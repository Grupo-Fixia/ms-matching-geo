"""Utilidades de prueba: un par RSA para firmar tokens como lo haría ms-users y un ms-users simulado (transporte de
httpx) que responde la búsqueda de técnicos y la consulta de revocación."""
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import unquote

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.main import create_app

ISSUER = "https://auth.fixia.com"
AUDIENCE = "https://api.fixia.com"
INTERNAL_KEY = "clave-interna-de-prueba"
USERS_URL = "http://ms-users:8080"


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
) -> dict:
    """Un técnico tal como lo devuelve ms-users."""
    return {
        "userId": user_id,
        "displayName": name,
        "categories": list(categories),
        "city": city,
        "circle": {"latitude": circle[0], "longitude": circle[1], "radiusKm": circle[2]} if circle else None,
    }


def page(items: list[dict], next_cursor: str | None = None) -> httpx.Response:
    return httpx.Response(200, json={"items": items, "nextCursor": next_cursor})


@dataclass
class FakeUsers:
    """ms-users simulado. `on_search` decide la respuesta de la búsqueda; `revoked` son los jti revocados."""

    on_search: Callable[[dict], httpx.Response] = lambda body: page([])
    revoked: set[str] = field(default_factory=set)
    revocation_error: Callable[[], httpx.Response] | None = None
    search_bodies: list[dict] = field(default_factory=list)
    revocation_paths: list[str] = field(default_factory=list)
    api_keys: list[str | None] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.api_keys.append(request.headers.get("X-Internal-Api-Key"))
        if request.headers.get("X-Internal-Api-Key") != INTERNAL_KEY:
            return httpx.Response(401)
        path = request.url.raw_path.decode()
        if request.method == "POST" and path == "/internal/technicians/search":
            body = json.loads(request.content)
            self.search_bodies.append(body)
            return self.on_search(body)
        if request.method == "GET" and path.startswith("/internal/tokens/") and path.endswith("/status"):
            self.revocation_paths.append(path)
            if self.revocation_error is not None:
                return self.revocation_error()
            jti = path.removeprefix("/internal/tokens/").removesuffix("/status")
            return httpx.Response(200, json={"revoked": unquote(jti) in self.revoked})
        return httpx.Response(404)


@pytest.fixture
def users() -> FakeUsers:
    return FakeUsers()


def build_client(
    public_pem: str, users: "FakeUsers | Callable[[httpx.Request], httpx.Response]", internal_api_key: str = INTERNAL_KEY
) -> TestClient:
    """La aplicación con ms-users simulado: un `FakeUsers` o, para forzar fallos de red, un manejador propio."""
    handler = users.handle if isinstance(users, FakeUsers) else users
    settings = Settings(
        jwt_public_key=public_pem,
        jwt_issuer=ISSUER,
        jwt_audience=AUDIENCE,
        users_base_url=USERS_URL,
        internal_api_key=internal_api_key,
    )
    http_client = httpx.Client(base_url=USERS_URL, transport=httpx.MockTransport(handler))
    return TestClient(create_app(settings, http_client))


@pytest.fixture
def client(keys: tuple[str, str], users: FakeUsers) -> TestClient:
    return build_client(keys[1], users)
