"""
Detección de equipos mencionados en titulares de noticias, y cálculo de
"qué tan caliente" es una noticia según menciones reales — no es una API
de tendencias de terceros, es una métrica propia, explicable y verificable:
entre más noticias recientes hablen del mismo equipo, más "caliente" se
considera el tema.

Se usa para dos cosas:
1. Mostrar el logo del equipo junto a la noticia (si se detecta uno).
2. Ordenar "Noticias Generales" por relevancia real en vez de solo fecha,
   cuando el cliente pide sort=trending.
"""
import re
from collections import Counter

from app.models.sport import NewsArticle, Team

# Nombres muy cortos (ej. "Sox") se excluyen para evitar falsos positivos:
# "Red Sox" y "White Sox" ya vienen completos desde team.short_name, así que
# no hace falta (ni conviene) partirlos más.
MIN_TEAM_NAME_LENGTH = 4


def _searchable_team_names(team: Team) -> list[str]:
    """Nombres por los que un titular podría referirse a este equipo, del más específico al más genérico."""
    candidates = [team.short_name, team.name, team.abbreviation]
    return [candidate for candidate in candidates if candidate and len(candidate) >= MIN_TEAM_NAME_LENGTH]


def _contains_whole_word(article_text: str, team_name: str) -> bool:
    """Coincidencia de palabra completa, sin importar mayúsculas/minúsculas (evita que 'Cubs' matchee 'Cubside')."""
    pattern = r"\b" + re.escape(team_name) + r"\b"
    return re.search(pattern, article_text, flags=re.IGNORECASE) is not None


def match_team_for_article(headline: str, teams: list[Team]) -> Team | None:
    """Devuelve el primer equipo cuyo nombre aparece en el titular, o None si no se detecta ninguno."""
    for team in teams:
        for team_name in _searchable_team_names(team):
            if _contains_whole_word(headline, team_name):
                return team
    return None


def annotate_and_rank(
    articles: list[NewsArticle], teams: list[Team], sort: str, lang: str = "es"
) -> list[dict]:
    """
    Devuelve los artículos como dicts listos para NewsOut, con team_name/
    team_logo_url ya resueltos, y ordenados según 'sort':
    - "recent": más nuevas primero (comportamiento original, sin cambios).
    - "trending": las que comparten equipo/tema con más noticias del lote
      actual aparecen primero (empatando por fecha como criterio secundario).

    lang: si es "es", se devuelve title_es/summary_es cuando ya existan
    (traducidos en la sincronización); si la traducción todavía no está
    lista, se usa el original en inglés como respaldo.
    """
    team_by_article_id: dict[int, Team | None] = {
        article.id: match_team_for_article(article.title, teams) for article in articles
    }

    mention_count_by_team_id = Counter(team.id for team in team_by_article_id.values() if team is not None)

    def trending_score(article: NewsArticle) -> int:
        matched_team = team_by_article_id[article.id]
        return mention_count_by_team_id[matched_team.id] if matched_team else 0

    ranked_articles = list(articles)
    if sort == "trending":
        ranked_articles.sort(key=lambda article: (trending_score(article), article.published_at), reverse=True)
    # "recent" no reordena: ya viene ordenado por published_at desde la consulta.

    ranked_payload = []
    for article in ranked_articles:
        matched_team = team_by_article_id[article.id]
        title = (article.title_es if lang == "es" else None) or article.title
        summary = (article.summary_es if lang == "es" else None) or article.summary
        ranked_payload.append(
            {
                "id": article.id,
                "title": title,
                "summary": summary,
                "image_url": article.image_url,
                "source": article.source,
                "article_url": article.article_url,
                "published_at": article.published_at,
                "team_name": matched_team.short_name or matched_team.name if matched_team else None,
                "team_logo_url": matched_team.logo_url if matched_team else None,
            }
        )
    return ranked_payload
