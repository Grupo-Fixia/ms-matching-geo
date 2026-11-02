"""Caso de uso: técnicos compatibles con una categoría y una zona."""
from src.app.application.errors import UpstreamUnavailable
from src.app.application.ports import TechnicianDirectory
from src.app.domain.models import Match, MatchPage, MatchQuery
from src.app.domain.zone import circle_covers, same_city

# Llamadas a ms-users por consulta. Cada una revisa hasta 500 técnicos allí, así que una consulta revisa como máximo
# 1500: acota el costo de una consulta pero no oculta a nadie, porque lo que queda se pide con el cursor (ADR-044).
MAX_UPSTREAM_CALLS = 3


class MatchingService:
    """ms-users filtra por categoría y ciudad; aquí se aplica el círculo de la zona con el punto de la solicitud.

    Una página puede venir corta, o vacía, con `next_cursor` no nulo: significa que quedan técnicos por revisar y hay
    que seguir pidiendo hasta que sea nulo. Del resultado se descarta el círculo: el domicilio aproximado del técnico no
    sale de este servicio.
    """

    def __init__(self, directory: TechnicianDirectory, max_upstream_calls: int = MAX_UPSTREAM_CALLS) -> None:
        self._directory = directory
        self._max_upstream_calls = max_upstream_calls

    def find(self, query: MatchQuery) -> MatchPage:
        matches: list[Match] = []
        cursor = query.cursor
        calls = 0
        while True:
            remaining = query.limit - len(matches)
            page = self._directory.search(query.category, query.city, remaining, cursor)
            calls += 1
            if len(page.items) > remaining:
                # Con más de lo pedido, el cursor quedaría más allá de técnicos que no se devolvieron.
                raise UpstreamUnavailable("ms-users devolvió más técnicos de los pedidos")
            for candidate in page.items:
                # La ciudad ya la filtró ms-users; se vuelve a comprobar para no depender de que lo haga bien.
                if same_city(candidate.city, query.city) and circle_covers(
                    candidate.circle, query.latitude, query.longitude
                ):
                    matches.append(
                        Match(candidate.user_id, candidate.display_name, candidate.categories, candidate.city)
                    )
            cursor = page.next_cursor
            if cursor is None or len(matches) >= query.limit or calls >= self._max_upstream_calls:
                return MatchPage(matches, cursor)
