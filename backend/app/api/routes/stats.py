from datetime import datetime, timezone
import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.core.rate_limit import enforce_rate_limit
from app.models.sport import Game, League, Player, Sport, Team
from app.services import mlb_service

logger = logging.getLogger("bfb.stats")

router = APIRouter(prefix="/stats", tags=["stats"])

# Categorías verificadas contra la API real (oct-2026): solo conteo + ERA.
# battingAverage se excluye a propósito (sin mínimo de turnos devuelve pitchers).
LEADER_CATEGORIES = {
    "hitting": ["homeRuns", "runsBattedIn", "stolenBases"],
    "pitching": ["wins", "earnedRunAverage", "strikeouts", "saves"],
}

_leaders_cache: dict = {"expires_at": 0.0, "payload": None}
LEADERS_TTL_SECONDS = 1800  # 30 min: en offseason casi no cambian


def _escape_like_search_term(search_term: str) -> str:
    """Escapa %, _ y \\ para que el buscador no permita patrones LIKE arbitrarios."""
    return search_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/search")
def search_entities(
    request: Request,
    q: str = Query(min_length=2, max_length=80, description="Nombre a buscar (mínimo 2 caracteres)"),
    entity_type: str = Query(default="team", alias="type", pattern="^(team|player)$"),
    sport_key: str = Query(alias="sport", pattern="^(baseball)$"),
    db: Session = Depends(get_db),
):
    """
    Búsqueda por nombre para el autocompletado del buscador de estadísticas.
    Nunca se busca por ID: el usuario escribe un nombre y elige de la lista.

    IMPORTANTE: "sport" es obligatorio y nunca se cruzan deportes — si la
    página está en Fútbol, jamás debe aparecer un resultado de béisbol o
    basketball, y viceversa.
    """
    sport = db.query(Sport).filter(Sport.key == sport_key).first()
    if not sport:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deporte no encontrado.")

    enforce_rate_limit(request, bucket="stats_search", limit=30, window_seconds=60)

    like_pattern = f"%{_escape_like_search_term(q.strip())}%"
    if entity_type == "player":
        matching_players = (
            db.query(Player)
            .join(Team, Player.team_id == Team.id)
            .join(League, Team.league_id == League.id)
            .options(joinedload(Player.team))
            .filter(Player.full_name.ilike(like_pattern, escape="\\"), League.sport_id == sport.id)
            .limit(10)
            .all()
        )
        return [
            {
                "id": player_row.id,
                "type": "player",
                "label": player_row.full_name,
                "sublabel": f"{player_row.position or ''} · {player_row.team.name if player_row.team else ''}".strip(" ·"),
            }
            for player_row in matching_players
        ]

    matching_teams = (
        db.query(Team)
        .join(League, Team.league_id == League.id)
        .filter(Team.name.ilike(like_pattern, escape="\\"), Team.is_placeholder.is_(False), League.sport_id == sport.id)
        .limit(10)
        .all()
    )
    return [
        {
            "id": team_row.id,
            "type": "team",
            "label": team_row.name,
            "sublabel": team_row.division or team_row.city or "",
            "logo_url": team_row.logo_url,
        }
        for team_row in matching_teams
    ]


