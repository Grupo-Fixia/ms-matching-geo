"""Ciclo de vida de la aplicación: arranca y se detiene. Sin consumidores (apagados por defecto en `Settings`) no
intenta conectarse a Kafka."""
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.main import create_app


def test_arranca_y_se_detiene_sin_consumidores(keys):
    with TestClient(create_app(Settings(jwt_public_key=keys[1]))) as client:
        assert client.get("/health").status_code == 200


def test_sin_replica_cargada_la_busqueda_da_502_y_no_una_lista_vacia(keys):
    settings = Settings(jwt_public_key=keys[1], internal_api_key="k")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/internal/matching/technicians",
            json={"category": "PLUMBING", "city": "Bogotá"},
            headers={"X-Internal-Api-Key": "k"},
        )
        assert response.status_code == 502
