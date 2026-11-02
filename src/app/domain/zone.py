"""Reglas de zona de atención. Misma semántica que `CoverageZone.covers` de ms-users, que es la regla de referencia:
si una cambia, la otra debe cambiar con ella (las dos se prueban con los mismos casos)."""
import math
import unicodedata

from src.app.domain.models import ZoneCircle

EARTH_RADIUS_KM = 6371.0


def normalize_city(value: str) -> str:
    """Ciudad sin espacios sobrantes, sin tildes y en minúsculas: "  BOGOTÁ " y "bogota" son la misma."""
    decomposed = unicodedata.normalize("NFD", value.strip())
    without_marks = "".join(char for char in decomposed if not unicodedata.category(char).startswith("M"))
    return without_marks.lower()


def same_city(left: str, right: str) -> bool:
    return normalize_city(left) == normalize_city(right)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia sobre la esfera terrestre (fórmula del haversine)."""
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def circle_covers(circle: ZoneCircle | None, latitude: float | None, longitude: float | None) -> bool:
    """Si el punto cae dentro del círculo del técnico. Sin círculo, o sin las dos coordenadas de la solicitud, la
    ciudad basta y el punto se da por cubierto."""
    if circle is None or latitude is None or longitude is None:
        return True
    return haversine_km(circle.latitude, circle.longitude, latitude, longitude) <= circle.radius_km
