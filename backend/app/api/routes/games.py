from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy.orm import Session, aliased, joinedload

from app.api.deps import get_db
from app.core.rate_limit import enforce_rate_limit
from app.models.sport import Game, League, Team
from app.schemas.sport import GameDetailOut, GameOut
from app.services import mlb_service, translation_service

router = APIRouter(tags=["games"])


@router.get("/leagues/{league_key}/games", response_model=list[GameOut])
def list_games(
    league_key: str = Path(pattern=r"^[a-z0-9_]{1,40}$"),
    game_date: date | None = Query(default=None, description="Fecha exacta (YYYY-MM-DD). Si no se da, usa una ventana de 24h."),
    status_filter: str | None = Query(default=None, alias="status", pattern="^(live|final|scheduled)$"),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    league = db.query(League).filter(League.key == league_key).first()
    if not league:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liga no encontrada.")

    # Se excluyen partidos donde el equipo local o visitante es un
    # "placeholder" (ej. "American League"/"National League" del Juego de
    # Estrellas de MLB, que no son franquicias reales): mismo criterio que
    # ya se aplica en posiciones y en la búsqueda de estadísticas.
    HomeTeamRow = aliased(Team)
    AwayTeamRow = aliased(Team)
    games_query = (
        db.query(Game)
        .options(joinedload(Game.home_team), joinedload(Game.away_team))
        .join(HomeTeamRow, Game.home_team_id == HomeTeamRow.id)
        .join(AwayTeamRow, Game.away_team_id == AwayTeamRow.id)
        .filter(Game.league_id == league.id)
        .filter(HomeTeamRow.is_placeholder.is_(False))
        .filter(AwayTeamRow.is_placeholder.is_(False))
    )

    if game_date:
        # Fecha explícita: se respeta el día calendario exacto pedido.
        games_query = games_query.filter(
            Game.start_time >= datetime.combine(game_date, datetime.min.time(), tzinfo=timezone.utc)
        ).filter(Game.start_time < datetime.combine(game_date, datetime.max.time(), tzinfo=timezone.utc))
    else:
        # Sin fecha explícita ("hoy" por defecto): se usa una ventana móvil de
        # 24h hacia atrás y 7 días hacia adelante, en vez de un día calendario
        # UTC fijo. Un día calendario fijo pierde partidos que cruzan la
        # medianoche UTC (ej. un juego de la Costa Oeste en vivo a la 1 AM UTC
        # queda fuera de "hoy" aunque esté sucediendo ahora mismo), y la
        # ventana de 7 días permite ver "próximos" para predecir (la sync de
        # NBA guarda ayer -> +7 días a propósito).
        current_time = datetime.now(timezone.utc)
        games_query = games_query.filter(Game.start_time >= current_time - timedelta(hours=24)).filter(
            Game.start_time <= current_time + timedelta(days=7)
        )

    if status_filter:
        games_query = games_query.filter(Game.status == status_filter)

    return games_query.order_by(Game.start_time.asc()).limit(limit).all()


@router.get("/games/{game_id}", response_model=GameDetailOut)
def get_game_detail(game_id: int = Path(gt=0, le=2147483647), db: Session = Depends(get_db)):
    """
    Detalle completo de un juego: incluye 'details' (JSON) con información
    específica del deporte, por ejemplo en béisbol: pitcher ganador,
    perdedor, salvamento y líderes ofensivos del juego.
    """
    HomeTeamRow = aliased(Team)
    AwayTeamRow = aliased(Team)
    target_game = (
        db.query(Game)
        .options(joinedload(Game.home_team), joinedload(Game.away_team))
        .join(HomeTeamRow, Game.home_team_id == HomeTeamRow.id)
        .join(AwayTeamRow, Game.away_team_id == AwayTeamRow.id)
        .filter(Game.id == game_id)
        .filter(HomeTeamRow.is_placeholder.is_(False))
        .filter(AwayTeamRow.is_placeholder.is_(False))
        .first()
    )
    if not target_game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partido no encontrado.")
    return target_game


@router.get("/games/{game_id}/live")
async def get_game_live_situation(
    request: Request,
    game_id: int = Path(gt=0, le=2147483647),
    lang: str = Query(default="es", pattern="^(es|en)$"),
    db: Session = Depends(get_db),
):
    """
    Situación en vivo de un juego de béisbol (bases, outs, bateador,
    pitcher, última jugada): sirve para MLB y para la LIDOM, porque ambas
    se sirven desde la misma MLB Stats API. A diferencia de /games/{id},
    esto consulta a la API DIRECTAMENTE en el momento de la petición, sin
    pasar por la base de datos ni esperar al ciclo de sincronización de 5
    minutos — así el frontend puede sondear este endpoint cada pocos
    segundos y mostrar algo realmente "al momento" mientras el usuario ve
    el partido.

    lang: si es "es", la descripción de "última jugada" se traduce al
    momento (cambia en cada jugada, así que no tiene sentido guardarla
    traducida). Nombres de jugadores nunca se traducen.
    """
    target_game = db.query(Game).options(joinedload(Game.league)).filter(Game.id == game_id).first()
    if not target_game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partido no encontrado.")

    if target_game.league.data_provider != "mlb_stats_api":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El detalle en vivo solo está disponible para partidos servidos por la MLB Stats API.",
        )

    if target_game.status != "live":
        return {"status": target_game.status, "situation": None}

    # Endpoint costoso (1 llamada externa a MLB por request + traducción):
    # rate-limit para que un sondeo agresivo no tumbe la cuota ni el servidor.
    enforce_rate_limit(request, bucket="games_live", limit=30, window_seconds=60)

    try:
        live_feed = await mlb_service.get_live_feed(int(target_game.external_id))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo obtener el estado en vivo del partido."
        )

    situation_payload = mlb_service.extract_live_situation(live_feed)
    if lang == "es" and situation_payload.get("last_play"):
        situation_payload["last_play"] = translation_service.translate_to_spanish(situation_payload["last_play"]) or situation_payload[
            "last_play"
        ]

    return {"status": target_game.status, "situation": situation_payload}
