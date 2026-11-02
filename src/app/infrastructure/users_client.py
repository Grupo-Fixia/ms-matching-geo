"""Cliente de ms-users para la búsqueda de técnicos: `POST /internal/technicians/search`, ruta interna que protege la
clave compartida `X-Internal-Api-Key` (ADR-040). Los datos del técnico viven en la base de ms-users (ADR-015/022)."""
import logging
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, ValidationError

from src.app.application.errors import InvalidCursor, UpstreamUnavailable
from src.app.domain.models import Candidate, CandidatePage, Category, ZoneCircle

API_KEY_HEADER = "X-Internal-Api-Key"
SEARCH_PATH = "/internal/technicians/search"

logger = logging.getLogger(__name__)


class _Circle(BaseModel):
    latitude: float
    longitude: float
    radiusKm: int


class _Item(BaseModel):
    userId: str
    displayName: str
    categories: list[str]
    city: str
    circle: _Circle | None = None


class _Page(BaseModel):
    items: list[_Item]
    nextCursor: str | None = None


class UsersTechnicianDirectory:
    """Implementa el puerto `TechnicianDirectory` llamando a ms-users. El `httpx.Client` ya trae la URL base y los
    tiempos de espera (cortos: la llamada va en el camino de cada consulta)."""

    def __init__(self, client: httpx.Client, api_key: str) -> None:
        self._client = client
        self._api_key = api_key

    def search(
        self, category: Category, city: str, limit: int, cursor: str | None, expected_at: datetime | None = None
    ) -> CandidatePage:
        body: dict[str, object] = {"category": category.value, "city": city, "limit": limit}
        if cursor is not None:
            body["cursor"] = cursor
        if expected_at is not None:
            # Siempre en UTC y terminado en "Z": el formato que ms-users (Instant) parsea sin ambigüedad.
            body["expectedAt"] = expected_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            response = self._client.post(SEARCH_PATH, json=body, headers={API_KEY_HEADER: self._api_key})
        except httpx.HTTPError as error:
            logger.warning("ms-users no respondió a la búsqueda de técnicos (%s)", type(error).__name__)
            raise UpstreamUnavailable("ms-users no respondió") from error

        # Con la consulta ya validada aquí, un 400 solo puede venir de un cursor que ms-users no emitió.
        if response.status_code == 400 and cursor is not None:
            raise InvalidCursor()
        if response.status_code != 200:
            logger.warning("ms-users respondió %s a la búsqueda de técnicos", response.status_code)
            raise UpstreamUnavailable(f"ms-users respondió {response.status_code}")

        try:
            page = _Page.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise UpstreamUnavailable("ms-users respondió con un cuerpo inválido") from error

        return CandidatePage(
            items=[
                Candidate(
                    user_id=item.userId,
                    display_name=item.displayName,
                    categories=tuple(item.categories),
                    city=item.city,
                    circle=ZoneCircle(item.circle.latitude, item.circle.longitude, item.circle.radiusKm)
                    if item.circle
                    else None,
                )
                for item in page.items
            ],
            next_cursor=page.nextCursor,
        )
