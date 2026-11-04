"""Consulta a ms-users si un access token fue revocado con logout (ADR-039). La lista de tokens revocados vive en la
base de ms-users, por eso se pregunta por su ruta interna `GET /internal/tokens/{jti}/status`."""
import logging
from urllib.parse import quote

import httpx

from src.app.application.errors import RevocationCheckFailed

API_KEY_HEADER = "X-Internal-Api-Key"

logger = logging.getLogger(__name__)


class TokenRevocationClient:
    """Sin caché y fallando cerrado: si ms-users no responde o responde algo inválido, la comprobación falla y el
    token se rechaza, porque aceptarlo haría valer un token revocado mientras dure la caída."""

    def __init__(self, client: httpx.Client, api_key: str) -> None:
        self._client = client
        self._api_key = api_key

    def is_revoked(self, jti: str) -> bool:
        # El jti viaja en la ruta: se codifica entero para que no pueda alterarla (por ejemplo con "/" o "..").
        path = f"/internal/tokens/{quote(jti, safe='')}/status"
        try:
            response = self._client.get(path, headers={API_KEY_HEADER: self._api_key})
        except httpx.HTTPError as error:
            logger.warning("ms-users no respondió a la consulta de revocación (%s)", type(error).__name__)
            raise RevocationCheckFailed("ms-users no respondió") from error
        if response.status_code != 200:
            logger.warning("ms-users respondió %s a la consulta de revocación", response.status_code)
            raise RevocationCheckFailed(f"ms-users respondió {response.status_code}")
        try:
            revoked = response.json()["revoked"]
        except (ValueError, KeyError, TypeError) as error:
            raise RevocationCheckFailed("ms-users respondió con un cuerpo inválido") from error
        if not isinstance(revoked, bool):
            raise RevocationCheckFailed("ms-users respondió con un cuerpo inválido")
        return revoked
