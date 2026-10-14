"""
Rate limiter en memoria, pensado para proteger /auth/login y /auth/register
contra ataques de fuerza bruta, y los endpoints costosos (búsquedas con
llamadas a APIs externas) contra abuso de cuota.

NOTA: esta implementación guarda el estado en memoria del proceso. Funciona
bien para un solo servidor/worker. Si en producción se despliega con varios
workers o instancias, se recomienda sustituir esto por un backend compartido
(Redis) para que el límite aplique globalmente.
"""
import time
from collections import defaultdict
from threading import Lock
from typing import Optional

from fastapi import HTTPException, Request, status

from app.core.config import settings

_attempt_timestamps_by_bucket: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = Lock()

# Tope de buckets en memoria: evita crecimiento ilimitado (un atacante
# rotando IPs/buckets no puede agotar la RAM del proceso).
_MAX_TRACKED_BUCKETS = 10000


def enforce_rate_limit(
    request: Request,
    bucket: str,
    limit: Optional[int] = None,
    window_seconds: Optional[int] = None,
) -> None:
    """
    Lanza 429 si la IP supera el número de intentos permitidos en la ventana.
    Si no se pasan limit/window, se usan los de login (más estrictos).
    """
    client_address = request.client.host if request.client else "unknown"
    bucket_key = f"{bucket}:{client_address}"
    current_timestamp = time.time()
    rate_window = window_seconds if window_seconds is not None else settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    max_attempts = limit if limit is not None else settings.LOGIN_RATE_LIMIT_ATTEMPTS

    with _rate_limit_lock:
        recent_attempts = [t for t in _attempt_timestamps_by_bucket[bucket_key] if current_timestamp - t < rate_window]
        if len(recent_attempts) >= max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiados intentos. Inténtalo de nuevo más tarde.",
            )
        recent_attempts.append(current_timestamp)
        _attempt_timestamps_by_bucket[bucket_key] = recent_attempts
        # Evicción: si hay demasiados buckets, se purgan los expirados.
        if len(_attempt_timestamps_by_bucket) > _MAX_TRACKED_BUCKETS:
            expired_keys = [
                tracked_key
                for tracked_key, stored_attempts in _attempt_timestamps_by_bucket.items()
                if not stored_attempts or current_timestamp - stored_attempts[-1] >= rate_window
            ]
            for expired_key in expired_keys[: len(_attempt_timestamps_by_bucket) - _MAX_TRACKED_BUCKETS]:
                _attempt_timestamps_by_bucket.pop(expired_key, None)
