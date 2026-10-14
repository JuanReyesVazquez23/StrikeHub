from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.sport import League, NewsArticle, Sport, Team
from app.schemas.sport import NewsOut
from app.services.news_ranking import annotate_and_rank

router = APIRouter(prefix="/news", tags=["news"])


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

    stored_articles = (
        db.query(NewsArticle)
        .filter(NewsArticle.sport_id == sport_row.id)
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
        .all()
    )

    # Equipos de todas las ligas de este deporte, para poder detectar
    # menciones en los titulares (ej. "Yankees" -> equipo de la MLB).
    league_teams = (
        db.query(Team)
        .join(League, Team.league_id == League.id)
        .filter(League.sport_id == sport_row.id)
        .all()
    )

    return annotate_and_rank(stored_articles, league_teams, sort=sort, lang=lang)
