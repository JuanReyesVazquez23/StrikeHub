"""
Cliente para la MLB Stats API oficial (https://statsapi.mlb.com).

Es una API pública, gratuita y sin necesidad de API key. Se usa como fuente
principal para la liga MLB (deporte: béisbol), incluyendo detalle de
pitchers abridores y ganadores/perdedores por juego.

Todas las funciones son async y usan httpx.AsyncClient. Los datos crudos
se devuelven como dicts (JSON) y son transformados/guardados en la capa de
sincronización (ver app/services/sync_service.py).
"""
from datetime import date

import httpx

from app.core.config import settings
from app.services.http_client import DEFAULT_HTTP_HTTP_TIMEOUT as HTTP_HTTP_TIMEOUT

MLB_SPORT_ID = 1  # id interno de MLB en statsapi.mlb.com (Grandes Ligas)

# IDs de división de MLB: fijos y permanentes (no cambian). Confirmados
# contra una respuesta real del endpoint /standings, que solo trae
# {"id": ..., "link": ...} en record["division"] -- NUNCA el nombre. El
# nombre hay que mapearlo por ID, no se puede pedir directamente.
MLB_DIVISION_NAMES = {
    200: "AL West",
    201: "AL East",
    202: "AL Central",
    203: "NL West",
    204: "NL East",
    205: "NL Central",
}


