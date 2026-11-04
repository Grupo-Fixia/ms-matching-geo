from contextlib import asynccontextmanager
import logging

import httpx
from fastapi import FastAPI

from src.app.application.matching_service import MatchingService
from src.app.config import Settings
from src.app.infrastructure.jwt_validator import JwtValidator
from src.app.infrastructure.token_revocation import TokenRevocationClient
from src.app.infrastructure.users_client import UsersTechnicianDirectory
from src.app.interfaces.errors import register_error_handlers
from src.app.interfaces.routers import router
from src.app.interfaces.security import Container

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, http_client: httpx.Client | None = None) -> FastAPI:
    """Arma la aplicación. Uvicorn la invoca como fábrica (`--factory`); las pruebas pasan su propia configuración y un
    `httpx.Client` con transporte simulado en lugar de ms-users."""
    settings = settings or Settings.from_env()
    owns_client = http_client is None
    client = http_client or httpx.Client(
        base_url=settings.users_base_url,
        timeout=httpx.Timeout(settings.users_read_timeout, connect=settings.users_connect_timeout),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Servicio ms-matching-geo inicializado correctamente.")
        yield
        if owns_client:
            client.close()
        logger.info("Servicio ms-matching-geo detenido.")

    app = FastAPI(
        title="Geo Matching Service",
        description="Técnicos compatibles con una categoría y una zona de atención, con los datos de ms-users.",
        lifespan=lifespan,
    )
    app.state.container = Container(
        matching_service=MatchingService(UsersTechnicianDirectory(client, settings.internal_api_key)),
        jwt_validator=JwtValidator(settings.jwt_public_key, settings.jwt_issuer, settings.jwt_audience),
        revocation_client=TokenRevocationClient(client, settings.internal_api_key),
        internal_api_key=settings.internal_api_key,
    )
    register_error_handlers(app)
    app.include_router(router)

    @app.get("/health", tags=["health"])
    def health():
        return {
            "service": "ms-matching-geo",
            "status": "UP",
        }

    return app
