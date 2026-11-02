"""Validación del access token de ms-users con su clave pública (ADR-039). Verifica lo mismo que ms-services: firma
RS256, vigencia, emisor y audiencia."""
from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from src.app.application.errors import InvalidToken

# Tolerancia mínima entre relojes; la misma que ms-users y ms-services (5 s).
CLOCK_SKEW_SECONDS = 5

# Sin alguno de estos claims el token no sirve: sin "jti" no se puede comprobar la revocación.
REQUIRED_CLAIMS = ["exp", "iss", "aud", "jti", "sub"]


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    jti: str
    roles: tuple[str, ...]


class JwtValidator:
    def __init__(self, public_key_pem: str, issuer: str, audience: str) -> None:
        key = load_pem_public_key(public_key_pem.encode("utf-8"))
        if not isinstance(key, RSAPublicKey):
            raise ValueError("JWT_PUBLIC_KEY debe ser una clave pública RSA")
        self._key = key
        self._issuer = issuer
        self._audience = audience

    def validate(self, token: str) -> TokenClaims:
        try:
            # El algoritmo se fija aquí y no se lee de la cabecera del token: evita aceptar "none" o HS256 firmado
            # con la clave pública.
            claims = jwt.decode(
                token,
                self._key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as error:
            raise InvalidToken() from error

        roles = claims.get("roles")
        return TokenClaims(
            subject=str(claims["sub"]),
            jti=str(claims["jti"]),
            roles=tuple(role for role in roles if isinstance(role, str)) if isinstance(roles, list) else (),
        )
