import logging

import pytest

from src.app.config import ConfigError, Settings

PEM = "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----"


def test_sin_clave_publica_no_arranca():
    with pytest.raises(ConfigError, match="JWT_PUBLIC_KEY"):
        Settings.from_env({})
    with pytest.raises(ConfigError):
        Settings.from_env({"JWT_PUBLIC_KEY": "   "})


def test_valores_por_defecto_iguales_a_los_de_ms_users_y_ms_services():
    settings = Settings.from_env({"JWT_PUBLIC_KEY": PEM, "INTERNAL_API_KEY": "k"})

    assert settings.jwt_issuer == "https://auth.fixia.com"
    assert settings.jwt_audience == "https://api.fixia.com"
    assert settings.users_base_url == "http://ms-users:8080"
    assert settings.users_connect_timeout == 1.0
    assert settings.users_read_timeout == 2.0
    assert settings.internal_api_key == "k"


def test_la_clave_con_saltos_de_linea_escritos_como_texto_se_restaura():
    settings = Settings.from_env({"JWT_PUBLIC_KEY": PEM.replace("\n", "\\n")})

    assert settings.jwt_public_key == PEM


def test_toma_los_valores_del_entorno():
    settings = Settings.from_env(
        {
            "JWT_PUBLIC_KEY": PEM,
            "JWT_ISSUER": "emisor",
            "JWT_AUDIENCE": "audiencia",
            "USERS_BASE_URL": "http://localhost:18080",
            "USERS_CONNECT_TIMEOUT": "500ms",
            "USERS_READ_TIMEOUT": "3s",
        }
    )

    assert (settings.jwt_issuer, settings.jwt_audience) == ("emisor", "audiencia")
    assert settings.users_base_url == "http://localhost:18080"
    assert settings.users_connect_timeout == 0.5
    assert settings.users_read_timeout == 3.0


def test_duraciones_en_segundos_sin_sufijo():
    settings = Settings.from_env({"JWT_PUBLIC_KEY": PEM, "USERS_READ_TIMEOUT": "1.5"})

    assert settings.users_read_timeout == 1.5


def test_una_duracion_invalida_es_un_error_de_configuracion():
    with pytest.raises(ConfigError, match="USERS_READ_TIMEOUT"):
        Settings.from_env({"JWT_PUBLIC_KEY": PEM, "USERS_READ_TIMEOUT": "mucho"})


def test_avisa_si_falta_la_clave_interna(caplog):
    with caplog.at_level(logging.WARNING):
        Settings.from_env({"JWT_PUBLIC_KEY": PEM})

    assert "INTERNAL_API_KEY" in caplog.text


def test_el_repr_no_muestra_las_claves():
    text = repr(Settings.from_env({"JWT_PUBLIC_KEY": PEM, "INTERNAL_API_KEY": "secreto"}))

    assert "secreto" not in text
    assert "BEGIN PUBLIC KEY" not in text
