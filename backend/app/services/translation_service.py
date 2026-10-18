"""
Traducción automática de contenido (noticias, jugadas en vivo) al español.

Se usa deep-translator con CADENA DE MOTORES (MyMemory -> Google):

- MyMemory va primero porque es el único que funcionó de verdad. Ojo: exige
  códigos de idioma con región ("en-GB"/"es-ES"); con "en"/"es" a secas
  lanzaba LanguageNotSupportedException y el respaldo nunca servía.
- Google queda de segundo: da mejor calidad de traducción, pero su endpoint
  gratuito bloquea con 429 las IPs de datacenters (Render/Railway), así que
  como primera opción dejaba todas las noticias en inglés.

Si todos los motores fallan se devuelve None y quien llama usa el original.

REGLA IMPORTANTE: nunca se traducen nombres propios (equipos, jugadores,
ciudades, estadios) — nada de eso pasa por aquí. Solo texto libre como
titulares y resúmenes de noticias, o descripciones de jugadas.
"""
import logging

from deep_translator import GoogleTranslator, MyMemoryTranslator

logger = logging.getLogger("bfb.translation")

# Límite práctico por texto: motores gratuitos de traducción suelen tener
# un límite de caracteres por request (ej. 5000). Un titular o resumen de
# noticia nunca se acerca a esto, es solo una salvaguarda.
MAX_TRANSLATABLE_CHARS = 4500

# MyMemory exige el idioma con región (no acepta "en"/"es" a secas).
MYMEMORY_SOURCE_LANG = "en-GB"
MYMEMORY_TARGET_LANG = "es-ES"


def _translate_via_mymemory(source_text: str) -> str | None:
    return MyMemoryTranslator(source=MYMEMORY_SOURCE_LANG, target=MYMEMORY_TARGET_LANG).translate(source_text)


def _translate_via_google(source_text: str) -> str | None:
    return GoogleTranslator(source="en", target="es").translate(source_text)


def translate_to_spanish(text: str | None) -> str | None:
    """
    Traduce un texto de inglés a español probando MyMemory primero y Google
    como respaldo. Si todo falla (motores caídos, límites excedidos, sin
    conexión), devuelve None en vez de lanzar una excepción — así un fallo
    de traducción nunca rompe la sincronización de noticias ni la consulta
    de un partido en vivo. El código que llama a esto debe usar el texto
    original en inglés como respaldo cuando esto devuelve None.
    """
    if not text:
        return None
    source_snippet = text[:MAX_TRANSLATABLE_CHARS]
    for provider_name, provider in (("mymemory", _translate_via_mymemory), ("google", _translate_via_google)):
        try:
            translated_text = provider(source_snippet)
            if (
                translated_text
                and translated_text.strip()
                and translated_text.strip().lower() != source_snippet.strip().lower()
            ):
                return translated_text
        except Exception:
            logger.info("Motor de traducción '%s' falló; probando el siguiente.", provider_name)
            continue
    logger.warning("No se pudo traducir un texto al español; se usará el original en inglés como respaldo.")
    return None
