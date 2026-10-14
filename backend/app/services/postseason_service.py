"""
Lógica del bracket de postemporada MLB (formato de 12 equipos, vigente desde 2022).

Este módulo es PURO: recibe los JSON crudos de la MLB Stats API (schedule y
standings) y devuelve el bracket ya armado. No hace llamadas de red ni toca la
base de datos, así que se puede probar sin levantar el servidor
(ver backend/tests/test_postseason_service.py).

Estructura fija del cuadro, por liga (AL y NL):

    Wild Card (mejor de 3):   #3 vs #6      #4 vs #5
    Divisional (mejor de 5):  #2 vs ganador(3/6)   #1 vs ganador(4/5)
    Campeonato (mejor de 7):  ganador DS_A vs ganador DS_B
    Serie Mundial (mejor de 7): campeón AL vs campeón NL

Los "sembrados" (#1..#6) se calculan desde las posiciones de temporada
regular: los 3 líderes de división son #1-#3 (por récord) y los 3 comodines
son #4-#6. Los juegos reales de la postemporada se ubican en su casilla del
cuadro por los equipos que participan, y los ganadores avanzan solos a la
siguiente ronda, aun cuando esa serie todavía no tenga juegos programados.
"""
from __future__ import annotations

from datetime import datetime, timezone

AL_LEAGUE_ID = 103
NL_LEAGUE_ID = 104
_LEAGUE_BY_ID = {AL_LEAGUE_ID: "AL", NL_LEAGUE_ID: "NL"}

# gameType de la MLB Stats API -> ronda.
_ROUND_BY_GAME_TYPE = {"F": "WC", "D": "DS", "L": "CS", "W": "WS"}
# Respaldo por descripción si por algún motivo gameType no viniera.
_ROUND_BY_DESCRIPTION = (
    ("wild card", "WC"),
    ("division", "DS"),
    ("championship", "CS"),
    ("world series", "WS"),
)
BEST_OF = {"WC": 3, "DS": 5, "CS": 7, "WS": 7}

# Ids fijos de equipos MLB -> (abreviatura, color primario). Sirven de respaldo
# cuando la API no trae la abreviatura y para colorear el cuadro.
TEAM_META: dict[str, tuple[str, str]] = {
    "108": ("LAA", "#BA0021"),
    "109": ("AZ", "#A71930"),
    "110": ("BAL", "#DF4601"),
    "111": ("BOS", "#BD3039"),
    "112": ("CHC", "#0E3386"),
    "113": ("CIN", "#C6011F"),
    "114": ("CLE", "#00385D"),
    "115": ("COL", "#33006F"),
    "116": ("DET", "#0C2340"),
    "117": ("HOU", "#EB6E1F"),
    "118": ("KC", "#004687"),
    "119": ("LAD", "#005A9C"),
    "120": ("WSH", "#AB0003"),
    "121": ("NYM", "#002D72"),
    "133": ("ATH", "#003831"),
    "134": ("PIT", "#FDB827"),
    "135": ("SD", "#2F241D"),
    "136": ("SEA", "#0C2C56"),
    "137": ("SF", "#FD5A1E"),
    "138": ("STL", "#C41E3A"),
    "139": ("TB", "#092C5C"),
    "140": ("TEX", "#003278"),
    "141": ("TOR", "#134A8E"),
    "142": ("MIN", "#002B5C"),
    "143": ("PHI", "#E81828"),
    "144": ("ATL", "#CE1141"),
    "145": ("CWS", "#27251F"),
    "146": ("MIA", "#00A3E0"),
    "147": ("NYY", "#0C2340"),
    "158": ("MIL", "#12284B"),
}
_DEFAULT_COLOR = "#3d3d43"


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _parse_optional_int(raw_value) -> int | None:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _normalize_team_id(raw_value) -> str | None:
    """Normaliza un id de equipo a str (o None si no es válido)."""
    parsed_id = _parse_optional_int(raw_value)
    return str(parsed_id) if parsed_id else None


