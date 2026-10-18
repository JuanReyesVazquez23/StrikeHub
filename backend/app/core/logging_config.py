"""
Configuración de logging compartida por el servidor web y el trabajo de
sincronización (cron).

Por qué existe: librerías como httpx escriben una línea INFO por CADA petición
HTTP. Un ciclo de sincronización hace decenas de peticiones (los rosters de la
MLB son ~30 equipos, uno por petición), así que el proceso escupe cientos de
líneas por corrida. En un cron eso es ruido puro: infla la salida del trabajo y
puede hacer que la plataforma lo acabe deshabilitando por volumen de logs.

Aquí se mantiene el nivel general en INFO (para conservar los resúmenes útiles
del negocio) y se silencian a WARNING los loggers charlatanes de terceros.
"""
import logging

# Loggers de terceros que escriben una línea por petición o por detalle interno
# y no aportan nada al diagnóstico del negocio. Si algún día hay que depurar
# una petición HTTP concreta, se sube el nivel de ese logger a INFO a mano.
NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "feedparser",
    "asyncio",
    "multipart",
    "python_multipart",
)

DEFAULT_LOG_LEVEL = logging.INFO


def configure_logging(level: int = DEFAULT_LOG_LEVEL) -> None:
    """
    Deja el logging listo para cualquier punto de entrada (servidor o cron).

    Es idempotente: el manejador raíz se configura una sola vez, pero el
    silenciado de los loggers de terceros se vuelve a aplicar en cada llamada
    (por eso no basta con un logging.basicConfig suelto en cada entrada).
    """
    logging.basicConfig(level=level)

    for logger_name in NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
