"""Autenticación de las dos rutas: la interna con la clave compartida (ADR-040) y la pública con el JWT de ms-users
(ADR-039). Ambas dan siempre el mismo 401, sin explicar el motivo."""
import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from src.app.application.errors import (
    AccessDenied,
    AuthenticationFailed,
    InvalidToken,
    RevocationCheckFailed,
)
from src.app.application.matching_service import MatchingService
from src.app.infrastructure.jwt_validator import JwtValidator, TokenClaims
from src.app.infrastructure.token_revocation import TokenRevocationClient

CLIENT_ROLE = "ROLE_CLIENT"

# `auto_error=False`: la falta de credencial la resolvemos nosotros con el mismo 401 de siempre. Estos esquemas
# también son los que aparecen en el OpenAPI.
bearer_scheme = HTTPBearer(auto_error=False, description="Access token de ms-users (JWT RS256) de un cliente.")
internal_key_scheme = APIKeyHeader(
    name="X-Internal-Api-Key", auto_error=False, description="Clave compartida entre microservicios (INTERNAL_API_KEY)."
)


@dataclass(frozen=True)
class Container:
    """Lo que las dependencias necesitan, armado una sola vez al crear la aplicación."""

    matching_service: MatchingService
    jwt_validator: JwtValidator
    revocation_client: TokenRevocationClient
    internal_api_key: str


def get_container(request: Request) -> Container:
    return request.app.state.container


def _sha256(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def require_internal(
    api_key: str | None = Depends(internal_key_scheme), container: Container = Depends(get_container)
) -> None:
    """Comparación sobre los hashes SHA-256 con `compare_digest`, que no depende del contenido de la clave enviada.
    Sin clave configurada, la ruta rechaza todo."""
    if not container.internal_api_key or not api_key:
        raise AuthenticationFailed()
    if not hmac.compare_digest(_sha256(container.internal_api_key), _sha256(api_key)):
        raise AuthenticationFailed()


def require_client(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    container: Container = Depends(get_container),
) -> TokenClaims:
    """Firma, vigencia, emisor y audiencia; luego revocación en ms-users (sin caché, falla cerrado); por último el rol.
    Solo un cliente puede explorar técnicos."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationFailed()
    try:
        claims = container.jwt_validator.validate(credentials.credentials)
        revoked = container.revocation_client.is_revoked(claims.jti)
    except (InvalidToken, RevocationCheckFailed) as error:
        raise AuthenticationFailed() from error
    if revoked:
        raise AuthenticationFailed()
    if CLIENT_ROLE not in claims.roles:
        raise AccessDenied()
    return claims