@router.get("/leaders")
async def season_leaders(
    request: Request,
    season: int | None = Query(default=None, ge=2000, le=2100),
):
    """
    Líderes de la temporada (bateo y pitcheo) para el contenido de
    offseason. 7 llamadas a MLB en el peor caso, cacheadas 30 minutos.
    """
    enforce_rate_limit(request, bucket="stats_leaders", limit=10, window_seconds=60)

    season_year = season or datetime.now(timezone.utc).year
    clock_now = time.monotonic()
    if _leaders_cache["payload"] is not None and _leaders_cache["expires_at"] > clock_now:
        cached_payload = _leaders_cache["payload"]
        if cached_payload.get("season") == season_year:
            return cached_payload

    leader_groups: dict[str, dict] = {}
    try:
        # En paralelo: 7 llamadas secuenciales tardaban ~9s.
        category_pairs = [(group, category) for group, categories in LEADER_CATEGORIES.items() for category in categories]
        raw_responses = await asyncio.gather(
            *[mlb_service.get_stat_leaders(season_year, category, limit=5) for _, category in category_pairs]
        )
        for (group, category), raw_response in zip(category_pairs, raw_responses):
            leader_entries = (raw_response.get("leagueLeaders") or [{}])[0].get("leaders", [])
            leader_groups.setdefault(group, {})[category] = [
                {
                    "rank": leader_entry.get("rank"),
                    "name": (leader_entry.get("person") or {}).get("fullName", ""),
                    "team": (leader_entry.get("team") or {}).get("name", ""),
                    "team_id": (leader_entry.get("team") or {}).get("id"),
                    "value": leader_entry.get("value"),
                }
                for leader_entry in leader_entries
            ]
    except Exception:
        logger.exception("No se pudieron obtener los líderes %d.", season_year)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudieron obtener los líderes de la temporada.",
        )

    payload = {"season": season_year, "groups": leader_groups}
    _leaders_cache["payload"] = payload
    _leaders_cache["expires_at"] = clock_now + LEADERS_TTL_SECONDS
    return payload


def _load_team_profile(team_id: int, db: Session) -> dict:
    """
    Construye el perfil completo de un equipo (récord, posición y sus
    últimos partidos). Función compartida entre el endpoint de un solo
    equipo y el de comparación, para no duplicar la misma lógica dos veces.
    """
    team = db.query(Team).options(joinedload(Team.league)).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipo no encontrado.")

    recent_finished_games = (
        db.query(Game)
        .options(joinedload(Game.home_team), joinedload(Game.away_team))
        .filter(Game.status == "final")
        .filter((Game.home_team_id == team.id) | (Game.away_team_id == team.id))
        .order_by(Game.start_time.desc())
        .limit(5)
        .all()
    )

    def _format_result_line(finished_game) -> dict:
        is_home_game = finished_game.home_team_id == team.id
        team_runs = finished_game.home_score if is_home_game else finished_game.away_score
        opponent = finished_game.away_team if is_home_game else finished_game.home_team
        opponent_runs = finished_game.away_score if is_home_game else finished_game.home_score
        result_code = "W" if (team_runs or 0) > (opponent_runs or 0) else "L"
        return {
            "date": finished_game.start_time.date().isoformat(),
            "rival": opponent.name,
            "score": f"{team_runs}-{opponent_runs}",
            "outcome": result_code,
        }

    return {
        "id": team.id,
        "name": team.name,
        "short_name": team.short_name,
        "logo_url": team.logo_url,
        "league": team.league.name if team.league else None,
        "sport_id": team.league.sport_id if team.league else None,
        "record": {"wins": team.wins, "losses": team.losses, "ties": team.ties, "win_pct": team.win_pct},
        "division": team.division,
        "conference": team.conference,
        "recent_results": [_format_result_line(finished_game) for finished_game in recent_finished_games],
    }


@router.get("/team/{team_id}")
def team_stats(team_id: int = Path(gt=0, le=2147483647), db: Session = Depends(get_db)):
    """Perfil real de un equipo: récord, posición y sus últimos partidos jugados."""
    profile = _load_team_profile(team_id, db)
    profile.pop("sport_id", None)  # detalle interno, no se expone en el perfil individual
    return profile


@router.get("/teams/compare")
def compare_teams(
    request: Request,
    id_a: int = Query(gt=0, le=2147483647, description="ID del primer equipo"),
    id_b: int = Query(gt=0, le=2147483647, description="ID del segundo equipo"),
    db: Session = Depends(get_db),
):
    """
    Compara dos equipos lado a lado. NUNCA se permite comparar equipos de
    deportes distintos (ej. un equipo de MLB contra uno de NBA) — se
    valida explícitamente y se rechaza con 400 si no coinciden.
    """
    enforce_rate_limit(request, bucket="stats_compare", limit=20, window_seconds=60)
    if id_a == id_b:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Elige dos equipos distintos.")

    team_a = _load_team_profile(id_a, db)
    team_b = _load_team_profile(id_b, db)

    if team_a["sport_id"] is None or team_b["sport_id"] is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo determinar el deporte de uno de los equipos.",
        )
    if team_a["sport_id"] != team_b["sport_id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pueden comparar equipos de deportes distintos.",
        )

    team_a.pop("sport_id", None)
    team_b.pop("sport_id", None)
    return {"team_a": team_a, "team_b": team_b}


