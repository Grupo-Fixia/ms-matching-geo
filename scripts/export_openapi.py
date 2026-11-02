"""Genera docs/openapi.yaml a partir de la aplicación, para que el contrato publicado no se desvíe del código.

Uso (desde la raíz del repositorio, con las dependencias de desarrollo):

    python -m scripts.export_openapi

Una prueba (tests/test_openapi.py) falla si el archivo no coincide con lo que genera la aplicación.
"""
from pathlib import Path

import httpx
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.app.config import Settings
from src.app.main import create_app

OPENAPI_PATH = Path(__file__).resolve().parent.parent / "docs" / "openapi.yaml"


def build_spec() -> dict:
    """El OpenAPI de la aplicación. La clave pública es efímera: solo hace falta para poder armar la aplicación."""
    public_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    app = create_app(Settings(jwt_public_key=public_pem), httpx.Client())
    return app.openapi()


def render(spec: dict) -> str:
    return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=120)


if __name__ == "__main__":
    OPENAPI_PATH.write_text(render(build_spec()), encoding="utf-8")
    print(f"Escrito {OPENAPI_PATH}")
