"""Seguridad: hashing de contraseñas (bcrypt) y tokens de sesión (JWT).

Decisiones de seguridad tomadas aquí:
- Contraseñas: nunca se guardan en texto plano, se usa bcrypt (passlib).
- Sesión: JWT firmado con SECRET_KEY, con expiración obligatoria.
- El token se entrega al cliente como cookie httpOnly (no accesible desde JS),
  para reducir el riesgo de robo de token vía XSS. Se usa SameSite=Lax para
  mitigar CSRF en peticiones cross-site.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from passlib.context import CryptContext

from app.core.config import settings

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    if len(plain_password.encode("utf-8")) > 72:
        # No debería llegar hasta aquí (el esquema de registro ya lo valida),
        # pero se deja como red de seguridad: mejor un error claro que el
        # ValueError interno de bcrypt.
        raise ValueError("La contraseña no puede tener más de 72 caracteres.")
    return password_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if len(plain_password.encode("utf-8")) > 72:
        # Ninguna cuenta real pudo haberse registrado con una contraseña así
        # de larga (ver hash_password), así que nunca puede ser correcta.
        # Se devuelve False en vez de dejar que bcrypt truene con un 500.
        return False
    return password_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str, expires_minutes: Optional[int] = None) -> str:
    """Crea un JWT cuyo 'sub' es el identificador del usuario (string)."""
    lifetime_minutes = expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    expiration_time = datetime.now(timezone.utc) + timedelta(minutes=lifetime_minutes)
    token_claims = {"sub": user_id, "exp": expiration_time, "iat": datetime.now(timezone.utc)}
    return jwt.encode(token_claims, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """Devuelve el 'sub' (id de usuario) si el token es válido, o None si no lo es."""
    try:
        token_claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        subject_claim = token_claims.get("sub")
        return str(subject_claim) if subject_claim is not None else None
    except jwt.PyJWTError:
        return None
