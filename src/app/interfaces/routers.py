"""Rutas HTTP. La pública sale por Traefik bajo `/api/geo` (sin quitar el prefijo, ADR-036); la interna va bajo
`/internal/**`, que el gateway no publica."""
from fastapi import APIRouter, Depends

from src.app.interfaces.schemas import MatchRequest, MatchResponse, Problem
from src.app.interfaces.security import Container, get_container, require_client, require_internal

PUBLIC_PATH = "/api/geo/matching/technicians"
INTERNAL_PATH = "/internal/matching/technicians"

_ERRORS = {
    400: {"model": Problem, "description": "Datos inválidos o cursor no válido."},
    401: {"model": Problem, "description": "Credencial ausente o no válida (siempre la misma respuesta)."},
    502: {"model": Problem, "description": "No se pudo consultar a ms-users."},
}
_FORBIDDEN = {403: {"model": Problem, "description": "El rol no permite la acción."}}

_DESCRIPTION = """Técnicos que ofrecen la categoría y atienden la ciudad indicadas, en orden estable y sin ranking.
Si la consulta trae `latitude` y `longitude` (juntas), se descartan los técnicos cuyo círculo de zona no cubre ese punto;
si el técnico no definió círculo, o no se envía el punto, basta la ciudad.

**Paginación por cursor.** Una consulta revisa como máximo 1500 técnicos. Una página puede venir corta, o vacía, con
`nextCursor` no nulo: hay que seguir pidiendo hasta que sea nulo.

No devuelve distancia, centro ni radio de la zona, ni datos de contacto. Si ms-users no responde, devuelve 502 y no una
lista vacía."""

router = APIRouter()


@router.post(
    PUBLIC_PATH,
    response_model=MatchResponse,
    summary="Buscar técnicos por especialidad y zona (cliente)",
    description=_DESCRIPTION + "\n\nSolo con rol `CLIENT`. Revisa la revocación del token en ms-users en cada petición.",
    responses={**_ERRORS, **_FORBIDDEN},
    tags=["matching"],
)
def match_public(
    request: MatchRequest,
    container: Container = Depends(get_container),
    _claims=Depends(require_client),
) -> MatchResponse:
    return MatchResponse.from_page(container.matching_service.find(request.to_query()))


@router.post(
    INTERNAL_PATH,
    response_model=MatchResponse,
    summary="Buscar técnicos por especialidad y zona (interna)",
    description=_DESCRIPTION
    + "\n\nRuta interna para otros microservicios (ms-services); Traefik no la publica. Protegida por la cabecera "
    "`X-Internal-Api-Key`.",
    responses=_ERRORS,
    tags=["matching"],
)
def match_internal(
    request: MatchRequest,
    container: Container = Depends(get_container),
    _auth=Depends(require_internal),
) -> MatchResponse:
    return MatchResponse.from_page(container.matching_service.find(request.to_query()))
