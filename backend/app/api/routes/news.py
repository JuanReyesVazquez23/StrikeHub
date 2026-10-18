from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.sport import League, NewsArticle, Sport, Team
from app.schemas.sport import NewsOut
from app.services.news_ranking import annotate_and_rank

router = APIRouter(prefix="/news", tags=["news"])


def _load_sport_articles(db: Session, sport_id: int, limit: int) -> list[NewsArticle]:
    """Noticias generales del deporte: las que no están atadas a una liga."""
    return (
        db.query(NewsArticle)
        .filter(NewsArticle.sport_id == sport_id, NewsArticle.league_id.is_(None))
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
        .all()
    )


def _load_league_articles(db: Session, league_id: int, limit: int) -> list[NewsArticle]:
    """Noticias propias de una liga concreta (ej. la LIDOM)."""
    return (
        db.query(NewsArticle)
        .filter(NewsArticle.league_id == league_id)
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
        .all()
    )


def _sport_teams(db: Session, sport_id: int) -> list[Team]:
    # Equipos de todas las ligas de este deporte, para poder detectar
    # menciones en los titulares (ej. "Yankees" -> equipo de la MLB).
    return (
        db.query(Team)
        .join(League, Team.league_id == League.id)
        .filter(League.sport_id == sport_id)
        .all()
    )


def _league_teams(db: Session, league_id: int) -> list[Team]:
    return db.query(Team).filter(Team.league_id == league_id).all()


@router.get("/league/{league_key}", response_model=list[NewsOut])
def get_league_news(
    league_key: str = Path(pattern=r"^[a-z0-9_]{1,40}$"),
    limit: int = Query(default=15, ge=1, le=50),
    sort: str = Query(default="recent", pattern="^(recent|trending)$"),
    lang: str = Query(default="es", pattern="^(es|en)$"),
    db: Session = Depends(get_db),
):
    """
    Noticias de una liga concreta (ej. LIDOM, cubierta por prensa dominicana).
    Se guardan en BD por el proceso de sincronización periódica y se sirven
    desde ahí para no golpear el feed RSS en cada visita.

    Si esa liga todavía no tiene noticias propias, se cae a las noticias
    generales de su deporte para que la sección nunca quede vacía.

    sort: "recent" (más nuevas primero) o "trending" (por relevancia real,
    ver app/services/news_ranking.py). lang: "es" o "en".
    """
    league = db.query(League).filter(League.key == league_key).first()
    if not league:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liga no encontrada.")

    stored_articles = _load_league_articles(db, league.id, limit)
    if stored_articles:
        teams = _league_teams(db, league.id)
    else:
        stored_articles = _load_sport_articles(db, league.sport_id, limit)
        teams = _sport_teams(db, league.sport_id)

    return annotate_and_rank(stored_articles, teams, sort=sort, lang=lang)


@router.get("/{sport_key}", response_model=list[NewsOut])
def get_sport_news(
    sport_key: str = Path(pattern=r"^[a-z_]{1,30}$"),
    limit: int = Query(default=15, ge=1, le=50),
    sort: str = Query(default="recent", pattern="^(recent|trending)$"),
    lang: str = Query(default="es", pattern="^(es|en)$"),
    db: Session = Depends(get_db),
):
    """
    Noticias generales del deporte (ej. todo lo relacionado a béisbol,
    no solo de una liga). Se guardan en BD por el proceso de sincronización
    periódica y se sirven desde ahí para no golpear el feed RSS en cada visita.

    sort:
    - "recent" (default, comportamiento original): más nuevas primero.
    - "trending": las que mencionan un equipo del que hay más noticias
      recientes aparecen primero (ver app/services/news_ranking.py).

    lang: "es" (default) devuelve el título/resumen traducido si ya está
    disponible; si la traducción todavía no se hizo, se usa el original en
    inglés como respaldo (nunca se deja al usuario sin contenido).
    """
    sport_row = db.query(Sport).filter(Sport.key == sport_key).first()
    if not sport_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deporte no encontrado.")

    stored_articles = _load_sport_articles(db, sport_row.id, limit)
    league_teams = _sport_teams(db, sport_row.id)

    return annotate_and_rank(stored_articles, league_teams, sort=sort, lang=lang)
