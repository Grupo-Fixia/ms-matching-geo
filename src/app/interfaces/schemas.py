"""Contrato HTTP de la búsqueda de técnicos. Los campos viajan en camelCase, como en ms-users y ms-services."""
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from src.app.domain.models import Category, MatchPage, MatchQuery

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
CITY_MAX_LENGTH = 100


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class MatchRequest(CamelModel):
    """Qué técnicos se buscan: los que ofrecen la categoría y atienden la ciudad. Si trae el punto aproximado de la
    solicitud (`latitude` y `longitude`, juntas), se descartan los técnicos cuyo círculo de zona no lo cubre."""

    category: Category = Field(description="Categoría de servicio.")
    city: str = Field(
        max_length=CITY_MAX_LENGTH,
        description="Ciudad de la zona de atención, sin distinguir mayúsculas ni tildes.",
        examples=["Bogotá"],
    )
    latitude: float | None = Field(default=None, ge=-90, le=90, description="Latitud aproximada de la solicitud.")
    longitude: float | None = Field(default=None, ge=-180, le=180, description="Longitud aproximada de la solicitud.")
    limit: int | None = Field(
        default=None, ge=1, le=MAX_LIMIT, description=f"Resultados por página (por defecto {DEFAULT_LIMIT})."
    )
    cursor: str | None = Field(
        default=None, description="El `nextCursor` de la página anterior; sin él se empieza desde el principio."
    )

    @field_validator("city")
    @classmethod
    def city_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("La ciudad es obligatoria")
        return value.strip()

    @model_validator(mode="after")
    def coordinates_together(self) -> "MatchRequest":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("La latitud y la longitud deben indicarse juntas")
        return self

    def to_query(self) -> MatchQuery:
        return MatchQuery(
            category=self.category,
            city=self.city,
            latitude=self.latitude,
            longitude=self.longitude,
            limit=self.limit if self.limit is not None else DEFAULT_LIMIT,
            cursor=self.cursor or None,
        )


class MatchItem(CamelModel):
    """Un técnico compatible. No incluye distancia, centro ni radio de su zona, ni datos de contacto."""

    user_id: str = Field(examples=["7ec00000-0000-4000-8000-000000000001"])
    display_name: str = Field(description="Nombre e inicial del apellido.", examples=["Carlos G."])
    categories: list[str]
    city: str = Field(description="Ciudad de la zona de atención.")


class MatchResponse(CamelModel):
    items: list[MatchItem]
    next_cursor: str | None = Field(
        description=(
            "Nulo solo cuando no quedan técnicos por revisar. Una página puede venir corta, o vacía, con cursor no "
            "nulo: hay que seguir pidiendo hasta que sea nulo."
        )
    )

    @classmethod
    def from_page(cls, page: MatchPage) -> "MatchResponse":
        return cls(
            items=[
                MatchItem(
                    user_id=match.user_id,
                    display_name=match.display_name,
                    categories=list(match.categories),
                    city=match.city,
                )
                for match in page.items
            ],
            next_cursor=page.next_cursor,
        )


class ProblemError(BaseModel):
    field: str
    message: str


class Problem(BaseModel):
    """Error en formato RFC 7807, igual que ms-users y ms-services."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str
    errors: list[ProblemError] | None = None
