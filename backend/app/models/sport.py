from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Sport(Base):
    """Deporte de alto nivel: baseball, football (fútbol) o basketball."""

    __tablename__ = "sports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # baseball|football|basketball
    name_es: Mapped[str] = mapped_column(String(50), nullable=False)
    name_en: Mapped[str] = mapped_column(String(50), nullable=False)

    leagues = relationship("League", back_populates="sport")


class League(Base):
    """Una liga concreta dentro de un deporte (MLB, EPL, NBA, Mundial, etc.)."""

    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"), nullable=False)

    key: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)  # mlb|nba|epl|world_cup...
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str | None] = mapped_column(String(60), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Liga "estrella" que se muestra por defecto al entrar al deporte (MLB, NBA, etc.)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    # Fuente de datos usada para esta liga: "mlb_stats_api".
    data_provider: Mapped[str] = mapped_column(String(30), nullable=False)

    # False = el panel de administración "borró" esta liga (ej. un evento ya
    # pasado, como un Mundial anterior). Mientras esté en False, ninguna
    # sincronización periódica la vuelve a tocar — se puede reactivar desde
    # el mismo panel cuando haga falta de nuevo (ej. el próximo Mundial).
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sport = relationship("Sport", back_populates="leagues")
    teams = relationship("Team", back_populates="league")
    games = relationship("Game", back_populates="league")


class Team(Base):
    """Franquicia real de una liga (ej. Yankees en MLB). Los placeholders del All-Star se excluyen en consultas."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(50), nullable=False)  # id en la API externa
    # True solo para equipos auto-creados que no son franquicias reales
    # (ej. "American League"/"National League" del Juego de Estrellas MLB).
    # Se excluyen de posiciones y de la búsqueda de estadísticas.
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Nombre corto/mascota (ej. "Yankees", sin la ciudad). Se usa para detectar
    # menciones del equipo en titulares de noticias y para mostrarlo compacto en la UI.
    short_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    abbreviation: Mapped[str | None] = mapped_column(String(10), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    ties: Mapped[int] = mapped_column(Integer, default=0)
    win_pct: Mapped[float] = mapped_column(Float, default=0.0)
    division: Mapped[str | None] = mapped_column(String(60), nullable=True)
    conference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    standings_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("league_id", "external_id", name="uq_team_league_external"),)

    league = relationship("League", back_populates="teams")
    players = relationship("Player", back_populates="team")


class Player(Base):
    """Jugador del roster activo de un equipo (sincronizado desde la API externa)."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(50), nullable=False)

    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    position: Mapped[str | None] = mapped_column(String(30), nullable=True)
    jersey_number: Mapped[str | None] = mapped_column(String(5), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (UniqueConstraint("team_id", "external_id", name="uq_player_team_external"),)

    team = relationship("Team", back_populates="players")


class Game(Base):
    """Partido entre dos franquicias reales: scheduled | live | final | postponed."""

    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(50), nullable=False)

    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # scheduled | live | final | postponed
    status: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)

    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Probabilidad (0-1) de que gane el equipo local, calculada antes del inicio del juego.
    home_win_probability: Mapped[float | None] = mapped_column(Float, nullable=True)

    venue: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Estado del juego en curso (ej. inning, cuarto, minuto) en texto libre para mostrar en UI.
    period_status: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Detalles específicos del deporte: pitchers, boxscore, goleadores, etc.
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("league_id", "external_id", name="uq_game_league_external"),)

    league = relationship("League", back_populates="games")
    home_team = relationship("Team", foreign_keys=[home_team_id])
    away_team = relationship("Team", foreign_keys=[away_team_id])
    predictions = relationship("Prediction", back_populates="game", cascade="all, delete-orphan")


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # sport_id es NULL para noticias generales (de todo el deporte, no de una liga concreta)
    sport_id: Mapped[int | None] = mapped_column(ForeignKey("sports.id"), nullable=True)
    league_id: Mapped[int | None] = mapped_column(ForeignKey("leagues.id"), nullable=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Traducción automática al español (ver app/services/translation_service.py).
    # Se guarda aparte del original en inglés; nunca lo sobreescribe. Si la
    # traducción todavía no está lista o falló, queda en NULL y el
    # endpoint usa el original en inglés como respaldo.
    title_es: Mapped[str | None] = mapped_column(String(300), nullable=True)
    summary_es: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    article_url: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ExcludedTeam(Base):
    """
    Equipos que un admin borró a mano desde el panel de administración.

    Por qué existe: borrar un equipo con el panel de admin no bastaba,
    porque la siguiente sincronización lo volvía a crear si la API externa
    todavía lo reportaba. Esta tabla es la lista negra
    definitiva: toda sincronización de equipos revisa aquí primero y se
    salta cualquier external_id que aparezca, sin importar qué diga la API
    sobre ese equipo. Es la única forma de que un borrado del panel de
    admin se quede borrado para siempre.
    """

    __tablename__ = "excluded_teams"
    __table_args__ = (UniqueConstraint("league_id", "external_id", name="uq_excluded_team_league_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(50), nullable=False)
    team_name: Mapped[str | None] = mapped_column(String(150), nullable=True)  # solo de referencia, no se usa en lógica
    excluded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
