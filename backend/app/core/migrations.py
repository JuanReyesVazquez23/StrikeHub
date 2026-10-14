"""
Migraciones ligeras para columnas nuevas en tablas que YA existen en la
base de datos (por ejemplo, en producción/Railway).

Por qué existe este archivo: Base.metadata.create_all() (usado en el
arranque de la app) solo crea tablas que todavía no existen — nunca
modifica una tabla que ya está creada. Si agregamos una columna nueva a un
modelo (ej. Team.short_name) y la base de datos ya tiene la tabla "teams"
creada de antes, create_all() la ignora y la app fallaría al intentar leer
o escribir esa columna inexistente.

Cada sentencia usa "ADD COLUMN IF NOT EXISTS", así que:
- Es segura de ejecutar en cada arranque (no falla si la columna ya existe).
- No borra ni modifica datos existentes.
- En una base de datos nueva (recién creada), create_all() ya incluye estas
  columnas desde el principio, así que aquí simplemente no habría nada que
  hacer (la sentencia es un no-op).

Nota: para un proyecto que crezca más, lo correcto a mediano plazo es migrar
a Alembic (ya lo señala el README como próximo paso). Esto es un puente
seguro mientras tanto, no un reemplazo definitivo de Alembic.
"""
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger("bfb.migrations")

# Cada entrada es una sentencia SQL idempotente. Se agregan aquí a futuro
# nuevas columnas que necesiten "parchear" tablas ya existentes.
_IDEMPOTENT_DDL_STATEMENTS = [
    "ALTER TABLE teams ADD COLUMN IF NOT EXISTS short_name VARCHAR(60)",
    "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS title_es VARCHAR(300)",
    "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS summary_es TEXT",
    "ALTER TABLE teams ADD COLUMN IF NOT EXISTS is_placeholder BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE players ADD COLUMN IF NOT EXISTS goals INTEGER",
    "ALTER TABLE players ADD COLUMN IF NOT EXISTS assists INTEGER",
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS seen BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE players ADD COLUMN IF NOT EXISTS nba_stats_person_id VARCHAR(20)",
    "ALTER TABLE teams ADD COLUMN IF NOT EXISTS roster_synced_at TIMESTAMPTZ",
    "ALTER TABLE leagues ADD COLUMN IF NOT EXISTS sync_enabled BOOLEAN NOT NULL DEFAULT true",
    # StrikeHub (solo MLB): columnas de fútbol/basket que ya no usa ningún
    # código. Se eliminan si existen; IF EXISTS lo hace seguro en BD nuevas.
    "ALTER TABLE players DROP COLUMN IF EXISTS goals",
    "ALTER TABLE players DROP COLUMN IF EXISTS assists",
    "ALTER TABLE players DROP COLUMN IF EXISTS nba_stats_person_id",
    "ALTER TABLE teams DROP COLUMN IF EXISTS roster_synced_at",
    "ALTER TABLE leagues DROP COLUMN IF EXISTS provider_league_path",
]


def run_lightweight_migrations(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        for ddl_statement in _IDEMPOTENT_DDL_STATEMENTS:
            connection.execute(text(ddl_statement))
    logger.info("Migraciones ligeras aplicadas correctamente (%d sentencias).", len(_IDEMPOTENT_DDL_STATEMENTS))
