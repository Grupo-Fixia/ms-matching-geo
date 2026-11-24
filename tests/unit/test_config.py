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
    assert settings.internal_api_key == "k"
    # GC-547: los consumidores de Kafka se encienden por defecto fuera de las pruebas.
    assert settings.technicians_consumer_enabled is True
    assert settings.technicians_topic == "fixia.users.technician-states"
    assert settings.revocations_consumer_enabled is True
    assert settings.revocations_max_staleness == 5.0


def test_la_clave_con_saltos_de_linea_escritos_como_texto_se_restaura():
    settings = Settings.from_env({"JWT_PUBLIC_KEY": PEM.replace("\n", "\\n")})

    assert settings.jwt_public_key == PEM


def test_toma_los_valores_del_entorno():
    settings = Settings.from_env(
        {
            "JWT_PUBLIC_KEY": PEM,
            "JWT_ISSUER": "emisor",
            "JWT_AUDIENCE": "audiencia",
            "KAFKA_HOST": "kafka:9092",
            "FIXIA_TECHNICIANS_CONSUMER_ENABLED": "false",
            "FIXIA_REVOCATIONS_MAX_STALENESS": "500ms",
            "FIXIA_REVOCATIONS_LOOKBACK": "3s",
        }
    )

    assert (settings.jwt_issuer, settings.jwt_audience) == ("emisor", "audiencia")
    assert settings.kafka_bootstrap_servers == "kafka:9092"
    assert settings.technicians_consumer_enabled is False
    assert settings.revocations_max_staleness == 0.5
    assert settings.revocations_lookback == 3.0


def test_duraciones_en_segundos_sin_sufijo():
    settings = Settings.from_env({"JWT_PUBLIC_KEY": PEM, "FIXIA_REVOCATIONS_MAX_STALENESS": "1.5"})

    assert settings.revocations_max_staleness == 1.5


def test_una_duracion_invalida_es_un_error_de_configuracion():
    with pytest.raises(ConfigError, match="FIXIA_REVOCATIONS_MAX_STALENESS"):
        Settings.from_env({"JWT_PUBLIC_KEY": PEM, "FIXIA_REVOCATIONS_MAX_STALENESS": "mucho"})


def test_avisa_si_falta_la_clave_interna(caplog):
    with caplog.at_level(logging.WARNING):
        Settings.from_env({"JWT_PUBLIC_KEY": PEM})

    assert "INTERNAL_API_KEY" in caplog.text


def test_el_repr_no_muestra_las_claves():
    text = repr(Settings.from_env({"JWT_PUBLIC_KEY": PEM, "INTERNAL_API_KEY": "secreto"}))

    assert "secreto" not in text
    assert "BEGIN PUBLIC KEY" not in text
