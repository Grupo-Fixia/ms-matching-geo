"""Configuración por variables de entorno. Los nombres coinciden con los de ms-users y ms-services."""
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_ISSUER = "https://auth.fixia.com"
DEFAULT_AUDIENCE = "https://api.fixia.com"


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
    internal_api_key: str = field(default="", repr=False)
    # Cero dependencias síncronas (GC-547): los técnicos y la revocación llegan por Kafka. Los consumidores están
    # apagados por defecto aquí, para las pruebas; from_env los enciende salvo que se apaguen por variable.
    kafka_bootstrap_servers: str = "localhost:9092"
    technicians_consumer_enabled: bool = False
    technicians_topic: str = "fixia.users.technician-states"
    revocations_consumer_enabled: bool = False
    revocations_topic: str = "fixia.users.sessions"
    revocations_max_staleness: float = 5.0
    revocations_lookback: float = 1200.0
    group_prefix: str = "ms-matching-geo"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        # La clave llega como PEM; en un .env las líneas a veces vienen con "\n" escrito como texto.
        public_key = env.get("JWT_PUBLIC_KEY", "").replace("\\n", "\n").strip()
        if not public_key:
            raise ConfigError("JWT_PUBLIC_KEY es obligatoria (clave pública X.509 de ms-users, en PEM)")
        internal_api_key = env.get("INTERNAL_API_KEY", "")
        if not internal_api_key:
            logger.warning("INTERNAL_API_KEY no está configurada: la ruta interna rechaza todo")
        return cls(
            jwt_public_key=public_key,
            jwt_issuer=env.get("JWT_ISSUER") or DEFAULT_ISSUER,
            jwt_audience=env.get("JWT_AUDIENCE") or DEFAULT_AUDIENCE,
            internal_api_key=internal_api_key,
            kafka_bootstrap_servers=env.get("KAFKA_BOOTSTRAP_SERVERS") or env.get("KAFKA_HOST") or "localhost:9092",
            technicians_consumer_enabled=_enabled(env, "FIXIA_TECHNICIANS_CONSUMER_ENABLED"),
            technicians_topic=env.get("FIXIA_TECHNICIANS_TOPIC") or "fixia.users.technician-states",
            revocations_consumer_enabled=_enabled(env, "FIXIA_REVOCATIONS_CONSUMER_ENABLED"),
            revocations_topic=env.get("FIXIA_REVOCATIONS_TOPIC") or "fixia.users.sessions",
            revocations_max_staleness=_seconds(env.get("FIXIA_REVOCATIONS_MAX_STALENESS"), 5.0,
                                               "FIXIA_REVOCATIONS_MAX_STALENESS"),
            revocations_lookback=_seconds(env.get("FIXIA_REVOCATIONS_LOOKBACK"), 1200.0, "FIXIA_REVOCATIONS_LOOKBACK"),
            group_prefix=env.get("FIXIA_CONSUMER_GROUP_PREFIX") or "ms-matching-geo",
        )


def _enabled(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "true").strip().lower() != "false"
