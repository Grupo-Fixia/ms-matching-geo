import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest

from src.app.application.errors import InvalidToken
from src.app.infrastructure.jwt_validator import JwtValidator
from tests.conftest import AUDIENCE, ISSUER, make_token


@pytest.fixture
def validator(keys) -> JwtValidator:
    return JwtValidator(keys[1], ISSUER, AUDIENCE)


def test_un_token_valido_devuelve_sus_claims(validator, keys):
    token = make_token(keys[0], roles=("ROLE_CLIENT",), jti="abc-123")

    claims = validator.validate(token)

    assert claims.jti == "abc-123"
    assert claims.roles == ("ROLE_CLIENT",)
    assert claims.subject.startswith("usr_")


def test_acepta_la_audiencia_entre_varias(validator, keys):
    assert validator.validate(make_token(keys[0], audience=["otra", AUDIENCE]))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expires_in": -60},
        {"issuer": "https://otro.example"},
        {"audience": "https://otra-audiencia.example"},
        {"omit": ("jti",)},
        {"omit": ("sub",)},
        {"omit": ("exp",)},
        {"omit": ("iss",)},
        {"omit": ("aud",)},
    ],
)
def test_rechaza_tokens_con_claims_invalidos_o_ausentes(validator, keys, kwargs):
    with pytest.raises(InvalidToken):
        validator.validate(make_token(keys[0], **kwargs))


def test_tolera_los_5_segundos_de_desfase_de_reloj(validator, keys):
    assert validator.validate(make_token(keys[0], expires_in=-3))


def test_rechaza_un_token_firmado_con_otra_clave(validator, other_keys):
    with pytest.raises(InvalidToken):
        validator.validate(make_token(other_keys[0]))


def test_rechaza_basura(validator):
    for token in ("", "no-es-un-jwt", "a.b.c"):
        with pytest.raises(InvalidToken):
            validator.validate(token)


def test_rechaza_el_algoritmo_none(validator):
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": "usr_1", "aud": [AUDIENCE], "exp": now + 900, "jti": "x", "roles": ["ROLE_CLIENT"]}
    with pytest.raises(InvalidToken):
        validator.validate(jwt.encode(claims, None, algorithm="none"))


def test_rechaza_hs256_firmado_con_la_clave_publica(validator, keys):
    """Ataque clásico de confusión de algoritmo: el algoritmo lo fija el servicio, no la cabecera del token."""

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(
        json.dumps(
            {"iss": ISSUER, "sub": "usr_1", "aud": [AUDIENCE], "exp": now + 900, "jti": "x", "roles": ["ROLE_CLIENT"]}
        ).encode()
    )
    signature = b64(hmac.new(keys[1].encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())

    with pytest.raises(InvalidToken):
        validator.validate(f"{header}.{payload}.{signature}")


def test_roles_con_forma_inesperada_se_ignoran(validator, keys):
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": "usr_1", "aud": [AUDIENCE], "exp": now + 900, "jti": "x", "roles": "ROLE_CLIENT"}
    token = jwt.encode(claims, keys[0], algorithm="RS256")

    assert validator.validate(token).roles == ()


def test_la_clave_debe_ser_una_clave_publica_rsa_en_pem():
    with pytest.raises(ValueError):
        JwtValidator("no-es-un-pem", ISSUER, AUDIENCE)


def test_rechaza_una_clave_publica_que_no_es_rsa():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pem = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )

    with pytest.raises(ValueError, match="RSA"):
        JwtValidator(pem, ISSUER, AUDIENCE)
