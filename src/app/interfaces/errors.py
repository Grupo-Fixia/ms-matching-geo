"""Respuestas de error en formato RFC 7807 (problem+json), con el mismo estilo que ms-users y ms-services. Los mensajes
nunca incluyen datos sensibles ni detalles internos."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.app.application.errors import AccessDenied, AuthenticationFailed, InvalidCursor, UpstreamUnavailable

PROBLEM_JSON = "application/problem+json"

logger = logging.getLogger(__name__)


def problem(request: Request, status: int, title: str, detail: str, **extra: object) -> JSONResponse:
    body = {"type": "about:blank", "title": title, "status": status, "detail": detail, "instance": request.url.path}
    body.update(extra)
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_JSON)


def _field(location: tuple) -> str:
    # loc = ("body", "campo", ...); el prefijo "body" no le dice nada al cliente.
    return ".".join(str(part) for part in location[1:]) or "body"


def _message(error: dict) -> str:
    if error["type"] == "missing":
        return "El campo es obligatorio"
    message = str(error["msg"])
    # Los mensajes de nuestros validadores llegan como "Value error, <mensaje>".
    return message.removeprefix("Value error, ")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        if any(error["type"] == "json_invalid" for error in exc.errors()):
            return problem(request, 400, "Solicitud inválida", "El cuerpo de la solicitud no es válido")
        errors = sorted(
            ({"field": _field(error["loc"]), "message": _message(error)} for error in exc.errors()),
            key=lambda item: (item["field"], item["message"]),
        )
        return problem(request, 400, "Datos inválidos", "Hay datos que debe corregir", errors=errors)

    @app.exception_handler(InvalidCursor)
    async def invalid_cursor(request: Request, exc: InvalidCursor) -> JSONResponse:
        return problem(request, 400, "Datos inválidos", "El cursor no es válido")

    @app.exception_handler(AuthenticationFailed)
    async def unauthenticated(request: Request, exc: AuthenticationFailed) -> JSONResponse:
        # Siempre igual, sin explicar el motivo, para no dar pistas a quien prueba tokens o claves.
        response = problem(request, 401, "No autenticado", "Se requiere autenticación válida")
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.exception_handler(AccessDenied)
    async def forbidden(request: Request, exc: AccessDenied) -> JSONResponse:
        return problem(request, 403, "Acceso denegado", "No tiene permiso para realizar esta acción")

    @app.exception_handler(UpstreamUnavailable)
    async def upstream_unavailable(request: Request, exc: UpstreamUnavailable) -> JSONResponse:
        return problem(
            request, 502, "Servicio no disponible", "No se pudo consultar a los técnicos. Intente de nuevo más tarde"
        )
