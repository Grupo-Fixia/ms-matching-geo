"""Revocación de tokens sin consultar a ms-users (GC-547, cero dependencias síncronas).

La lista local de tokens revocados se alimenta con `sesion.revocada` (`fixia.users.sessions`) y es la única fuente:
un token revocado puede servir aquí el tiempo que tarda el evento en llegar (el retraso del Outbox de ms-users, ~2 s,
más Kafka), la ventana corta que aceptó el PO. Si la lista no está al día (el consumidor no confirmó con el broker hace
menos de `max_staleness` segundos), la comprobación falla y el token se rechaza (falla cerrado).
"""
import json
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from src.app.application.errors import RevocationCheckFailed

SESSION_REVOKED = "sesion.revocada"


def _now() -> float:
    return time.time()


class RevocationList:
    """Tokens revocados en memoria, cada uno hasta su vencimiento. Segura entre hilos: el consumidor escribe y las
    peticiones leen."""

    def __init__(self, max_staleness: float = 5.0, clock: Callable[[], float] = _now) -> None:
        self._revoked: dict[str, float] = {}
        self._lock = threading.Lock()
        self._clock = clock
        self._max_staleness = max_staleness
        self._caught_up_at: float | None = None

    def add(self, jti: str, expires_at: float) -> None:
        now = self._clock()
        with self._lock:
            if expires_at > now:
                self._revoked[jti] = expires_at
            for key in [key for key, expiry in self._revoked.items() if expiry <= now]:
                del self._revoked[key]

    def contains(self, jti: str) -> bool:
        with self._lock:
            expiry = self._revoked.get(jti)
        return expiry is not None and expiry > self._clock()

    def mark_caught_up(self) -> None:
        """El consumidor confirmó con el broker que no le falta nada por leer."""
        self._caught_up_at = self._clock()

    def is_fresh(self) -> bool:
        last = self._caught_up_at
        return last is not None and last + self._max_staleness >= self._clock()


class ReplicatedRevocationChecker:
    """`is_revoked(jti)` con la lista local: verdadero si la lista lo conoce como revocado; si la lista no está al día,
    `RevocationCheckFailed` (falla cerrado)."""

    def __init__(self, revocation_list: RevocationList) -> None:
        self._list = revocation_list

    def is_revoked(self, jti: str) -> bool:
        if self._list.contains(jti):
            return True
        if not self._list.is_fresh():
            raise RevocationCheckFailed("La lista local de revocados no está al día")
        return False


def apply_message(revocation_list: RevocationList, value: bytes | str | None) -> None:
    """Aplica un mensaje del tópico. Los demás tipos se ignoran; uno inválido lanza `ValueError`."""
    if value is None:
        raise ValueError("Mensaje vacío")
    try:
        root = json.loads(value)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("El mensaje no es JSON válido") from error
    if not isinstance(root, dict) or root.get("eventType") != SESSION_REVOKED:
        return
    data = root.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("jti"), str) or not data["jti"].strip():
        raise ValueError("Falta data.jti")
    try:
        expires_at = datetime.fromisoformat(str(data["expiresAt"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as error:
        raise ValueError("Falta data.expiresAt o no es válido") from error
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    revocation_list.add(data["jti"], expires_at.timestamp())
