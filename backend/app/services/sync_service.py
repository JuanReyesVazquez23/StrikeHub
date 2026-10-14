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

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.favorite import Favorite
from app.models.prediction import Prediction
from app.models.sport import ExcludedTeam, Game, League, NewsArticle, Player, Sport, Team
from app.models.user import User
from app.services import (
    mlb_service,
    news_service,
    translation_service,
)
from app.services.probability_service import (
    estimate_home_win_probability,
    points_for_prediction,
    points_lost_for_prediction,
)

logger = logging.getLogger("bfb.sync")

CURRENT_MLB_SEASON = datetime.now(timezone.utc).year


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
    """Crea el deporte (solo béisbol) y la liga MLB si todavía no existen (idempotente)."""
    baseball = _get_or_create_sport(db, "baseball", "Béisbol", "Baseball")

    _get_or_create_league(db, baseball, "mlb", "MLB", provider="mlb_stats_api", is_primary=True)


async def sync_mlb_teams_and_standings() -> None:
    db = SessionLocal()
    try:
        league = db.query(League).filter(League.key == "mlb").first()
        if not league:
            logger.warning("Liga MLB no existe todavía en la BD; ejecuta ensure_base_catalog primero.")
            return
        if not league.sync_enabled:
            logger.info("Liga '%s' desactivada desde el panel de admin; se omite su sincronización.", league.key)
            return

        standings_response = await mlb_service.get_standings(CURRENT_MLB_SEASON)

        # El endpoint de standings solo trae "name" (nombre completo, ej.
        # "New York Yankees"). Para el nombre corto ("Yankees"), la
        # abreviación ("NYY") y la ciudad, se necesita el endpoint /teams.
        teams_response = await mlb_service.get_teams(CURRENT_MLB_SEASON)
        team_details_by_external_id = {str(team_payload["id"]): team_payload for team_payload in teams_response.get("teams", [])}

        valid_external_ids: set[str] = set()
        excluded_ids = {
            e.external_id for e in db.query(ExcludedTeam).filter(ExcludedTeam.league_id == league.id).all()
        }
        for division_record in standings_response.get("records", []):
            division_id = division_record.get("division", {}).get("id")
            division_name = mlb_service.MLB_DIVISION_NAMES.get(division_id)

            for team_standing in division_record.get("teamRecords", []):
                standing_team_info = team_standing["team"]
                external_id = str(standing_team_info["id"])
                if external_id in excluded_ids:
                    continue  # borrado a mano por el panel de admin; nunca se recrea
                valid_external_ids.add(external_id)
                team_details = team_details_by_external_id.get(external_id, {})

                team = (
                    db.query(Team)
                    .filter(Team.league_id == league.id, Team.external_id == external_id)
                    .first()
                )
                if not team:
                    team = Team(league_id=league.id, external_id=external_id, name=standing_team_info["name"])
                    db.add(team)

                wins = team_standing.get("wins", 0)
                losses = team_standing.get("losses", 0)
                games_played = wins + losses
                team.name = standing_team_info["name"]
                team.short_name = team_details.get("teamName")  # ej. "Yankees"
                team.abbreviation = team_details.get("abbreviation")  # ej. "NYY"
                team.city = team_details.get("locationName")  # ej. "New York"
                # Logo oficial de MLB: patrón de CDN público y estable, confirmado
                # contra datos reales usados por la propia comunidad de MLB.
                team.logo_url = f"https://www.mlbstatic.com/team-logos/{external_id}.svg"
                team.wins = wins
                team.losses = losses
                team.win_pct = round(wins / games_played, 3) if games_played else 0.0
                team.division = division_name
                team.is_placeholder = False
                team.standings_updated_at = datetime.now(timezone.utc)

        # Limpieza: cualquier equipo de MLB en la BD que NO sea una de las 30
        # franquicias reales de esta tabla de posiciones se elimina (ej. los
        # "equipos" American League / National League del Juego de Estrellas
        # que hayan quedado guardados de una sincronización anterior a este
        # arreglo — is_placeholder ya no alcanza por sí solo si esos registros
        # se crearon antes de que existiera esa bandera).
        pruned_team_count = _prune_stale_teams(db, league, valid_external_ids)
        if pruned_team_count:
            logger.info(
                "Se eliminaron %d equipo(s) de 'mlb' que no son franquicias reales (ej. Juego de Estrellas).",
                pruned_team_count,
            )

        db.commit()
        logger.info("Posiciones de MLB sincronizadas correctamente.")
    finally:
        db.close()