async def get_standings(season: int) -> dict:
    """Posiciones actuales de la MLB por división."""
    endpoint_url = f"{settings.MLB_STATS_API_BASE}/standings"
    query_params = {"leagueId": "103,104", "season": season, "standingsTypes": "regularSeason"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(endpoint_url, params=query_params)
        response.raise_for_status()
        return response.json()


async def get_schedule(game_date: date) -> dict:
    """
    Calendario/resultados del día indicado. Incluye pitchers probables y,
    si el juego ya inició/terminó, el linescore básico.
    """
    endpoint_url = f"{settings.MLB_STATS_API_BASE}/schedule"
    query_params = {
        "sportId": MLB_SPORT_ID,
        "date": game_date.isoformat(),
        "hydrate": "team,linescore,probablePitcher,decisions",
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(endpoint_url, params=query_params)
        response.raise_for_status()
        return response.json()


async def get_live_feed(mlb_game_id: int) -> dict:
    """
    Feed en vivo/boxscore completo de un juego: pitcher ganador, perdedor,
    salvamento, líderes ofensivos, etc. mlb_game_id es el id de juego de MLB.
    """
    endpoint_url = f"{settings.MLB_STATS_API_BASE.replace('/api/v1', '')}/api/v1.1/game/{mlb_game_id}/feed/live"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(endpoint_url)
        response.raise_for_status()
        return response.json()


async def get_postseason_schedule(season: int) -> dict:
    """
    Todos los juegos de postemporada (Wild Card, Divisionales, Campeonato y
    Serie Mundial) de la temporada. gameType: F = Wild Card, D = Division,
    L = League Championship, W = World Series. Con seriesStatus hidratado
    (marcador de la serie: quién va ganando y por cuánto).
    """
    endpoint_url = f"{settings.MLB_STATS_API_BASE}/schedule"
    query_params = {
        "sportId": MLB_SPORT_ID,
        "season": season,
        "gameType": "F,D,L,W",
        "hydrate": "seriesStatus,team",
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(endpoint_url, params=query_params)
        response.raise_for_status()
        return response.json()


async def get_stat_leaders(season: int, category: str, limit: int = 5) -> dict:
    """
    Líderes de la temporada en una categoría (ej. homeRuns, saves).
    OJO: no pedir promedios sin mínimo calificatorio (battingAverage
    devuelve pitchers con 2 turnos); solo categorías de conteo + ERA,
    que sí salen cuerdas. Ver LEADER_CATEGORIES en routes/stats.py.
    """
    endpoint_url = f"{settings.MLB_STATS_API_BASE}/stats/leaders"
    query_params = {
        "leaderCategories": category,
        "sportId": MLB_SPORT_ID,
        "season": season,
        "limit": limit,
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(endpoint_url, params=query_params)
        response.raise_for_status()
        return response.json()


def extract_live_situation(live_feed: dict) -> dict:
    """
    Extrae la situación de juego en vivo (bases, outs, bateador, pitcher,
    última jugada) del feed GUMBO de MLB. Estructura confirmada contra la
    documentación oficial de MLB Stats API (linescore.offense/defense).

    Las bases solo aparecen como clave en el JSON cuando están ocupadas
    (no vienen como null/false); por eso se detecta con bool(...) sobre la
    presencia de la clave, no comparando un valor.
    """
    linescore_data = live_feed.get("liveData", {}).get("linescore", {})
    offense = linescore_data.get("offense", {})
    defense = linescore_data.get("defense", {})
    current_play = live_feed.get("liveData", {}).get("plays", {}).get("currentPlay", {})

    return {
        "inning": linescore_data.get("currentInning"),
        "inning_half": linescore_data.get("inningHalf"),  # "Top" | "Bottom"
        "outs": linescore_data.get("outs", 0),
        "balls": linescore_data.get("balls", 0),
        "strikes": linescore_data.get("strikes", 0),
        "bases": {
            "first": bool(offense.get("first")),
            "second": bool(offense.get("second")),
            "third": bool(offense.get("third")),
        },
        "batter": offense.get("batter", {}).get("fullName"),
        "pitcher": defense.get("pitcher", {}).get("fullName"),
        "last_play": current_play.get("result", {}).get("description"),
    }


async def get_teams(season: int) -> dict:
    endpoint_url = f"{settings.MLB_STATS_API_BASE}/teams"
    query_params = {"sportId": MLB_SPORT_ID, "season": season}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(endpoint_url, params=query_params)
        response.raise_for_status()
        return response.json()


async def get_team_roster(team_id: int, season: int) -> dict:
    endpoint_url = f"{settings.MLB_STATS_API_BASE}/teams/{team_id}/roster"
    query_params = {"season": season}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(endpoint_url, params=query_params)
        response.raise_for_status()
        return response.json()


async def get_player_season_stats(person_id: int, season: int) -> dict:
    """
    Estadísticas reales de temporada de un jugador: bateo y pitcheo. Se
    consulta en vivo solo cuando el usuario busca a ese jugador (no se
    guarda en BD), así siempre está al día y no hace falta otra migración.
    Un bateador no tendrá datos de pitcheo y viceversa; eso es normal.
    """
    endpoint_url = f"{settings.MLB_STATS_API_BASE}/people/{person_id}/stats"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        hitting_response = await client.get(endpoint_url, params={"stats": "season", "group": "hitting", "season": season})
        pitching_response = await client.get(endpoint_url, params={"stats": "season", "group": "pitching", "season": season})
    hitting_response.raise_for_status()
    pitching_response.raise_for_status()
    return {"hitting": hitting_response.json(), "pitching": pitching_response.json()}


def _extract_first_split_stat(stats_response: dict) -> dict | None:
    stat_splits = (stats_response.get("stats") or [{}])[0].get("splits", [])
    return stat_splits[0]["stat"] if stat_splits else None


def extract_batting_stats(hitting_response: dict) -> dict | None:
    """Devuelve None si el jugador no tiene estadísticas de bateo esta temporada (ej. es pitcher puro)."""
    stat_entry = _extract_first_split_stat(hitting_response)
    if not stat_entry:
        return None
    return {
        "games": stat_entry.get("gamesPlayed"),
        "at_bats": stat_entry.get("atBats"),
        "hits": stat_entry.get("hits"),
        "home_runs": stat_entry.get("homeRuns"),
        "rbi": stat_entry.get("rbi"),
        "avg": stat_entry.get("avg"),
        "obp": stat_entry.get("obp"),
        "slg": stat_entry.get("slg"),
        "ops": stat_entry.get("ops"),
        "stolen_bases": stat_entry.get("stolenBases"),
    }


def extract_pitching_stats(pitching_response: dict) -> dict | None:
    """Devuelve None si el jugador no tiene estadísticas de pitcheo esta temporada (ej. es bateador puro)."""
    stat_entry = _extract_first_split_stat(pitching_response)
    if not stat_entry:
        return None
    return {
        "games": stat_entry.get("gamesPlayed"),
        "wins": stat_entry.get("wins"),
        "losses": stat_entry.get("losses"),
        "era": stat_entry.get("era"),
        "strikeouts": stat_entry.get("strikeOuts"),
        "saves": stat_entry.get("saves"),
        "innings_pitched": stat_entry.get("inningsPitched"),
        "whip": stat_entry.get("whip"),
    }


def extract_probable_pitchers(schedule_game: dict) -> dict:
    """Extrae de un juego del /schedule los pitchers abridores probables (para 'Jugadores Hoy')."""
    team_sides = schedule_game.get("teams", {})
    return {
        "home_pitcher": team_sides.get("home", {}).get("probablePitcher", {}).get("fullName"),
        "away_pitcher": team_sides.get("away", {}).get("probablePitcher", {}).get("fullName"),
    }


def extract_decisions(schedule_game: dict) -> dict:
    """Extrae pitcher ganador/perdedor/salvamento de un juego ya finalizado."""
    game_decisions = schedule_game.get("decisions", {})
    return {
        "winning_pitcher": game_decisions.get("winner", {}).get("fullName"),
        "losing_pitcher": game_decisions.get("loser", {}).get("fullName"),
        "save_pitcher": game_decisions.get("save", {}).get("fullName"),
    }
