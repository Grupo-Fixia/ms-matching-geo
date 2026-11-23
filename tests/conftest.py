"""Utilidades de prueba: un par RSA para firmar tokens como lo haría ms-users y un doble de la réplica local (GC-547)
que responde la búsqueda de técnicos y la revocación de tokens, en lugar de ms-users."""
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from src.app.application.errors import RevocationCheckFailed
from src.app.config import Settings
from src.app.domain.models import Candidate, CandidatePage, Category, ZoneCircle
from src.app.main import create_app

ISSUER = "https://auth.fixia.com"
AUDIENCE = "https://api.fixia.com"
INTERNAL_KEY = "clave-interna-de-prueba"


def new_key_pair() -> tuple[str, str]:
    """(privada PKCS#8, pública X.509), ambas en PEM: el mismo formato que usa ms-users."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private_pem, public_pem


@pytest.fixture(scope="session")
def keys() -> tuple[str, str]:
    return new_key_pair()


@pytest.fixture(scope="session")
def other_keys() -> tuple[str, str]:
    return new_key_pair()


def make_token(
    private_pem: str,
    *,
    roles: tuple[str, ...] = ("ROLE_CLIENT",),
    jti: str | None = None,
    expires_in: int = 900,
    issuer: str = ISSUER,
    audience: str | list[str] = AUDIENCE,
    omit: tuple[str, ...] = (),
) -> str:
    now = int(time.time())
    claims = {
        "iss": issuer,
        "sub": f"usr_{uuid.uuid4()}",
        "aud": audience if isinstance(audience, list) else [audience],
        "iat": now,
        "exp": now + expires_in,
        "jti": jti or str(uuid.uuid4()),
        "roles": list(roles),
    }
    for name in omit:
        claims.pop(name)
    return jwt.encode(claims, private_pem, algorithm="RS256")


def item(
    user_id: str,
    city: str = "Bogotá",
    circle: tuple[float, float, int] | None = None,
    name: str = "Carlos G.",
    categories: tuple[str, ...] = ("PLUMBING",),
) -> Candidate:
    """Un técnico tal como lo entrega el directorio."""
    return Candidate(
        user_id=user_id,
        display_name=name,
        categories=tuple(categories),
        city=city,
        circle=ZoneCircle(*circle) if circle else None,
    )


def page(items: list[Candidate], next_cursor: str | None = None) -> CandidatePage:
    return CandidatePage(items=items, next_cursor=next_cursor)


def raising(error: Exception) -> Callable[[dict], CandidatePage]:
    """Un `on_search` que falla con `error`."""

    def search(body: dict) -> CandidatePage:
        raise error

    return search


@dataclass
class FakeUsers:
    """Doble del directorio de técnicos y de la lista de revocados. `on_search` recibe la consulta como diccionario
    (las mismas claves que antes viajaban a ms-users) y decide la página; `revoked` son los jti revocados y
    `revocation_error` simula una lista que no está al día."""

    on_search: Callable[[dict], CandidatePage] = lambda body: page([])
    revoked: set[str] = field(default_factory=set)
    revocation_error: bool = False
    search_bodies: list[dict] = field(default_factory=list)
    checked_jtis: list[str] = field(default_factory=list)

    def search(
        self, category: Category, city: str, limit: int, cursor: str | None, expected_at: datetime | None = None
    ) -> CandidatePage:
        body: dict[str, object] = {"category": category.value, "city": city, "limit": limit}
        if cursor is not None:
            body["cursor"] = cursor
        if expected_at is not None:
            body["expectedAt"] = expected_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        self.search_bodies.append(body)
        return self.on_search(body)

    def is_revoked(self, jti: str) -> bool:
        self.checked_jtis.append(jti)
        if self.revocation_error:
            raise RevocationCheckFailed("La lista no está al día")
        return jti in self.revoked


@pytest.fixture
def users() -> FakeUsers:
    return FakeUsers()


def build_client(public_pem: str, users: FakeUsers, internal_api_key: str = INTERNAL_KEY) -> TestClient:
    """La aplicación con el doble de la réplica en lugar de los consumidores de Kafka."""
    settings = Settings(
        jwt_public_key=public_pem,
        jwt_issuer=ISSUER,
        jwt_audience=AUDIENCE,
        internal_api_key=internal_api_key,
    )
    return TestClient(create_app(settings, directory=users, revocation_checker=users))


@pytest.fixture
def client(keys: tuple[str, str], users: FakeUsers) -> TestClient:
    return build_client(keys[1], users)
