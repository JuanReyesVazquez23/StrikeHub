"""
Obtención de noticias deportivas reales vía feeds RSS públicos.

Términos de uso de ESPN RSS (obligatorio cumplir):
- Solo se muestra el contenido tal cual viene en el feed (título + resumen),
  sin modificarlo.
- Siempre se debe enlazar al artículo completo en espn.com.
- Siempre se debe indicar que el contenido proviene de ESPN.
- No se debe incluir publicidad dentro del contenido del feed.

Esta función NO reproduce el artículo completo, solo el resumen que ESPN
distribuye en su propio feed público para ese fin.

Además del feed general de ESPN, se usan feeds de prensa local para las ligas
que ESPN no cubre (ej. la LIDOM, desde un medio dominicano). En esos casos se
muestra al pie de la noticia el medio real del que proviene (campo 'source').
"""
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.core.config import settings

from app.services.http_client import DEFAULT_HTTP_TIMEOUT as HTTP_TIMEOUT

FEEDS_BY_SPORT = {
    "baseball": settings.NEWS_RSS_MLB,
}

# Feeds específicos de una liga: url -> nombre de la fuente que se muestra.
# La LIDOM no tiene feed propio en ESPN, así que se cubre desde prensa
# dominicana. Ese feed es de "Deportes" en general (trae otros deportes), por
# eso al sincronizar se filtra a lo que menciona la liga o sus equipos.
FEEDS_BY_LEAGUE = {
    "lidom": (settings.NEWS_RSS_LIDOM, settings.NEWS_SOURCE_LIDOM),
}

# Palabras (se comparan normalizadas, sin acentos) que identifican una noticia
# como de la liga, además de los nombres/apodos de sus equipos (que se
# detectan dinámicamente desde la BD y se pasan a fetch_league_news).
LEAGUE_KEYWORDS = {
    "lidom": ("lidom", "pelota invernal"),
}

# Busca el primer <img src="..."> dentro de HTML (algunos feeds de ESPN
# incrustan la imagen directamente en el resumen en vez de usar una etiqueta
# de imagen aparte).
_INLINE_IMAGE_PATTERN = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def _normalize_for_match(text_value: str) -> str:
    """Minúsculas y sin acentos, para comparar "Águilas" con "aguilas"."""
    decomposed = unicodedata.normalize("NFKD", text_value or "")
    return "".join(character for character in decomposed if not unicodedata.combining(character)).lower()


# Fin de oración: un punto, signo de exclamación o de interrogación seguido de
# un espacio (o del final del texto). El lookahead descarta los puntos de
# decimales ("11.5") y el lookbehind los de abreviaturas ("EE.UU.").
_SENTENCE_END_PATTERN = re.compile(r"(?<![A-ZÁÉÍÓÚÑ])[.!?](?=\s|$)")
# Los feeds dejan un espacio antes de la puntuación cuando venía de una
# etiqueta HTML ("...la victoria ."); se limpia al recortar.
_SPACE_BEFORE_PUNCTUATION_PATTERN = re.compile(r"\s+([.!?,;:])")
# Si el primer fin de oración cae antes de este largo, se asume que es una
# abreviatura ("Dr. Pérez...") y se sigue buscando el siguiente.
MIN_SUMMARY_SENTENCE_LENGTH = 30


def _summarize_first_sentence(summary: str | None) -> str | None:
    """
    Recorta el resumen a su primera oración (hasta el primer punto incluido).

    Los feeds de prensa local traen resúmenes muy largos que hacen las
    tarjetas eternas, así que solo se guarda la primera oración.
    """
    if not summary:
        return summary

    for sentence_end in _SENTENCE_END_PATTERN.finditer(summary):
        if sentence_end.end() >= MIN_SUMMARY_SENTENCE_LENGTH:
            first_sentence = summary[: sentence_end.end()]
            return _SPACE_BEFORE_PUNCTUATION_PATTERN.sub(r"\1", first_sentence).strip()

    return summary.strip()


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


async def fetch_rss_news(feed_url: str, limit: int = 15, source: str = "ESPN") -> list[dict]:
    """
    Descarga y parsea un feed RSS, devolviendo una lista de artículos
    normalizados. 'source' es el medio que se muestra al pie de la noticia.
    """
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
                "source": source,
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


async def fetch_league_news(league_key: str, team_name_hints: list[str], limit: int = 15) -> list[dict]:
    """
    Noticias de una liga concreta (ej. la LIDOM, cubierta por prensa
    dominicana). Ese feed es de "Deportes" en general, así que se descartan
    las noticias que no mencionan la liga ni a ninguno de sus equipos.

    team_name_hints: nombres y apodos de los equipos de la liga, tal como
    están en la BD (se comparan sin acentos ni mayúsculas).

    El resumen se recorta a su primera oración (ver _summarize_first_sentence).
    """
    feed = FEEDS_BY_LEAGUE.get(league_key)
    if not feed:
        return []
    feed_url, feed_source = feed

    # Se pide un lote más grande y se filtra después: el feed mezcla varios
    # deportes, así que no todas las entradas son de la liga.
    fetched_articles = await fetch_rss_news(feed_url, limit=50, source=feed_source)

    normalized_keywords = [_normalize_for_match(keyword) for keyword in LEAGUE_KEYWORDS.get(league_key, ())]
    normalized_hints = [_normalize_for_match(hint) for hint in team_name_hints if hint]

    relevant_articles = []
    for feed_article in fetched_articles:
        # Las palabras propias de la liga (ej. "LIDOM") se buscan en todo el
        # texto, pero los nombres de equipos solo en el titular: "Estrellas" o
        # "Toros" son palabras comunes que en un resumen darían falsos positivos.
        full_text = _normalize_for_match(f"{feed_article.get('title') or ''} {feed_article.get('summary') or ''}")
        title_text = _normalize_for_match(feed_article.get("title") or "")
        mentions_league = any(keyword in full_text for keyword in normalized_keywords)
        mentions_team = any(hint in title_text for hint in normalized_hints)
        if mentions_league or mentions_team:
            relevant_articles.append(feed_article)

    # La prensa local escribe resúmenes de varios párrafos: se recorta a la
    # primera oración para que las tarjetas no queden enormes. (Al feed de ESPN
    # no se le aplica: sus términos de uso piden mostrar el contenido tal cual.)
    for feed_article in relevant_articles:
        feed_article["summary"] = _summarize_first_sentence(feed_article["summary"])

    return relevant_articles[:limit]
