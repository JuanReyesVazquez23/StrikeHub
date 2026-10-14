"""
Configuración de SQLAlchemy para PostgreSQL.

Usar siempre el ORM (sesiones, queries con parámetros) y NUNCA construir
SQL concatenando strings, para evitar inyección SQL.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # evita conexiones muertas tras inactividad
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db():
    """Dependencia de FastAPI: entrega una sesión de BD y garantiza su cierre."""
    database_session = SessionLocal()
    try:
        yield database_session
    finally:
        database_session.close()
