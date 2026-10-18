"""
Configuración central de StrikeHub.

Todas las variables sensibles (contraseñas, claves de API, secretos JWT)
se leen desde el entorno (.env) y NUNCA se escriben directamente en el código.
"""
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- General ---
    PROJECT_NAME: str = "StrikeHub"
    API_V1_PREFIX: str = "/api/v1"
    ENV: str = "development"  # development | production

    # --- Base de datos ---
    # Ejemplo: postgresql+psycopg2://usuario:password@localhost:5432/bfb_deportes
    DATABASE_URL: str = "postgresql+psycopg2://bfb_user:bfb_password@localhost:5432/bfb_deportes"

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_database_url(cls, database_url: str) -> str:
        """
        Algunas plataformas (Railway, Heroku) entregan la URL de Postgres con
        el prefijo antiguo 'postgres://', que SQLAlchemy 2.0 ya no acepta.
        Se normaliza automáticamente a 'postgresql://' para evitar un error
        de arranque difícil de diagnosticar.
        """
        if database_url.startswith("postgres://"):
            return database_url.replace("postgres://", "postgresql://", 1)
        return database_url

    # --- Seguridad / JWT ---
    # SECRET_KEY debe generarse único por instalación. Nunca usar el valor por defecto en producción.
    SECRET_KEY: str = "CAMBIA_ESTA_CLAVE_POR_UNA_ALEATORIA_Y_SECRETA"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 días
    COOKIE_NAME: str = "bfb_session"

    # --- CORS ---
    # Lista de orígenes permitidos. En producción NUNCA usar "*".
    CORS_ORIGINS: list[str] = [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    # --- APIs externas de datos deportivos ---
    # MLB Stats API es oficial, gratuita y no requiere API key.
    MLB_STATS_API_BASE: str = "https://statsapi.mlb.com/api/v1"

    # --- Noticias (RSS oficiales, gratuitos, con imagen) ---
    NEWS_RSS_GENERAL: str = "https://www.espn.com/espn/rss/news"
    NEWS_RSS_MLB: str = "https://www.espn.com/espn/rss/mlb/news"
    # La LIDOM no tiene feed propio en ESPN: se cubre desde prensa dominicana.
    # El feed es de "Deportes" (trae también otros deportes), así que al
    # sincronizar se filtra a las noticias que mencionan la liga o sus equipos
    # (ver LEAGUE_KEYWORDS en app/services/news_service.py).
    NEWS_RSS_LIDOM: str = "https://www.diariolibre.com/rss/deportes.xml"
    NEWS_SOURCE_LIDOM: str = "Diario Libre"
    # Frecuencia mínima (minutos) entre refrescos de noticias por sección, para no saturar la fuente.
    NEWS_REFRESH_MINUTES: int = 15

    # --- Sistema de puntos Strike (predicciones) ---
    BET_MIN_POINTS: int = 2
    BET_MAX_POINTS: int = 20
    NEW_USER_STARTING_POINTS: int = 100

    # --- Rate limiting básico (login/registro) ---
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 8
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300

    # --- Panel de administración (borrar equipos incorrectos manualmente) ---
    # Usernames (separados por coma, tal cual se registraron) con acceso al
    # panel de admin. Vacío por defecto = nadie tiene acceso. Se define por
    # variable de entorno para no dejar el usuario admin escrito en el código.
    ADMIN_USERNAMES: str = ""

    def is_admin_username(self, username: str) -> bool:
        configured_admins = {candidate.strip() for candidate in self.ADMIN_USERNAMES.split(",") if candidate.strip()}
        return username in configured_admins

    @model_validator(mode="after")
    def _fail_fast_insecure_production(self):
        """
        Fail-fast en producción: si la app arranca con la SECRET_KEY de
        ejemplo (pública en el repo) o con CORS permisivo, los JWT serían
        falsificables y la API quedaría abierta. Mejor no arrancar que
        arrancar inseguro.
        """
        if self.ENV == "production":
            if (
                not self.SECRET_KEY
                or self.SECRET_KEY.startswith("CAMBIA_ESTA_CLAVE")
                or len(self.SECRET_KEY) < 32
            ):
                raise ValueError("SECRET_KEY inválida en producción: define una clave aleatoria de 32+ caracteres.")
            for allowed_origin in self.CORS_ORIGINS:
                if allowed_origin.strip() in ("*", "null"):
                    raise ValueError("CORS_ORIGINS no puede ser '*' en producción cuando se usan cookies.")
                if "localhost" in allowed_origin or "127.0.0.1" in allowed_origin:
                    raise ValueError(f"CORS_ORIGINS contiene origen local en producción: {allowed_origin}")
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Cachea la instancia de configuración para no releer el .env en cada request."""
    return Settings()


settings = get_settings()
