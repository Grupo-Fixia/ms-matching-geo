"""Ciclo de vida de la aplicación: arranca, sirve y se detiene sin cerrar el cliente HTTP que le inyectaron."""
import httpx
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.main import create_app
from tests.conftest import USERS_URL


def test_arranca_y_se_detiene_sin_cerrar_un_cliente_inyectado(keys):
    injected = httpx.Client(base_url=USERS_URL)

    with TestClient(create_app(Settings(jwt_public_key=keys[1]), injected)) as client:
        assert client.get("/health").status_code == 200

    assert not injected.is_closed


def test_si_crea_su_propio_cliente_lo_cierra_al_detenerse(keys):
    with TestClient(create_app(Settings(jwt_public_key=keys[1]))) as client:
        assert client.get("/health").status_code == 200
