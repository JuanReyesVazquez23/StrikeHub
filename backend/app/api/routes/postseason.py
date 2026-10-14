"""
Panorama de la Postemporada MLB: bracket vivo (Wild Card -> Divisionales ->
Campeonato -> Serie Mundial) construido desde la MLB Stats API.

Fuentes (ambas oficiales, gratuitas y sin key):
  - /schedule con gameType F,D,L,W  -> juegos y marcadores reales.
  - /standings (temporada regular)  -> sembrados #1..#6 por liga.

La lógica de armado vive en app/services/postseason_service.py (pura y
testeable). Aquí solo se orquesta: caché, rate limit y manejo de errores.

Comportamiento:
  - Caché en memoria por temporada: 45 s si hay un juego en vivo, 180 s en
    otro caso y 600 s si todavía no hay postemporada.
  - Si la MLB API falla pero hay una respuesta previa, se devuelve esa con
    stale=true en lugar de romper la página.
  - Si no hay juegos de postemporada, responde postseason_active=false.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.rate_limit import enforce_rate_limit
from app.models.sport import League, Team
from app.services import mlb_service
from app.services.postseason_service import build_bracket, has_live_game

logger = logging.getLogger("bfb.postseason")

router = APIRouter(prefix="/postseason", tags=["postseason"])

_TTL_LIVE_SECONDS = 45
_TTL_IDLE_SECONDS = 180
_TTL_INACTIVE_SECONDS = 600
_STANDINGS_TTL_SECONDS = 3600  # los sembrados no cambian durante la postemporada
_STALE_MAX_SECONDS = 6 * 3600  # tope para servir datos viejos si la API falla

# Primera temporada con el formato actual de 12 equipos (3 series de Wild Card por liga).
_MIN_SEASON = 2022

_bracket_cache: dict[int, dict] = {}
_standings_cache: dict[int, dict] = {}
_season_locks: dict[int, asyncio.Lock] = {}


def _season_lock(season_year: int) -> asyncio.Lock:
    season_lock = _season_locks.get(season_year)
    if season_lock is None:
        season_lock = _season_locks[season_year] = asyncio.Lock()
    return season_lock


async def _get_cached_standings(season_year: int) -> dict | None:
    """Posiciones de temporada regular (cacheadas 1 h). Tolera fallos: devuelve None."""
    clock_now = time.monotonic()
    cached_standings = _standings_cache.get(season_year)
    if cached_standings and cached_standings["expires_at"] > clock_now:
        return cached_standings["data"]
    try:
        standings_response = await mlb_service.get_standings(season_year)
    except Exception:
        logger.exception("No se pudieron obtener las posiciones %d para los sembrados.", season_year)
        return cached_standings["data"] if cached_standings else None
    _standings_cache[season_year] = {"data": standings_response, "expires_at": clock_now + _STANDINGS_TTL_SECONDS}
    return standings_response


def _load_team_logos(database: Session) -> dict[str, str | None]:
    """Logos de equipos desde la BD. Si falla, el servicio usa el CDN de MLB."""
    logo_by_team_id: dict[str, str | None] = {}
    try:
        mlb_league = database.query(League).filter(League.key == "mlb").first()
        if mlb_league:
            for team_row in database.query(Team).filter(Team.league_id == mlb_league.id).all():
                logo_by_team_id[str(team_row.external_id)] = team_row.logo_url
    except Exception:
        logger.exception("No se pudieron leer los logos de equipos de la BD.")
    return logo_by_team_id


async def _assemble_bracket_payload(season_year: int, database: Session) -> tuple[dict, int]:
    postseason_schedule = await mlb_service.get_postseason_schedule(season_year)
    has_scheduled_games = any(schedule_day.get("games") for schedule_day in postseason_schedule.get("dates", []) or [])
    regular_standings = await _get_cached_standings(season_year) if has_scheduled_games else None
    bracket_payload = build_bracket(postseason_schedule, regular_standings, _load_team_logos(database) if has_scheduled_games else {}, season=season_year)

    if not bracket_payload["postseason_active"]:
        cache_ttl = _TTL_INACTIVE_SECONDS
    elif has_live_game(bracket_payload):
        cache_ttl = _TTL_LIVE_SECONDS
    else:
        cache_ttl = _TTL_IDLE_SECONDS
    return bracket_payload, cache_ttl


@router.get("/bracket")
async def get_bracket(
    request: Request,
    season: int | None = Query(default=None, ge=_MIN_SEASON, le=2100),
    db: Session = Depends(get_db),
):
    """
    Bracket de postemporada de la temporada indicada (default: año actual).

    Respuesta: { season, postseason_active, seeds_available, updated_at, stale,
                 al: [5 series], nl: [5 series], world_series, champion }.
    Cada serie trae: id, slot (WC_A, WC_B, DS_A, DS_B, CS, WS), round, league,
    best_of, status (pending|scheduled|live|in_progress|final), teams (2
    posiciones; null = por definir), winner_id y games.
    """
    enforce_rate_limit(request, bucket="postseason", limit=30, window_seconds=60)

    season_year = season or datetime.now(timezone.utc).year
    cached_bracket = _bracket_cache.get(season_year)
    if cached_bracket and cached_bracket["expires_at"] > time.monotonic():
        return cached_bracket["payload"]

    # Un solo refresco a la vez por temporada: evita varias llamadas idénticas a la MLB API.
    async with _season_lock(season_year):
        cached_bracket = _bracket_cache.get(season_year)
        if cached_bracket and cached_bracket["expires_at"] > time.monotonic():
            return cached_bracket["payload"]
        try:
            bracket_payload, cache_ttl = await _assemble_bracket_payload(season_year, db)
        except Exception:
            logger.exception("No se pudo obtener la postemporada %d.", season_year)
            if cached_bracket and time.monotonic() - cached_bracket["built_at"] < _STALE_MAX_SECONDS:
                return {**cached_bracket["payload"], "stale": True}
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No se pudo obtener la postemporada.",
            )
        clock_now = time.monotonic()
        _bracket_cache[season_year] = {"payload": bracket_payload, "expires_at": clock_now + cache_ttl, "built_at": clock_now}
        return bracket_payload
