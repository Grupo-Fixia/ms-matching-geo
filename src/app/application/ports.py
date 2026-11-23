"""Puertos: lo que el caso de uso necesita del exterior, sin saber cómo se obtiene."""
from datetime import datetime
from typing import Protocol

from src.app.domain.models import CandidatePage, Category


class TechnicianDirectory(Protocol):
    """Técnicos que ofrecen una categoría y atienden una ciudad. Los datos son de ms-users; desde GC-547 se leen de una
    réplica local alimentada por Kafka."""

    def search(
        self, category: Category, city: str, limit: int, cursor: str | None, expected_at: datetime | None = None
    ) -> CandidatePage:
        """Una página de hasta `limit` candidatos a partir de `cursor` (None para empezar). Con `expected_at` solo
        entran los técnicos con una franja de disponibilidad que incluya ese instante.

        Raises:
            InvalidCursor: el cursor no es válido.
            UpstreamUnavailable: no se pudo obtener una respuesta válida.
        """
        ...