def _detect_round(schedule_game: dict) -> str | None:
    round_from_type = _ROUND_BY_GAME_TYPE.get(str(schedule_game.get("gameType") or "").upper())
    if round_from_type:
        return round_from_type
    series_description = (schedule_game.get("seriesDescription") or "").lower()
    for keyword, round_code in _ROUND_BY_DESCRIPTION:
        if keyword in series_description:
            return round_code
    return None


def _classify_game_status(schedule_game: dict) -> str:
    game_status = schedule_game.get("status") or {}
    detailed_state = (game_status.get("detailedState") or "").lower()
    if "postponed" in detailed_state or "cancel" in detailed_state:
        return "postponed"
    abstract_state = (game_status.get("abstractGameState") or "").lower()
    if abstract_state == "final" or "final" in detailed_state or "game over" in detailed_state:
        return "final"
    if abstract_state == "live" or "progress" in detailed_state or "review" in detailed_state:
        return "live"
    return "scheduled"


def _resolve_team_logo(team_id: str, logos: dict[str, str | None]) -> str:
    return logos.get(team_id) or f"https://www.mlbstatic.com/team-logos/{team_id}.svg"


# --------------------------------------------------------------------------
# Sembrados (seeds) desde las posiciones de temporada regular
# --------------------------------------------------------------------------
def compute_seeds(standings: dict | None) -> dict[str, dict]:
    """
    Devuelve {team_id: {"league": "AL"|"NL", "seed": 1..6, "name": str}}.

    Solo incluye los 6 clasificados por liga. Si las posiciones faltan o están
    incompletas, devuelve lo que se pueda (el armado del bracket tolera eso).
    """
    if not standings:
        return {}

    teams_by_league: dict[str, list[dict]] = {"AL": [], "NL": []}
    for division_record in standings.get("records", []) or []:
        league = _LEAGUE_BY_ID.get(_parse_optional_int((division_record.get("league") or {}).get("id")))
        if not league:
            continue
        teams_by_league[league].extend(division_record.get("teamRecords", []) or [])

    def _rank_position(team_record: dict, rank_key: str) -> int:
        parsed_rank = _parse_optional_int(team_record.get(rank_key))
        return parsed_rank if parsed_rank is not None else 10**6

    def _winning_pct(team_record: dict) -> float:
        try:
            return float(team_record.get("winningPercentage") or 0)
        except (TypeError, ValueError):
            return 0.0

    seeds: dict[str, dict] = {}
    for league, league_teams in teams_by_league.items():
        division_winners = [
            team_record for team_record in league_teams
            if team_record.get("divisionLeader") is True or _parse_optional_int(team_record.get("divisionRank")) == 1
        ]
        winner_ids = {_normalize_team_id((team_record.get("team") or {}).get("id")) for team_record in division_winners}
        wildcard_contenders = [
            team_record for team_record in league_teams
            if _normalize_team_id((team_record.get("team") or {}).get("id")) not in winner_ids
            and _parse_optional_int(team_record.get("wildCardRank")) is not None
        ]
        division_winners.sort(key=lambda team_record: (_rank_position(team_record, "leagueRank"), -_winning_pct(team_record)))
        wildcard_contenders.sort(key=lambda team_record: (_rank_position(team_record, "wildCardRank"), -_winning_pct(team_record)))

        for position_index, team_record in enumerate(division_winners[:3]):
            _assign_seed(seeds, team_record, league, position_index + 1)
        for position_index, team_record in enumerate(wildcard_contenders[:3]):
            _assign_seed(seeds, team_record, league, position_index + 4)
    return seeds


def _assign_seed(seeds: dict, team_record: dict, league: str, seed: int) -> None:
    team = team_record.get("team") or {}
    team_id = _normalize_team_id(team.get("id"))
    if team_id:
        seeds[team_id] = {"league": league, "seed": seed, "name": team.get("name") or ""}


