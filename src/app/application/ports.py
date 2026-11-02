"""Puertos: lo que el caso de uso necesita del exterior, sin saber cómo se obtiene."""
from typing import Protocol

from src.app.domain.models import CandidatePage, Category


class TechnicianDirectory(Protocol):
    """Técnicos que ofrecen una categoría y atienden una ciudad. Los datos viven en ms-users (Database per Service)."""

    def search(self, category: Category, city: str, limit: int, cursor: str | None) -> CandidatePage:
        """Una página de hasta `limit` candidatos a partir de `cursor` (None para empezar).

        Raises:
            InvalidCursor: el cursor no es válido.
            UpstreamUnavailable: no se pudo obtener una respuesta válida.
        """
        ...
