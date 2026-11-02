"""Caso de uso de matching con un directorio falso: filtro por círculo, paginación y presupuesto de llamadas."""
import dataclasses

import pytest

from src.app.application.errors import UpstreamUnavailable
from src.app.application.matching_service import MAX_UPSTREAM_CALLS, MatchingService
from src.app.domain.models import Candidate, CandidatePage, Category, Match, MatchQuery, ZoneCircle

CENTER = (4.598, -74.076)
CHAPINERO = (4.63, -74.06)


def candidate(user_id: str, circle: ZoneCircle | None = None, city: str = "Bogotá") -> Candidate:
    return Candidate(user_id, "Carlos G.", ("PLUMBING",), city, circle)


def query(limit: int = 20, cursor: str | None = None, point: tuple | None = CHAPINERO) -> MatchQuery:
    latitude, longitude = point if point else (None, None)
    return MatchQuery(Category.PLUMBING, "Bogotá", latitude, longitude, limit, cursor)


class FakeDirectory:
    """Devuelve las páginas en orden y anota con qué `limit` y `cursor` se le pidió cada una."""

    def __init__(self, *pages: CandidatePage) -> None:
        self._pages = list(pages)
        self.calls: list[tuple[int, str | None]] = []

    def search(self, category, city, limit, cursor):
        self.calls.append((limit, cursor))
        return self._pages.pop(0)


def ids(page) -> list[str]:
    return [match.user_id for match in page.items]


def test_descarta_a_los_tecnicos_cuyo_circulo_no_cubre_el_punto():
    inside = candidate("dentro", ZoneCircle(*CENTER, 5))
    outside = candidate("fuera", ZoneCircle(*CENTER, 2))
    city_only = candidate("ciudad")
    service = MatchingService(FakeDirectory(CandidatePage([inside, outside, city_only], None)))

    result = service.find(query())

    assert ids(result) == ["dentro", "ciudad"]
    assert result.next_cursor is None


def test_sin_punto_en_la_solicitud_basta_la_ciudad():
    service = MatchingService(
        FakeDirectory(CandidatePage([candidate("a", ZoneCircle(*CENTER, 1)), candidate("b")], None))
    )

    assert ids(service.find(query(point=None))) == ["a", "b"]


def test_descarta_lo_que_ms_users_devuelva_de_otra_ciudad():
    service = MatchingService(FakeDirectory(CandidatePage([candidate("a"), candidate("b", city="Medellín")], None)))

    assert ids(service.find(query())) == ["a"]


def test_el_resultado_no_lleva_el_circulo():
    service = MatchingService(FakeDirectory(CandidatePage([candidate("a", ZoneCircle(*CENTER, 5))], None)))

    match = service.find(query()).items[0]

    assert isinstance(match, Match)
    assert {f.name for f in dataclasses.fields(match)} == {"user_id", "display_name", "categories", "city"}


def test_reune_el_limite_en_varias_llamadas_pidiendo_solo_lo_que_falta():
    excluded = candidate("excluido", ZoneCircle(*CENTER, 2))
    directory = FakeDirectory(
        CandidatePage([excluded], "c1"),
        CandidatePage([candidate("uno")], "c2"),
        CandidatePage([candidate("dos")], "c3"),
    )

    result = MatchingService(directory).find(query(limit=2))

    assert ids(result) == ["uno", "dos"]
    assert result.next_cursor == "c3"
    assert directory.calls == [(2, None), (2, "c1"), (1, "c2")]


def test_desde_el_cursor_recibido():
    directory = FakeDirectory(CandidatePage([], None))

    MatchingService(directory).find(query(cursor="desde-aqui"))

    assert directory.calls == [(20, "desde-aqui")]


def test_se_detiene_al_agotar_el_presupuesto_y_devuelve_el_cursor_alcanzado():
    excluded = [candidate(f"x{n}", ZoneCircle(*CENTER, 1)) for n in range(3)]
    directory = FakeDirectory(*[CandidatePage([e], f"c{n}") for n, e in enumerate(excluded)], CandidatePage([], None))

    result = MatchingService(directory).find(query())

    assert result.items == []
    assert result.next_cursor == f"c{MAX_UPSTREAM_CALLS - 1}"
    assert len(directory.calls) == MAX_UPSTREAM_CALLS


def test_con_menos_llamadas_permitidas_se_detiene_antes():
    directory = FakeDirectory(CandidatePage([], "c0"), CandidatePage([], "c1"))

    result = MatchingService(directory, max_upstream_calls=1).find(query())

    assert result.next_cursor == "c0"
    assert len(directory.calls) == 1


def test_sin_cursor_de_ms_users_no_quedan_tecnicos_por_revisar():
    directory = FakeDirectory(CandidatePage([candidate("a")], None))

    result = MatchingService(directory).find(query(limit=5))

    assert result.next_cursor is None
    assert len(directory.calls) == 1


def test_si_ms_users_devuelve_mas_de_lo_pedido_falla_en_lugar_de_perder_tecnicos():
    directory = FakeDirectory(CandidatePage([candidate("a"), candidate("b")], "c1"))

    with pytest.raises(UpstreamUnavailable):
        MatchingService(directory).find(query(limit=1))