def _extract_team_runs(schedule_game: dict, team_side: str) -> int | None:
    """
    Extrae el marcador real de un lado ("home" o "away") de un juego de MLB.

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


async def sync_mlb_games(target_date: date | None = None) -> None:
    db = SessionLocal()
    try:
        league = db.query(League).filter(League.key == "mlb").first()
        if not league:
            return
        if not league.sync_enabled:
            logger.info("Liga '%s' desactivada desde el panel de admin; se omite su sincronización.", league.key)
            return

        reference_date = target_date or datetime.now(timezone.utc).date()
        # Se sincroniza "ayer" y "hoy" (no solo hoy): un juego de la Costa Oeste
        # que empieza tarde en hora local puede caer en el día siguiente en UTC,
        # y sin esto ese juego nunca se guardaba en la base de datos.
        # También se incluye "mañana": sin esto, partidos próximos (para
        # predecir, o eventos especiales como el Juego de Estrellas) no
        # aparecían hasta el mismo día.
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

        for sync_date in sorted(dates_to_sync):
            daily_schedule = await mlb_service.get_schedule(sync_date)
            _upsert_games_from_schedule(db, league, daily_schedule)

        db.commit()
        logger.info("Calendario de MLB sincronizado (%d fecha(s)).", len(dates_to_sync))
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
            # a sync_mlb_teams_and_standings, que corre antes que esta función.
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

            game_details = game.details or {}
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


async def sync_mlb_rosters() -> None:
    """
    Sincroniza los jugadores (roster) de cada equipo de MLB. Es lo que
    permite que el buscador de estadísticas encuentre jugadores reales por
    nombre, no solo por ID.
    """
    db = SessionLocal()
    try:
        league = db.query(League).filter(League.key == "mlb").first()
        if not league:
            return
        if not league.sync_enabled:
            logger.info("Liga '%s' desactivada desde el panel de admin; se omite su sincronización.", league.key)
            return

        teams = db.query(Team).filter(Team.league_id == league.id).all()
        for team in teams:
            try:
                roster_response = await mlb_service.get_team_roster(int(team.external_id), CURRENT_MLB_SEASON)
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
        logger.info("Roster de MLB sincronizado (%d equipos).", len(teams))
    finally:
        db.close()


def resolve_finished_predictions() -> None:
    """
    Recorre juegos finalizados con predicciones pendientes, determina si el
    usuario acertó y otorga puntos Strike según la probabilidad al momento de
    predecir. Se debe llamar después de sync_mlb_games.
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

            for feed_article in fetched_articles:
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
                    if not existing.title_es:
                        existing.title_es = translation_service.translate_to_spanish(existing.title)
                    if not existing.summary_es and existing.summary:
                        existing.summary_es = translation_service.translate_to_spanish(existing.summary)
                    continue

                db.add(
                    NewsArticle(
                        sport_id=sport.id,
                        title=feed_article["title"],
                        title_es=translation_service.translate_to_spanish(feed_article["title"]),
                        summary=feed_article["summary"],
                        summary_es=translation_service.translate_to_spanish(feed_article["summary"]),
                        image_url=feed_article["image_url"],
                        source=feed_article["source"],
                        article_url=feed_article["article_url"],
                        published_at=feed_article["published_at"],
                    )
                )
            db.commit()
        logger.info("Noticias sincronizadas para %d deporte(s).", len(sports))
    finally:
        db.close()


async def run_full_sync() -> None:
    """Punto de entrada único: refresca MLB (equipos, partidos, rosters) + noticias y resuelve predicciones."""
    db = SessionLocal()
    try:
        ensure_base_catalog(db)
    finally:
        db.close()

    await sync_mlb_teams_and_standings()
    await sync_mlb_games()
    await sync_mlb_rosters()

    await sync_news()
    resolve_finished_predictions()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_full_sync())