# --------------------------------------------------------------------------
# Series crudas desde el schedule
# --------------------------------------------------------------------------
def _group_series_by_matchup(schedule: dict) -> tuple[dict, dict, dict]:
    """
    Agrupa los juegos por (ronda, par de equipos).

    Devuelve (series, team_info, team_league_hint):
      - series: {(round, frozenset(ids)): {...juegos, victorias, ganador...}}
      - team_info: {team_id: {"name", "abbreviation"}}
      - team_league_hint: {team_id: "AL"|"NL"} sacado del objeto team hidratado
    """
    grouped_series: dict = {}
    team_info: dict[str, dict] = {}
    league_hint: dict[str, str] = {}

    for schedule_day in schedule.get("dates", []) or []:
        for schedule_game in schedule_day.get("games", []) or []:
            round_code = _detect_round(schedule_game)
            if not round_code:
                continue
            team_sides = schedule_game.get("teams") or {}
            home_side, away_side = team_sides.get("home") or {}, team_sides.get("away") or {}
            home_team, away_team = home_side.get("team") or {}, away_side.get("team") or {}
            home_id, away_id = _normalize_team_id(home_team.get("id")), _normalize_team_id(away_team.get("id"))
            if not home_id or not away_id or home_id == away_id:
                continue  # juego con equipos aún por definir

            for team_id, team_payload in ((home_id, home_team), (away_id, away_team)):
                info_entry = team_info.setdefault(team_id, {"name": "", "abbreviation": ""})
                info_entry["name"] = info_entry["name"] or team_payload.get("name") or ""
                info_entry["abbreviation"] = (
                    info_entry["abbreviation"] or team_payload.get("abbreviation") or TEAM_META.get(team_id, ("", ""))[0]
                )
                hint = _LEAGUE_BY_ID.get(_parse_optional_int((team_payload.get("league") or {}).get("id")))
                if hint:
                    league_hint[team_id] = hint

            matchup_key = (round_code, frozenset((home_id, away_id)))
            series_entry = grouped_series.get(matchup_key)
            if series_entry is None:
                series_entry = {
                    "round": round_code,
                    "ids": (home_id, away_id),
                    "best_of": BEST_OF[round_code],
                    "games": [],
                    "wins": {home_id: 0, away_id: 0},
                }
                grouped_series[matchup_key] = series_entry
            series_length = _parse_optional_int(schedule_game.get("gamesInSeries"))
            if series_length in (3, 5, 7):
                series_entry["best_of"] = series_length

            series_entry["games"].append(
                {
                    "id": schedule_game.get("gamePk"),
                    "game_number": _parse_optional_int(schedule_game.get("seriesGameNumber")),
                    "date": schedule_game.get("gameDate"),
                    "status": _classify_game_status(schedule_game),
                    "home_id": home_id,
                    "away_id": away_id,
                    "home_abbreviation": team_info[home_id]["abbreviation"],
                    "away_abbreviation": team_info[away_id]["abbreviation"],
                    "home_score": home_side.get("score"),
                    "away_score": away_side.get("score"),
                }
            )

    for series_entry in grouped_series.values():
        series_entry["games"].sort(key=lambda series_game: (series_game["date"] or "", series_game["game_number"] or 0))
        for series_game in series_entry["games"]:
            home_runs, away_runs = series_game["home_score"], series_game["away_score"]
            if series_game["status"] != "final" or home_runs is None or away_runs is None or home_runs == away_runs:
                continue
            series_entry["wins"][series_game["home_id"] if home_runs > away_runs else series_game["away_id"]] += 1
        wins_to_clinch = series_entry["best_of"] // 2 + 1
        series_entry["winner_id"] = next((team_id for team_id, win_count in series_entry["wins"].items() if win_count >= wins_to_clinch), None)
        if series_entry["winner_id"]:
            # Juegos "si es necesario" que ya no se jugaron: no se muestran.
            series_entry["games"] = [series_game for series_game in series_entry["games"] if series_game["status"] in ("final", "live")]
    return grouped_series, team_info, league_hint