async def _load_player_profile(player_id: int, db: Session) -> dict:
    """
    Construye el perfil completo de un jugador (posición, equipo, y
    estadísticas reales si es de MLB). Función compartida entre el
    endpoint de un solo jugador y el de comparación, para no duplicar
    la misma lógica dos veces.
    """
    player = (
        db.query(Player)
        .options(joinedload(Player.team).joinedload(Team.league))
        .filter(Player.id == player_id)
        .first()
    )
    if not player:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jugador no encontrado.")

    batting_line = None
    pitching_line = None

    is_mlb_rostered = player.team and player.team.league and player.team.league.data_provider == "mlb_stats_api"
    if is_mlb_rostered:
        try:
            current_season_year = datetime.now(timezone.utc).year
            season_stats_response = await mlb_service.get_player_season_stats(int(player.external_id), current_season_year)
            batting_line = mlb_service.extract_batting_stats(season_stats_response["hitting"])
            pitching_line = mlb_service.extract_pitching_stats(season_stats_response["pitching"])
        except Exception:
            pass  # el perfil se muestra igual, solo sin números, en vez de fallar la petición completa

    return {
        "id": player.id,
        "full_name": player.full_name,
        "position": player.position,
        "jersey_number": player.jersey_number,
        "team": {
            "id": player.team.id,
            "name": player.team.name,
            "logo_url": player.team.logo_url,
        }
        if player.team
        else None,
        "sport_id": player.team.league.sport_id if player.team and player.team.league else None,
        "batting_stats": batting_line,
        "pitching_stats": pitching_line,
    }


@router.get("/player/{player_id}")
async def player_stats(
    request: Request,
    player_id: int = Path(gt=0, le=2147483647),
    db: Session = Depends(get_db),
):
    """
    Perfil real de un jugador: posición, número, equipo, y sus estadísticas
    reales de la temporada actual (home runs, hits, OBP, etc. si es
    bateador; wins, ERA, ponches si es pitcher).

    Los números se consultan en vivo a MLB Stats API en el momento de la
    búsqueda (solo para jugadores de esa liga por ahora). Si la consulta
    externa falla, se muestra igual el perfil del jugador sin números en
    vez de romper la página completa.
    """
    # 1 llamada externa por request (MLB/NBA/API-Football): rate-limit.
    enforce_rate_limit(request, bucket="stats_player", limit=20, window_seconds=60)
    profile = await _load_player_profile(player_id, db)
    profile.pop("sport_id", None)  # detalle interno, no se expone en el perfil individual
    return profile


@router.get("/players/compare")
async def compare_players(
    request: Request,
    id_a: int = Query(gt=0, le=2147483647, description="ID del primer jugador"),
    id_b: int = Query(gt=0, le=2147483647, description="ID del segundo jugador"),
    db: Session = Depends(get_db),
):
    """
    Compara dos jugadores lado a lado. NUNCA se permite comparar jugadores
    de deportes distintos (ej. un jugador de MLB contra uno de NBA) — se
    valida explícitamente y se rechaza con 400 si no coinciden.
    """
    # Hasta 4 llamadas externas por request (2 jugadores × MLB/NBA + fútbol):
    # límite más estricto para no agotar la cuota de 100/día de API-Football.
    enforce_rate_limit(request, bucket="stats_compare", limit=10, window_seconds=60)
    if id_a == id_b:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Elige dos jugadores distintos.")

    player_a = await _load_player_profile(id_a, db)
    player_b = await _load_player_profile(id_b, db)

    if player_a["sport_id"] is None or player_b["sport_id"] is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo determinar el deporte de uno de los jugadores.",
        )
    if player_a["sport_id"] != player_b["sport_id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pueden comparar jugadores de deportes distintos.",
        )

    player_a.pop("sport_id", None)
    player_b.pop("sport_id", None)
    return {"player_a": player_a, "player_b": player_b}
