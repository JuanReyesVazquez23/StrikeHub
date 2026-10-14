"""
Obtención de noticias deportivas reales vía RSS de ESPN.

Términos de uso de ESPN RSS (obligatorio cumplir):
- Solo se muestra el contenido tal cual viene en el feed (título + resumen),
  sin modificarlo.
- Siempre se debe enlazar al artículo completo en espn.com.
- Siempre se debe indicar que el contenido proviene de ESPN.
- No se debe incluir publicidad dentro del contenido del feed.

Esta función NO reproduce el artículo completo, solo el resumen que ESPN
distribuye en su propio feed público para ese fin.
"""
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.core.config import settings

from app.services.http_client import DEFAULT_HTTP_TIMEOUT as HTTP_TIMEOUT

FEEDS_BY_SPORT = {
    "baseball": settings.NEWS_RSS_MLB,
}

# Busca el primer <img src="..."> dentro de HTML (algunos feeds de ESPN
# incrustan la imagen directamente en el resumen en vez de usar una etiqueta
# de imagen aparte).
_INLINE_IMAGE_PATTERN = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def _extract_article_image(feed_entry: dict) -> str | None:
    """
    Busca la imagen real del artículo, probando las distintas formas en que
    un feed RSS puede exponerla, de la más específica a la más genérica:
    1) media:content / media:thumbnail (extensión Media RSS)
    2) <enclosure> (método clásico de RSS, común en varios feeds de ESPN)
    3) una etiqueta <img> incrustada dentro del HTML del resumen
    """
    if feed_entry.get("media_content"):
        return feed_entry["media_content"][0].get("url")
    if feed_entry.get("media_thumbnail"):
        return feed_entry["media_thumbnail"][0].get("url")

    for enclosure in feed_entry.get("enclosures", []):
        if enclosure.get("type", "").startswith("image") or enclosure.get("href", "").lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp")
        ):
            return enclosure.get("href")

    for feed_link in feed_entry.get("links", []):
        if feed_link.get("type", "").startswith("image"):
            return feed_link.get("href")

    summary_markup = feed_entry.get("summary", "")
    image_match = _INLINE_IMAGE_PATTERN.search(summary_markup)
    if image_match:
        return image_match.group(1)

    return None


def _strip_html(html_content: str) -> str:
    """Deja solo texto legible, sin etiquetas HTML. Nunca se inserta HTML de terceros sin sanear."""
    text_only = re.sub(r"<[^>]+>", " ", html_content)
    return re.sub(r"\s+", " ", text_only).strip()


def _parse_published_date(feed_entry: dict) -> datetime:
    published = feed_entry.get("published")
    if published:
        try:
            return parsedate_to_datetime(published)
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc)


async def fetch_rss_news(feed_url: str, limit: int = 15) -> list[dict]:
    """Descarga y parsea un feed RSS, devolviendo una lista de artículos normalizados."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent": "BFBDeportes/1.0"}) as client:
        response = await client.get(feed_url)
        response.raise_for_status()
        response_body = response.content

    parsed_feed = feedparser.parse(response_body)
    normalized_articles = []
    for feed_entry in parsed_feed.entries[:limit]:
        normalized_articles.append(
            {
                "title": feed_entry.get("title", "").strip(),
                "summary": _strip_html(feed_entry.get("summary", "")).strip() or None,
                "image_url": _extract_article_image(feed_entry),
                "source": "ESPN",
                "article_url": feed_entry.get("link"),
                "published_at": _parse_published_date(feed_entry),
            }
        )
    return normalized_articles


async def fetch_general_baseball_news(limit: int = 10) -> list[dict]:
    return await fetch_rss_news(settings.NEWS_RSS_MLB, limit=limit)


async def fetch_general_news(sport_key: str, limit: int = 10) -> list[dict]:
    feed_url = FEEDS_BY_SPORT.get(sport_key, settings.NEWS_RSS_MLB)
    return await fetch_rss_news(feed_url, limit=limit)