# --------------------------------------------------------------------------
# Armado del bracket
# --------------------------------------------------------------------------
def build_bracket(
    schedule: dict,
    standings: dict | None = None,
    logos: dict[str, str | None] | None = None,
    season: int | None = None,
) -> dict:
    logos = logos or {}
    seeds = compute_seeds(standings)
    grouped_series, team_info, league_hint = _group_series_by_matchup(schedule)
    has_postseason_games = bool(grouped_series)

    for team_id, seed_info in seeds.items():
        info_entry = team_info.setdefault(team_id, {"name": "", "abbreviation": TEAM_META.get(team_id, ("", ""))[0]})
        info_entry["name"] = info_entry["name"] or seed_info["name"]
        info_entry["abbreviation"] = info_entry["abbreviation"] or TEAM_META.get(team_id, ("", ""))[0]

    def resolve_league(team_id: str) -> str | None:
        return (seeds.get(team_id) or {}).get("league") or league_hint.get(team_id)

    has_complete_seeds = all(
        sum(1 for seed_info in seeds.values() if seed_info["league"] == league_code) == 6 for league_code in ("AL", "NL")
    )

    payload = {
        "season": season,
        "postseason_active": has_postseason_games,
        "seeds_available": has_complete_seeds,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stale": False,
        "al": [],
        "nl": [],
        "world_series": None,
        "champion": None,
    }
    if not has_postseason_games:
        return payload

    consumed_series_keys: set = set()

    def find_series_for_slot(round_code: str, league_code: str | None, expected_team_ids: list[str | None], allow_first_available: bool = False):
        """Busca la serie real que corresponde a una casilla del cuadro."""
        wanted_ids = {team_id for team_id in expected_team_ids if team_id}
        candidates = [
            (matchup_key, series_entry) for matchup_key, series_entry in grouped_series.items()
            if series_entry["round"] == round_code and matchup_key not in consumed_series_keys
            and (league_code is None or resolve_league(series_entry["ids"][0]) == league_code or resolve_league(series_entry["ids"][1]) == league_code)
        ]
        candidates.sort(key=lambda candidate: candidate[1]["games"][0]["date"] or "")
        for matchup_key, series_entry in candidates:
            if wanted_ids & set(series_entry["ids"]):
                consumed_series_keys.add(matchup_key)
                return series_entry
        # Sin sembrados no se puede casar por equipo: se asigna por orden de fecha.
        # En CS/WS solo existe una serie por liga, así que también aplica.
        if candidates and (allow_first_available or not has_complete_seeds):
            matchup_key, series_entry = candidates[0]
            consumed_series_keys.add(matchup_key)
            return series_entry
        return None

    def build_team_card(team_id: str | None, matched_series: dict | None) -> dict | None:
        if not team_id:
            return None
        team_details = team_info.get(team_id, {})
        series_winner = matched_series.get("winner_id") if matched_series else None
        return {
            "id": team_id,
            "name": team_details.get("name", ""),
            "abbreviation": team_details.get("abbreviation") or TEAM_META.get(team_id, ("", ""))[0],
            "logo_url": _resolve_team_logo(team_id, logos),
            "color": TEAM_META.get(team_id, ("", _DEFAULT_COLOR))[1],
            "seed": (seeds.get(team_id) or {}).get("seed"),
            "wins": matched_series["wins"].get(team_id, 0) if matched_series else 0,
            "is_winner": bool(series_winner and series_winner == team_id),
            "eliminated": bool(series_winner and series_winner != team_id),
        }

    def build_series_card(slot_code: str, league_code: str | None, round_code: str, projected_team_ids: list[str | None], matched_series: dict | None) -> dict:
        ordered_team_ids: list[str | None] = [None, None]
        if matched_series:
            actual_team_ids = list(matched_series["ids"])
            for position, projected_id in enumerate(projected_team_ids):
                if projected_id in actual_team_ids:
                    ordered_team_ids[position] = projected_id
            unplaced_team_ids = [team_id for team_id in actual_team_ids if team_id not in ordered_team_ids]
            if round_code == "WS":
                unplaced_team_ids.sort(key=lambda team_id: resolve_league(team_id) != "AL")
            for position in range(2):
                if ordered_team_ids[position] is None and unplaced_team_ids:
                    ordered_team_ids[position] = unplaced_team_ids.pop(0)
        else:
            ordered_team_ids = list(projected_team_ids)

        if not matched_series:
            series_status = "pending"
        elif matched_series["winner_id"]:
            series_status = "final"
        elif any(series_game["status"] == "live" for series_game in matched_series["games"]):
            series_status = "live"
        elif any(series_game["status"] == "final" for series_game in matched_series["games"]):
            series_status = "in_progress"
        else:
            series_status = "scheduled"

        return {
            "id": f"{league_code}_{slot_code}" if league_code else slot_code,
            "slot": slot_code,
            "round": round_code,
            "league": league_code,
            "best_of": matched_series["best_of"] if matched_series else BEST_OF[round_code],
            "status": series_status,
            "teams": [build_team_card(team_id, matched_series) for team_id in ordered_team_ids],
            "winner_id": matched_series["winner_id"] if matched_series else None,
            "games": matched_series["games"] if matched_series else [],
        }

    champions_by_league: dict[str, str | None] = {}
    for league_code in ("AL", "NL"):
        seeds_by_rank = {seed_info["seed"]: team_id for team_id, seed_info in seeds.items() if seed_info["league"] == league_code}
        seed_1, seed_2, seed_3, seed_4, seed_5, seed_6 = (seeds_by_rank.get(rank) for rank in range(1, 7))

        wildcard_a_raw = find_series_for_slot("WC", league_code, [seed_3, seed_6])
        wildcard_b_raw = find_series_for_slot("WC", league_code, [seed_4, seed_5])
        wildcard_a = build_series_card("WC_A", league_code, "WC", [seed_6, seed_3], wildcard_a_raw)
        wildcard_b = build_series_card("WC_B", league_code, "WC", [seed_5, seed_4], wildcard_b_raw)

        division_a_raw = find_series_for_slot("DS", league_code, [seed_2])
        division_b_raw = find_series_for_slot("DS", league_code, [seed_1])
        division_a = build_series_card("DS_A", league_code, "DS", [wildcard_a["winner_id"], seed_2], division_a_raw)
        division_b = build_series_card("DS_B", league_code, "DS", [wildcard_b["winner_id"], seed_1], division_b_raw)

        championship_raw = find_series_for_slot("CS", league_code, [division_a["winner_id"], division_b["winner_id"]], allow_first_available=True)
        championship = build_series_card("CS", league_code, "CS", [division_a["winner_id"], division_b["winner_id"]], championship_raw)

        champions_by_league[league_code] = championship["winner_id"]
        payload["al" if league_code == "AL" else "nl"] = [wildcard_a, wildcard_b, division_a, division_b, championship]

    world_series_raw = find_series_for_slot("WS", None, [champions_by_league["AL"], champions_by_league["NL"]], allow_first_available=True)
    world_series_card = build_series_card("WS", None, "WS", [champions_by_league["AL"], champions_by_league["NL"]], world_series_raw)
    payload["world_series"] = world_series_card
    if world_series_card["winner_id"]:
        champion_card = next((team_card for team_card in world_series_card["teams"] if team_card and team_card["id"] == world_series_card["winner_id"]), None)
        payload["champion"] = champion_card
    return payload


def has_live_game(payload: dict) -> bool:
    bracket_series = (payload.get("al") or []) + (payload.get("nl") or [])
    if payload.get("world_series"):
        bracket_series.append(payload["world_series"])
    return any(series_entry.get("status") == "live" for series_entry in bracket_series)
