"""Modelo del dominio de matching: qué se busca y qué se devuelve. Sin dependencias de FastAPI ni de HTTP."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Category(str, Enum):
    """Categorías de servicio del catálogo de ms-users (`ServiceCategory`); en la API viaja el nombre."""

    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    MAINTENANCE = "MAINTENANCE"
    LOCKSMITHING = "LOCKSMITHING"
    PAINTING = "PAINTING"
    CARPENTRY = "CARPENTRY"


@dataclass(frozen=True)
class ZoneCircle:
    """Centro y radio de la zona de un técnico. Revela su domicilio aproximado: nunca sale de este servicio."""

    latitude: float
    longitude: float
    radius_km: int


@dataclass(frozen=True)
class Candidate:
    """Un técnico que ms-users considera compatible por categoría y ciudad, con el círculo de su zona si lo definió."""

    user_id: str
    display_name: str
    categories: tuple[str, ...]
    city: str
    circle: ZoneCircle | None


@dataclass(frozen=True)
class CandidatePage:
    """Una página de candidatos de ms-users. Puede venir corta, o vacía, con cursor no nulo."""

    items: list[Candidate]
    next_cursor: str | None


@dataclass(frozen=True)
class MatchQuery:
    """Lo que se busca: categoría y ciudad, y opcionalmente el punto aproximado de la solicitud y su momento esperado
    (con zona horaria: se normaliza a UTC antes de llegar aquí)."""

    category: Category
    city: str
    latitude: float | None
    longitude: float | None
    limit: int
    cursor: str | None
    expected_at: datetime | None = None


@dataclass(frozen=True)
class Match:
    """Un técnico compatible tal como se devuelve. No lleva el círculo, distancia ni datos de contacto: así no pueden
    filtrarse por construcción."""

    user_id: str
    display_name: str
    categories: tuple[str, ...]
    city: str


@dataclass(frozen=True)
class MatchPage:
    items: list[Match]
    next_cursor: str | None
