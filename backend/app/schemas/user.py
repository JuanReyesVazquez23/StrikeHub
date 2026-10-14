import re

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]{3,20}$")


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, username: str) -> str:
        if not USERNAME_REGEX.match(username):
            raise ValueError(
                "El usuario debe tener entre 3 y 20 caracteres (letras, números o guion bajo)."
            )
        return username

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: str) -> str:
        if len(password) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres.")
        if len(password.encode("utf-8")) > 72:
            # Límite real de bcrypt (72 bytes, no caracteres — un emoji o una
            # letra con acento puede pesar varios bytes). Sin este chequeo,
            # bcrypt lanza un error interno feo y el registro responde 500
            # en vez de un mensaje claro.
            raise ValueError("La contraseña no puede tener más de 72 caracteres.")
        return password


class UserLogin(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, username: str) -> str:
        if len(username) > 20:
            raise ValueError("Usuario o contraseña incorrectos.")
        return username

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: str) -> str:
        # Tope para que un payload gigante no llegue a bcrypt (costoso).
        if len(password.encode("utf-8")) > 72:
            raise ValueError("Usuario o contraseña incorrectos.")
        return password


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    bfb_points: int
    preferred_language: str
    is_admin: bool = False


class LanguageUpdate(BaseModel):
    preferred_language: str

    @field_validator("preferred_language")
    @classmethod
    def validate_language(cls, language: str) -> str:
        if language not in ("es", "en"):
            raise ValueError("Idioma no soportado. Usa 'es' o 'en'.")
        return language
