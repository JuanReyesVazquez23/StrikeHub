import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import admin, auth, favorites, games, leagues, news, postseason, predictions, stats
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.migrations import run_lightweight_migrations
from app.services.sync_service import ensure_base_catalog, run_full_sync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bfb.main")

BACKGROUND_SYNC_INTERVAL_SECONDS = 300  # 5 minutos

# Ruta absoluta a la carpeta frontend/, calculada desde la ubicación de este
# archivo (backend/app/main.py -> sube 2 niveles -> backend/ -> frontend/).
# frontend/ vive DENTRO de backend/ a propósito: en Railway, el servicio está
# configurado con Root Directory=backend, así que solo lo que esté dentro de
# esa carpeta llega al build. Si frontend/ estuviera al lado de backend/
# (como estaba antes), Railway la excluiría del despliegue.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


async def _run_periodic_sync_loop() -> None:
    """Refresca los datos de MLB periódicamente."""
    while True:
        try:
            await run_full_sync()
        except Exception:  # noqa: BLE001 - un fallo de sync no debe tumbar el servidor
            logger.exception("Error durante la sincronización periódica.")
        await asyncio.sleep(BACKGROUND_SYNC_INTERVAL_SECONDS)


def _start_sync_loop_in_background_thread() -> None:
    """
    Corre _run_periodic_sync_loop en su PROPIO hilo, con su PROPIO event loop,
    separado del event loop principal que atiende las peticiones HTTP.

    Por qué: sync_service.py usa sesiones SÍNCRONAS de SQLAlchemy (no la
    versión async) para hablar con la base de datos. Si esa sincronización
    corriera en el mismo event loop que usa Uvicorn para atender HTTP (como
    estaba antes, con asyncio.create_task), cada consulta a la base de datos
    bloquea TODO el servidor mientras dura — nadie puede registrarse, iniciar
    sesión ni cargar ninguna página mientras el ciclo de sincronización está
    corriendo (la sincronización de MLB tarda varios minutos entre equipos,
    partidos y rosters). En un
    hilo aparte, el servidor sigue respondiendo con normalidad sin importar
    cuánto tarde la sincronización.
    """
    asyncio.run(_run_periodic_sync_loop())


@asynccontextmanager
async def lifespan(application: FastAPI):
    # NOTA: create_all() es adecuado para desarrollo. En producción se
    # recomienda usar Alembic para migraciones versionadas del esquema.
    Base.metadata.create_all(bind=engine)

    # Parchea columnas nuevas en tablas que ya existían antes de este cambio
    # (ver core/migrations.py para el porqué). Seguro de correr siempre.
    run_lightweight_migrations(engine)

    database_session = SessionLocal()
    try:
        ensure_base_catalog(database_session)
    finally:
        database_session.close()

    # daemon=True: el hilo se cierra solo cuando el proceso termina, no hace
    # falta (ni conviene) intentar cancelarlo a mano en el shutdown.
    threading.Thread(target=_start_sync_loop_in_background_thread, daemon=True).start()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    # En producción no se expone Swagger/ReDoc: evita enumerar /admin/*.
    docs_url=None if settings.ENV == "production" else "/docs",
    redoc_url=None if settings.ENV == "production" else "/redoc",
    openapi_url=None if settings.ENV == "production" else "/openapi.json",
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """
    Cabeceras de seguridad mínimas.
    La CSP permite scripts 'self' (sin onclick inline — ver main.js
    data-open-auth), estilos inline (el HTML usa style="..." en varios
    puntos), imágenes https:/data: (logos ESPN/MLB remotos) y Google Fonts.
    """
    response = await call_next(request)
    security_policy = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' https: data:; "
        "connect-src 'self'; "
        "form-action 'self'"
    )
    response.headers["Content-Security-Policy"] = security_policy
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.ENV == "production":
        # Solo tiene sentido con HTTPS (Render/Railway lo sirven).
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # nunca "*" en producción cuando se usan cookies
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(leagues.router, prefix=settings.API_V1_PREFIX)
app.include_router(games.router, prefix=settings.API_V1_PREFIX)
app.include_router(news.router, prefix=settings.API_V1_PREFIX)
app.include_router(favorites.router, prefix=settings.API_V1_PREFIX)
app.include_router(predictions.router, prefix=settings.API_V1_PREFIX)
app.include_router(stats.router, prefix=settings.API_V1_PREFIX)
app.include_router(admin.router, prefix=settings.API_V1_PREFIX)
app.include_router(postseason.router, prefix=settings.API_V1_PREFIX)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "project": settings.PROJECT_NAME}


# Sirve el frontend estático (HTML/CSS/JS) desde el mismo servidor.
# Si la carpeta no existe (ej. estructura de despliegue distinta), se avisa
# claramente en los logs en vez de fallar con un error críptico de FastAPI.
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    logger.warning(
        "No se encontró la carpeta frontend en %s; el sitio no se servirá "
        "desde este proceso (la API seguirá funcionando en %s).",
        FRONTEND_DIR,
        settings.API_V1_PREFIX,
    )
