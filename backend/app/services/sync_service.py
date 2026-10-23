"""
Sincronización periódica: trae datos reales de las APIs externas y los
guarda en PostgreSQL. Separar "sincronizar" de "servir" es lo que permite:

1) Respetar los límites de peticiones por minuto de las APIs externas.
2) Servir las páginas rápido (lectura local en vez de esperar a un tercero).
3) Resolver predicciones y otorgar puntos Strike cuando un partido termina.

Este archivo se ejecuta desde un scheduler (ver app/main.py, tarea en
background) o manualmente con `python -m app.services.sync_service`.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import Base, SessionLocal, engine
from app.core.logging_config import configure_logging
from app.core.migrations import run_lightweight_migrations
from app.models.favorite import Favorite
from app.models.prediction import Prediction
from app.models.sport import ExcludedTeam, Game, League, NewsArticle, Player, Sport, Team
from app.models.user import User
from app.services import (
    mlb_service,
    news_service,
    translation_service,
)
from app.services.mlb_service import LEAGUE_API_CONFIGS, StatsApiLeagueConfig
from app.services.probability_service import (
    estimate_home_win_probability,
    points_for_prediction,
    points_lost_for_prediction,
)

logger = logging.getLogger("bfb.sync")

CURRENT_SEASON = datetime.now(timezone.utc).year

# Con el calendario completo ya guardado, una liga de temporada corta como la
# LIDOM tiene siempre decenas de partidos futuros en BD. Si quedan menos que
# esto (temporada recién cargada, o ya casi terminando), vale la pena volver a
# pedir la temporada completa; si no, no se descarga la misma lista en cada
# ciclo de sincronización.
FULL_SCHEDULE_MIN_UPCOMING_GAMES = 15


def _get_or_create_sport(db: Session, sport_key: str, spanish_name: str, english_name: str) -> Sport:
    sport = db.query(Sport).filter(Sport.key == sport_key).first()
    if not sport:
        sport = Sport(key=sport_key, name_es=spanish_name, name_en=english_name)
        db.add(sport)
        db.commit()
        db.refresh(sport)
    return sport


def _get_or_create_league(db: Session, sport: Sport, league_key: str, league_name: str, provider: str, is_primary=False) -> League:
    league = db.query(League).filter(League.key == league_key).first()
    if not league:
        league = League(
            sport_id=sport.id, key=league_key, name=league_name, is_primary=is_primary, data_provider=provider
        )
        db.add(league)
        db.commit()
        db.refresh(league)
    elif league.data_provider != provider:
        # Se actualiza aunque ya exista: si cambiamos de proveedor en el
        # código, sin esto la BD
        # de producción se quedaría con el proveedor viejo para siempre.
        league.data_provider = provider
        db.commit()
    return league


def ensure_base_catalog(db: Session) -> None:
    """
    Crea el deporte (solo béisbol) y las ligas soportadas si todavía no
    existen (idempotente): MLB (temporada regular) y LIDOM (liga invernal
    dominicana). Ambas se sirven desde la misma MLB Stats API.
    """
    baseball = _get_or_create_sport(db, "baseball", "Béisbol", "Baseball")

    _get_or_create_league(db, baseball, "mlb", "MLB", provider="mlb_stats_api", is_primary=True)
    _get_or_create_league(db, baseball, "lidom", "LIDOM", provider="mlb_stats_api")


async def sync_league_teams_and_standings(league_key: str, api_config: StatsApiLeagueConfig) -> None:
    """
    Sincroniza los equipos y las posiciones de una liga. Funciona igual para
    la MLB (divisiones AL/NL) y para la LIDOM (un solo grupo, sin divisiones):
    la única diferencia la aporta api_config.
    """
    db = SessionLocal()
    try:
        league = db.query(League).filter(League.key == league_key).first()
        if not league:
            logger.warning("Liga '%s' no existe todavía en la BD; ejecuta ensure_base_catalog primero.", league_key)
            return
        if not league.sync_enabled:
            logger.info("Liga '%s' desactivada desde el panel de admin; se omite su sincronización.", league.key)
            return

        standings_response = await mlb_service.get_standings(CURRENT_SEASON, api_config)

        # El endpoint de standings trae el nombre completo, pero para el
        # nombre corto ("Yankees"/"Licey"), la abreviación ("NYY"/"LIC") y la
        # ciudad se necesita el endpoint /teams.
        teams_response = await mlb_service.get_teams(CURRENT_SEASON, api_config)
        team_details_by_external_id = {str(team_payload["id"]): team_payload for team_payload in teams_response.get("teams", [])}

        valid_external_ids: set[str] = set()
        excluded_ids = {
            e.external_id for e in db.query(ExcludedTeam).filter(ExcludedTeam.league_id == league.id).all()
        }
        for division_record in standings_response.get("records", []):
            division_id = division_record.get("division", {}).get("id")
            division_name = api_config.division_names.get(division_id)

            for team_standing in division_record.get("teamRecords", []):
                standing_team_info = team_standing["team"]
                external_id = str(standing_team_info["id"])
                if external_id in excluded_ids:
                    continue  # borrado a mano por el panel de admin; nunca se recrea
                valid_external_ids.add(external_id)
                team_details = team_details_by_external_id.get(external_id, {})
                # Se prefiere el nombre completo desde /teams ("Estrellas
                # Orientales"); el de /standings puede venir corto ("Estrellas").
                full_name = team_details.get("name") or standing_team_info["name"]

                team = (
                    db.query(Team)
                    .filter(Team.league_id == league.id, Team.external_id == external_id)
                    .first()
                )
                if not team:
                    team = Team(league_id=league.id, external_id=external_id, name=full_name)
                    db.add(team)

                wins = team_standing.get("wins", 0)
                losses = team_standing.get("losses", 0)
                games_played = wins + losses
                team.name = full_name
                team.short_name = team_details.get("teamName")  # ej. "Yankees" / "Licey"
                team.abbreviation = team_details.get("abbreviation")  # ej. "NYY" / "LIC"
                team.city = team_details.get("locationName")  # ej. "New York" / "Santo Domingo"
                # Logo oficial: patrón de CDN público y estable, confirmado
                # contra datos reales. Sirve igual para la LIDOM (sus equipos
                # usan el mismo CDN, ej. https://www.mlbstatic.com/team-logos/672.svg).
                team.logo_url = f"https://www.mlbstatic.com/team-logos/{external_id}.svg"
                team.wins = wins
                team.losses = losses
                team.win_pct = round(wins / games_played, 3) if games_played else 0.0
                team.division = division_name
                team.is_placeholder = False
                team.standings_updated_at = datetime.now(timezone.utc)

        # Limpieza: cualquier equipo de esta liga en la BD que la API ya NO
        # devuelva se elimina (ej. los "equipos" American League/"National
        # League" del Juego de Estrellas de MLB — is_placeholder ya no alcanza
        # por sí solo si esos registros se crearon antes de que existiera esa
        # bandera — o equipos de otra liga invernal guardados por error).
        pruned_team_count = _prune_stale_teams(db, league, valid_external_ids)
        if pruned_team_count:
            logger.info(
                "Se eliminaron %d equipo(s) de '%s' que no son franquicias reales.",
                pruned_team_count,
                league.key,
            )

        db.commit()
        logger.info("Posiciones de '%s' sincronizadas correctamente.", league.key)
    finally:
        db.close()


def _extract_team_runs(schedule_game: dict, team_side: str) -> int | None:
    """
    Extrae el marcador real de un lado ("home" o "away") de un juego.

    Se prioriza linescore.teams.{side}.runs, confirmado como la fuente que
    sí se actualiza mientras el partido está EN VIVO. teams.{side}.score
    se usa como respaldo (es la fuente que ya se usaba antes; funciona bien
    para partidos finalizados, pero se quedaba en 0 durante partidos en vivo,
    que era la causa del bug reportado de "siempre 0-0").
    """
    linescore_sides = (schedule_game.get("linescore") or {}).get("teams") or {}
    side_runs = linescore_sides.get(team_side, {}).get("runs")
    if side_runs is not None:
        return side_runs
    return schedule_game.get("teams", {}).get(team_side, {}).get("score")


def season_schedule_window(reference_date: date) -> tuple[date, date]:
    """
    Rango de fechas de la temporada que cruza dos años (la LIDOM va de octubre
    a enero). De septiembre en adelante es la temporada que empieza ese mismo
    año; de enero a agosto, la que empezó el año anterior — así el rango se
    ajusta solo cada temporada, sin fechas escritas a mano.

    Ojo: de marzo a agosto ese rango cae en el pasado (la temporada ya
    terminó), y quien llama debe notarlo comparando con la fecha de
    referencia antes de pedir nada.
    """
    season_start_year = reference_date.year if reference_date.month >= 9 else reference_date.year - 1
    return date(season_start_year, 9, 1), date(season_start_year + 1, 2, 28)


def _dates_with_missing_decisions(db: Session, league: League) -> set[date]:
    """
    Fechas de los ultimos 7 dias con partidos finalizados a los que les falta el
    pitcher ganador en 'details'.

    Sirve para rellenarlos: un partido de hace dos dias ya salio de la ventana
    de sincronizacion (ayer/hoy/manana) y, si en su momento no se guardo la
    decision, se quedaria para siempre sin ganador ni perdedor. Los partidos sin
    decision oficial (empates, suspendidos) tambien caen aqui, pero el limite de
    7 dias evita pedirlos indefinidamente.
    """
    recent_finished_games = (
        db.query(Game)
        .filter(Game.league_id == league.id, Game.status == "final")
        .order_by(Game.start_time.desc())
        .limit(60)
        .all()
    )
    oldest_date = datetime.now(timezone.utc).date() - timedelta(days=7)
    return {
        finished_game.start_time.date()
        for finished_game in recent_finished_games
        if not (finished_game.details or {}).get("winning_pitcher")
        and finished_game.start_time.date() >= oldest_date
    }


async def sync_league_games(
    league_key: str, api_config: StatsApiLeagueConfig, target_date: date | None = None
) -> None:
    """
    Sincroniza el calendario de una liga, reintentando una vez si otro proceso
    se le adelantó.

    El cron y el sincronizador del sitio comparten base de datos, así que
    pueden intentar insertar el mismo partido nuevo al mismo tiempo. El que
    pierde la carrera recibe IntegrityError al confirmar; en el reintento ese
    partido ya existe y solo se actualiza, en vez de tumbar la corrida entera.
    """
    try:
        await _sync_league_games_once(league_key, api_config, target_date)
    except IntegrityError:
        logger.warning(
            "El calendario de '%s' chocó con otra sincronización en curso; se reintenta una vez.",
            league_key,
        )
        await _sync_league_games_once(league_key, api_config, target_date)


async def _sync_league_games_once(
    league_key: str, api_config: StatsApiLeagueConfig, target_date: date | None = None
) -> None:
    db = SessionLocal()
    try:
        league = db.query(League).filter(League.key == league_key).first()
        if not league:
            return
        if not league.sync_enabled:
            logger.info("Liga '%s' desactivada desde el panel de admin; se omite su sincronización.", league.key)
            return

        reference_date = target_date or datetime.now(timezone.utc).date()
        # Se sincroniza "ayer" y "hoy" (no solo hoy): un juego que empieza
        # tarde en hora local puede caer en el día siguiente en UTC, y sin
        # esto ese juego nunca se guardaba en la base de datos.
        # También se incluye "mañana": sin esto, partidos próximos (para
        # predecir, o eventos especiales) no aparecían hasta el mismo día.
        dates_to_sync = {reference_date - timedelta(days=1), reference_date, reference_date + timedelta(days=1)}

        # Auto-corrección: cualquier juego que sigue marcado "live" en la BD
        # pero es de una fecha que ya no cae en la ventana de arriba nunca se
        # vuelve a tocar, y se queda "en vivo" para siempre aunque ya haya
        # terminado hace días. Se agregan esas fechas para forzar su corrección.
        orphaned_live_game_dates = {
            live_game.start_time.date()
            for live_game in db.query(Game).filter(Game.league_id == league.id, Game.status == "live").all()
        }
        dates_to_sync |= orphaned_live_game_dates

        # Auto-corrección: partidos finalizados recientes que quedaron sin
        # ganador guardado (pasó mientras el detalle JSON no se persistía al
        # actualizar un juego que ya existía). Se vuelven a pedir sus fechas.
        dates_to_sync |= _dates_with_missing_decisions(db, league)

        for sync_date in sorted(dates_to_sync):
            daily_schedule = await mlb_service.get_schedule(sync_date, api_config)
            _upsert_games_from_schedule(db, league, daily_schedule)

        if api_config.sync_full_season_schedule:
            season_start_date, season_end_date = season_schedule_window(reference_date)
            # De marzo a agosto (temporada muerta en la LIDOM) el rango cae en
            # el pasado y no hay nada nuevo que traer.
            if season_start_date <= reference_date <= season_end_date:
                # La temporada completa se pide solo si el calendario guardado
                # se está quedando sin partidos futuros: con la temporada ya
                # cargada hay decenas de juegos por delante, así que esto corre
                # una vez por temporada (y otra vez al final, para recoger la
                # postemporada) en vez de descargar la misma lista en cada ciclo.
                near_window_end = datetime.combine(
                    reference_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
                )
                upcoming_game_count = (
                    db.query(Game)
                    .filter(Game.league_id == league.id, Game.start_time > near_window_end)
                    .count()
                )
                if upcoming_game_count < FULL_SCHEDULE_MIN_UPCOMING_GAMES:
                    full_season_schedule = await mlb_service.get_schedule_range(
                        season_start_date, season_end_date, api_config
                    )
                    _upsert_games_from_schedule(db, league, full_season_schedule)
                    logger.info(
                        "Calendario completo de '%s' sincronizado (%s a %s).",
                        league.key,
                        season_start_date.isoformat(),
                        season_end_date.isoformat(),
                    )

        db.commit()
        logger.info("Calendario de '%s' sincronizado (%d fecha(s)).", league.key, len(dates_to_sync))
    finally:
        db.close()


def _upsert_games_from_schedule(db, league, daily_schedule: dict) -> None:
    """Procesa un calendario (un solo día) de la MLB Stats API y actualiza/crea los juegos en BD."""
    for schedule_day in daily_schedule.get("dates", []):
        for schedule_game in schedule_day.get("games", []):
            external_game_id = str(schedule_game["gamePk"])
            home_team_info = schedule_game["teams"]["home"]["team"]
            away_team_info = schedule_game["teams"]["away"]["team"]

            home_team = (
                db.query(Team)
                .filter(Team.league_id == league.id, Team.external_id == str(home_team_info["id"]))
                .first()
            )
            away_team = (
                db.query(Team)
                .filter(Team.league_id == league.id, Team.external_id == str(away_team_info["id"]))
                .first()
            )
            # Si alguno de los dos "equipos" no existe ya como franquicia real
            # sincronizada (ej. "American League"/"National League" del Juego
            # de Estrellas, o el Futures Game), el partido se omite por
            # completo: no es temporada regular entre los 30 equipos reales y
            # no debe aparecer en la página (pedido explícito). Antes se
            # creaba un equipo "placeholder" para no perder el partido, pero
            # eso es justo lo que hacía que el Juego de Estrellas apareciera
            # en la página. Los 30 equipos reales siempre existen ya gracias
            # a sync_league_teams_and_standings, que corre antes que esta función.
            if not home_team or not away_team:
                continue

            game = (
                db.query(Game)
                .filter(Game.league_id == league.id, Game.external_id == external_game_id)
                .first()
            )
            if not game:
                game = Game(
                    league_id=league.id,
                    external_id=external_game_id,
                    home_team_id=home_team.id,
                    away_team_id=away_team.id,
                    start_time=datetime.fromisoformat(schedule_game["gameDate"].replace("Z", "+00:00")),
                )
                db.add(game)
                # La sesión se crea con autoflush=False: sin este flush, un
                # juego recién agregado no se ve en las consultas siguientes, y
                # un mismo partido que llegue dos veces en la misma corrida
                # (ej. en la ventana cercana y en el calendario completo de la
                # temporada) se intentaría insertar dos veces y reventaría la
                # restricción única de (liga, id externo).
                db.flush()

            raw_status = schedule_game.get("status", {}).get("abstractGameState", "Preview")
            status_mapping = {"Preview": "scheduled", "Live": "live", "Final": "final"}
            game.status = status_mapping.get(raw_status, "scheduled")

            game.home_score = _extract_team_runs(schedule_game, "home")
            game.away_score = _extract_team_runs(schedule_game, "away")
            game.venue = schedule_game.get("venue", {}).get("name")

            if game.status == "scheduled" and game.home_win_probability is None:
                home_recent_form = _compute_recent_win_pct(db, home_team.id)
                away_recent_form = _compute_recent_win_pct(db, away_team.id)
                game.home_win_probability = estimate_home_win_probability(
                    home_team.win_pct or 0.5, away_team.win_pct or 0.5, home_recent_form, away_recent_form
                )

            game_details = dict(game.details or {})
            if game.status == "scheduled":
                game_details.update(mlb_service.extract_probable_pitchers(schedule_game))
            elif game.status == "final":
                game_details.update(mlb_service.extract_decisions(schedule_game))
                linescore_data = schedule_game.get("linescore", {})
                game_details["innings_played"] = linescore_data.get("currentInning")
            elif game.status == "live":
                linescore_data = schedule_game.get("linescore", {})
                game.period_status = f"Inning {linescore_data.get('currentInning', '?')}"
            game.details = game_details
            # SQLAlchemy no detecta cambios hechos DENTRO de una columna JSON
            # (mutarla en sitio no la marca como modificada). Sin este aviso, el
            # UPDATE no incluye 'details' y un partido que pasa de programado a
            # finalizado se quedaba con los pitchers probables para siempre, sin
            # ganador ni perdedor.
            flag_modified(game, "details")
            game.last_synced_at = datetime.now(timezone.utc)


def _compute_recent_win_pct(db: Session, team_id: int, game_count: int = 10) -> float | None:
    """
    % de victorias del equipo en sus últimos `game_count` partidos ya
    jugados (los más recientes primero). Un empate cuenta como partido
    jugado sin sumar victoria (así se ignoran en fútbol en vez de tratarlos
    como derrota).

    Devuelve None si el equipo todavía no tiene partidos jugados — para no
    inventar una "racha" a partir de cero datos; quien llama a esto debe
    entonces usar solo el récord de temporada.
    """
    finished_games = (
        db.query(Game)
        .filter(
            (Game.home_team_id == team_id) | (Game.away_team_id == team_id),
            Game.status == "final",
        )
        .order_by(Game.start_time.desc())
        .limit(game_count)
        .all()
    )

    win_count = 0
    decided_games = 0
    for finished_game in finished_games:
        if finished_game.home_score is None or finished_game.away_score is None:
            continue
        is_home_game = finished_game.home_team_id == team_id
        side_runs = finished_game.home_score if is_home_game else finished_game.away_score
        opponent_runs = finished_game.away_score if is_home_game else finished_game.home_score
        decided_games += 1
        if side_runs > opponent_runs:
            win_count += 1

    return win_count / decided_games if decided_games else None


def delete_players_cascade(db: Session, stale_player_ids: list[int]) -> int:
    """
    Borra los jugadores indicados junto con los favoritos que apunten a
    ellos (para no violar la llave foránea). Se usa en la limpieza de
    rosters (jugadores que ya no están en el roster activo) y se puede
    reutilizar donde haga falta borrar jugadores.
    """
    if not stale_player_ids:
        return 0
    db.query(Favorite).filter(Favorite.player_id.in_(stale_player_ids)).delete(synchronize_session=False)
    return db.query(Player).filter(Player.id.in_(stale_player_ids)).delete(synchronize_session=False)


def delete_teams_cascade(db: Session, stale_team_ids: list[int]) -> int:
    """
    Borra los equipos indicados junto con todo lo que depende de ellos, en
    el orden correcto para no violar llaves foráneas: favoritos directos,
    jugadores (y sus favoritos), partidos (uno por uno, para que dispare
    el cascade Game -> Prediction ya definido en el modelo), y por último
    los equipos. Devuelve cuántos equipos se eliminaron.

    Se usa tanto en la limpieza automática de sincronización como en el
    panel de administración para borrar equipos incorrectos a mano.
    """
    if not stale_team_ids:
        return 0

    # Favoritos que apuntan directo a alguno de estos equipos.
    db.query(Favorite).filter(Favorite.team_id.in_(stale_team_ids)).delete(synchronize_session=False)

    # Jugadores de estos equipos (y los favoritos que apunten a esos jugadores).
    roster_player_ids = [player_row.id for player_row in db.query(Player).filter(Player.team_id.in_(stale_team_ids)).all()]
    if roster_player_ids:
        db.query(Favorite).filter(Favorite.player_id.in_(roster_player_ids)).delete(synchronize_session=False)
        db.query(Player).filter(Player.id.in_(roster_player_ids)).delete(synchronize_session=False)

    # Partidos de estos equipos: se borran uno por uno (no en bloque) para
    # que SQLAlchemy dispare el cascade Game -> Prediction ya definido en el
    # modelo (un borrado en bloque no dispara cascades del ORM).
    affected_games = (
        db.query(Game)
        .filter((Game.home_team_id.in_(stale_team_ids)) | (Game.away_team_id.in_(stale_team_ids)))
        .all()
    )
    for affected_game in affected_games:
        db.delete(affected_game)
    db.flush()

    deleted_team_count = db.query(Team).filter(Team.id.in_(stale_team_ids)).delete(synchronize_session=False)
    return deleted_team_count


def _prune_stale_teams(db: Session, league: League, valid_external_ids: set[str]) -> int:
    """
    Elimina de la BD equipos de esta liga que la API ya NO devuelve (ej.
    quedaron guardados por una versión anterior del código que traía datos
    equivocados). Devuelve cuántos equipos se eliminaron.

    Medida de seguridad: si la API no devolvió ningún equipo válido (ej. un
    fallo temporal), no se borra nada — así un error pasajero de la API
    nunca puede vaciar la tabla completa por error.
    """
    if not valid_external_ids:
        return 0

    orphaned_team_ids = [
        team_row.id
        for team_row in db.query(Team)
        .filter(Team.league_id == league.id, Team.external_id.notin_(valid_external_ids))
        .all()
    ]
    return delete_teams_cascade(db, orphaned_team_ids)


async def sync_league_rosters(league_key: str) -> None:
    """
    Sincroniza los jugadores (roster) de cada equipo de una liga. Es lo que
    permite que el buscador de estadísticas encuentre jugadores reales por
    nombre, no solo por ID.
    """
    db = SessionLocal()
    try:
        league = db.query(League).filter(League.key == league_key).first()
        if not league:
            return
        if not league.sync_enabled:
            logger.info("Liga '%s' desactivada desde el panel de admin; se omite su sincronización.", league.key)
            return

        teams = db.query(Team).filter(Team.league_id == league.id).all()
        for team in teams:
            try:
                roster_response = await mlb_service.get_team_roster(int(team.external_id), CURRENT_SEASON)
            except Exception:
                logger.exception("No se pudo obtener el roster del equipo '%s'.", team.name)
                continue

            for roster_entry in roster_response.get("roster", []):
                person_payload = roster_entry.get("person", {})
                external_player_id = str(person_payload.get("id", ""))
                if not external_player_id:
                    continue

                player = (
                    db.query(Player)
                    .filter(Player.team_id == team.id, Player.external_id == external_player_id)
                    .first()
                )
                if not player:
                    player = Player(team_id=team.id, external_id=external_player_id, full_name=person_payload.get("fullName", ""))
                    db.add(player)

                player.full_name = person_payload.get("fullName") or player.full_name
                player.position = roster_entry.get("position", {}).get("abbreviation")
                player.jersey_number = roster_entry.get("jerseyNumber")

        db.commit()
        logger.info("Roster de '%s' sincronizado (%d equipos).", league.key, len(teams))
    finally:
        db.close()


def resolve_finished_predictions() -> None:
    """
    Recorre juegos finalizados con predicciones pendientes, determina si el
    usuario acertó y otorga puntos Strike según la probabilidad al momento de
    predecir. Se debe llamar después de sync_league_games.
    """
    db = SessionLocal()
    try:
        unresolved_predictions = (
            db.query(Prediction)
            .join(Game, Prediction.game_id == Game.id)
            .filter(Prediction.status == "pending", Game.status == "final")
            .all()
        )
        resolved_prediction_count = 0
        for prediction in unresolved_predictions:
            finished_game = prediction.game
            if finished_game.home_score is None or finished_game.away_score is None:
                continue

            winning_team_id = None
            if finished_game.home_score > finished_game.away_score:
                winning_team_id = finished_game.home_team_id
            elif finished_game.away_score > finished_game.home_score:
                winning_team_id = finished_game.away_team_id

            predictor = db.get(User, prediction.user_id)
            if prediction.predicted_team_id == winning_team_id:
                award_points = points_for_prediction(prediction.probability_at_pick)
                prediction.status = "correct"
                prediction.points_awarded = award_points
                predictor.bfb_points += award_points
            else:
                penalty_points = points_lost_for_prediction(prediction.probability_at_pick)
                prediction.status = "incorrect"
                prediction.points_awarded = -penalty_points
                predictor.bfb_points = max(0, predictor.bfb_points - penalty_points)

            prediction.resolved_at = datetime.now(timezone.utc)
            prediction.seen = False  # hay un resultado nuevo: el frontend debe avisarle al usuario
            resolved_prediction_count += 1

        db.commit()
        logger.info("Predicciones resueltas: %d", resolved_prediction_count)
    finally:
        db.close()


def _upsert_news_articles(
    db: Session,
    feed_articles: list[dict],
    *,
    sport_id: int,
    league_id: int | None = None,
    translate: bool = True,
) -> None:
    """
    Inserta/actualiza artículos de noticias ya descargados.

    translate=False para fuentes que ya vienen en español (ej. la prensa
    dominicana que cubre la LIDOM): ahí el texto original es el que se
    muestra en español y no hay nada que traducir.
    """
    for feed_article in feed_articles:
        if not feed_article["article_url"]:
            continue

        existing = (
            db.query(NewsArticle).filter(NewsArticle.article_url == feed_article["article_url"]).first()
        )
        if existing:
            # Se actualiza la imagen y el resumen aunque el artículo ya
            # exista: si el artículo se guardó antes de una mejora en
            # la extracción de imagen, esto permite que se "autocorrija"
            # en el siguiente ciclo en vez de quedarse sin imagen para siempre.
            existing.image_url = feed_article["image_url"] or existing.image_url
            if feed_article["summary"] and feed_article["summary"] != existing.summary:
                existing.summary = feed_article["summary"]
                existing.summary_es = None  # el resumen cambió: se re-traduce abajo

            # Solo se traduce si todavía no hay traducción (evita
            # volver a traducir lo mismo cada 5 minutos sin necesidad).
            if translate:
                if not existing.title_es:
                    existing.title_es = translation_service.translate_to_spanish(existing.title)
                if not existing.summary_es and existing.summary:
                    existing.summary_es = translation_service.translate_to_spanish(existing.summary)
            continue

        db.add(
            NewsArticle(
                sport_id=sport_id,
                league_id=league_id,
                title=feed_article["title"],
                title_es=translation_service.translate_to_spanish(feed_article["title"]) if translate else None,
                summary=feed_article["summary"],
                summary_es=translation_service.translate_to_spanish(feed_article["summary"]) if translate else None,
                image_url=feed_article["image_url"],
                source=feed_article["source"],
                article_url=feed_article["article_url"],
                published_at=feed_article["published_at"],
            )
        )


async def sync_news() -> None:
    db = SessionLocal()
    try:
        sports = db.query(Sport).all()
        for sport in sports:
            try:
                fetched_articles = await news_service.fetch_general_news(sport.key, limit=15)
            except Exception:
                logger.exception("No se pudieron obtener noticias de '%s'.", sport.key)
                continue

            _upsert_news_articles(db, fetched_articles, sport_id=sport.id)
            db.commit()

        # Noticias propias de una liga (ej. la LIDOM, cubierta por prensa
        # dominicana). Se guardan con league_id para no mezclarlas con las
        # noticias generales del deporte; ya vienen en español, así que no se
        # traducen.
        for league_key in news_service.FEEDS_BY_LEAGUE:
            league = db.query(League).filter(League.key == league_key).first()
            if not league:
                continue

            league_teams = db.query(Team).filter(Team.league_id == league.id).all()
            team_name_hints = [team.short_name or team.name for team in league_teams]
            try:
                fetched_articles = await news_service.fetch_league_news(
                    league_key, team_name_hints, limit=15
                )
            except Exception:
                logger.exception("No se pudieron obtener noticias de la liga '%s'.", league_key)
                continue

            _upsert_news_articles(
                db,
                fetched_articles,
                sport_id=league.sport_id,
                league_id=league.id,
                translate=False,
            )
            db.commit()

        logger.info(
            "Noticias sincronizadas para %d deporte(s) y %d liga(s).",
            len(sports),
            len(news_service.FEEDS_BY_LEAGUE),
        )
    finally:
        db.close()


async def run_full_sync() -> None:
    """
    Punto de entrada único: refresca cada liga soportada (equipos, partidos,
    rosters) + noticias y resuelve predicciones.

    El orden importa: primero los equipos/posiciones (crean las franquicias),
    luego los partidos (los referencian) y por último los rosters.
    """
    db = SessionLocal()
    try:
        ensure_base_catalog(db)
    finally:
        db.close()

    for league_key, api_config in LEAGUE_API_CONFIGS.items():
        await sync_league_teams_and_standings(league_key, api_config)
    for league_key, api_config in LEAGUE_API_CONFIGS.items():
        await sync_league_games(league_key, api_config)
    for league_key in LEAGUE_API_CONFIGS:
        await sync_league_rosters(league_key)

    await sync_news()
    resolve_finished_predictions()


def _prepare_database() -> None:
    """
    Deja el esquema listo para sincronizar aunque la base esté vacía.

    El servidor web crea las tablas al arrancar, pero el cron corre en su
    propio proceso: con una base recién creada (ej. el Postgres gratuito de
    Render expira a los 30 días y se reemplaza) antes fallaba con
    "no such table: sports" y no sincronizaba nada. Crear tablas es
    idempotente, así que no molesta cuando la base ya está lista.
    """
    Base.metadata.create_all(bind=engine)

    # Los parches de columnas usan sintaxis de Postgres (ADD COLUMN IF NOT
    # EXISTS). En una base nueva create_all ya trae el esquema completo, así
    # que solo se aplican cuando el motor los soporta.
    if engine.dialect.name == "postgresql":
        run_lightweight_migrations(engine)


def main() -> int:
    """
    Punto de entrada del cron: sincroniza una sola vez y devuelve el código de
    salida (0 = bien, 1 = falló). Render/la plataforma usa ese código para
    marcar la corrida como exitosa o fallida.

    Se registra el error de forma concisa en vez de dejar que Python imprima
    todo el traceback: el cron no debe llenar los logs de ruido.
    """
    configure_logging()
    try:
        _prepare_database()
        asyncio.run(run_full_sync())
    except Exception:
        logger.exception("La sincronización completa falló.")
        return 1
    logger.info("Sincronización completa terminada sin errores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
