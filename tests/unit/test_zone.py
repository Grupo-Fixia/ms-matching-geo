"""Regla de zona. Los casos son los de `CoverageZoneTest` de ms-users, la regla de referencia: si una cambia, la otra
debe cambiar con ella."""
import pytest

from src.app.domain.models import ZoneCircle
from src.app.domain.zone import circle_covers, haversine_km, normalize_city, same_city

# Centro de Bogotá (Plaza de Bolívar) y un punto en Chapinero, a unos 4 km.
CENTER = (4.598, -74.076)
CHAPINERO = (4.63, -74.06)


def test_la_ciudad_coincide_sin_importar_mayusculas_tildes_ni_espacios():
    assert same_city("Bogotá", "bogota")
    assert same_city("  BOGOTÁ ", "Bogotá")
    assert same_city("Medellín", "MEDELLIN")
    assert not same_city("Bogotá", "Medellín")


@pytest.mark.parametrize("value,expected", [(" Bogotá ", "bogota"), ("Ñandú", "nandu"), ("CALI", "cali")])
def test_normalize_city(value, expected):
    assert normalize_city(value) == expected


def test_la_distancia_entre_el_centro_y_chapinero_es_de_unos_4_km():
    assert haversine_km(*CENTER, *CHAPINERO) == pytest.approx(4.0, abs=0.5)
    assert haversine_km(*CENTER, *CENTER) == 0


def test_con_circulo_exige_que_el_punto_caiga_dentro_del_radio():
    assert circle_covers(ZoneCircle(*CENTER, 5), *CHAPINERO)
    assert not circle_covers(ZoneCircle(*CENTER, 2), *CHAPINERO)


def test_sin_circulo_basta_la_ciudad():
    assert circle_covers(None, *CHAPINERO)


def test_si_la_solicitud_no_trae_las_dos_coordenadas_basta_la_ciudad():
    two_km = ZoneCircle(*CENTER, 2)
    assert circle_covers(two_km, None, None)
    assert circle_covers(two_km, CHAPINERO[0], None)
    assert circle_covers(two_km, None, CHAPINERO[1])


def test_un_radio_menor_que_la_distancia_deja_el_punto_fuera():
    distance = haversine_km(*CENTER, *CHAPINERO)
    assert circle_covers(ZoneCircle(*CENTER, 100), *CHAPINERO)
    assert not circle_covers(ZoneCircle(CENTER[0], CENTER[1], int(distance)), *CHAPINERO)
