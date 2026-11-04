"""Configuración por variables de entorno. Los nombres coinciden con los de ms-users y ms-services."""
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_ISSUER = "https://auth.fixia.com"
DEFAULT_AUDIENCE = "https://api.fixia.com"
DEFAULT_USERS_BASE_URL = "http://ms-users:8080"


class ConfigError(Exception):
    """Falta una variable obligatoria o tiene un valor que no se puede usar."""


def _seconds(raw: str | None, default: float, name: str) -> float:
    """Segundos a partir de "2", "1.5", "2s" o "500ms" (el formato de duración que usa ms-services)."""
    if raw is None or not raw.strip():
        return default
    text = raw.strip().lower()
    try:
        if text.endswith("ms"):
            return float(text[:-2]) / 1000
        return float(text.removesuffix("s"))
    except ValueError as error:
        raise ConfigError(f"{name} no es una duración válida: {raw!r}") from error


@dataclass(frozen=True)
class Settings:
    jwt_public_key: str = field(repr=False)
    jwt_issuer: str = DEFAULT_ISSUER
    jwt_audience: str = DEFAULT_AUDIENCE
    users_base_url: str = DEFAULT_USERS_BASE_URL
    internal_api_key: str = field(default="", repr=False)
    users_connect_timeout: float = 1.0
    users_read_timeout: float = 2.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        # La clave llega como PEM; en un .env las líneas a veces vienen con "\n" escrito como texto.
        public_key = env.get("JWT_PUBLIC_KEY", "").replace("\\n", "\n").strip()
        if not public_key:
            raise ConfigError("JWT_PUBLIC_KEY es obligatoria (clave pública X.509 de ms-users, en PEM)")
        internal_api_key = env.get("INTERNAL_API_KEY", "")
        if not internal_api_key:
            logger.warning(
                "INTERNAL_API_KEY no está configurada: la ruta interna rechaza todo y no se puede comprobar "
                "la revocación de los tokens, así que la ruta pública también rechaza todo"
            )
        return cls(
            jwt_public_key=public_key,
            jwt_issuer=env.get("JWT_ISSUER") or DEFAULT_ISSUER,
            jwt_audience=env.get("JWT_AUDIENCE") or DEFAULT_AUDIENCE,
            users_base_url=env.get("USERS_BASE_URL") or DEFAULT_USERS_BASE_URL,
            internal_api_key=internal_api_key,
            users_connect_timeout=_seconds(env.get("USERS_CONNECT_TIMEOUT"), 1.0, "USERS_CONNECT_TIMEOUT"),
            users_read_timeout=_seconds(env.get("USERS_READ_TIMEOUT"), 2.0, "USERS_READ_TIMEOUT"),
        )
