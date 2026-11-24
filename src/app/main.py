from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from src.app.application.matching_service import MatchingService
from src.app.application.ports import TechnicianDirectory
from src.app.config import Settings
from src.app.infrastructure.jwt_validator import JwtValidator
from src.app.infrastructure.replication import ReplicatedTechnicianDirectory, TechnicianReplica, TopicConsumer
from src.app.infrastructure.revocation import ReplicatedRevocationChecker, RevocationList, apply_message
from src.app.interfaces.errors import register_error_handlers
from src.app.interfaces.metrics import register_prometheus_metrics
from src.app.interfaces.routers import router
from src.app.interfaces.security import Container, RevocationChecker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    directory: TechnicianDirectory | None = None,
    revocation_checker: RevocationChecker | None = None,
) -> FastAPI:
    """Arma la aplicación. Uvicorn la invoca como fábrica (`--factory`).

    Desde GC-547 no hay llamadas a ms-users: los técnicos y la revocación de tokens llegan por Kafka a réplicas en
    memoria. Las pruebas pueden pasar su propio directorio y su propio verificador de revocación.
    """
    settings = settings or Settings.from_env()
    consumers: list[TopicConsumer] = []

    if directory is None:
        replica = TechnicianReplica()
        directory = ReplicatedTechnicianDirectory(replica)
        if settings.technicians_consumer_enabled:
            consumers.append(TopicConsumer(settings.kafka_bootstrap_servers, settings.technicians_topic,
                                           f"{settings.group_prefix}-technicians", replica.apply_message,
                                           replica.mark_loaded))

    if revocation_checker is None:
        revocation_list = RevocationList(max_staleness=settings.revocations_max_staleness)
        revocation_checker = ReplicatedRevocationChecker(revocation_list)
        if settings.revocations_consumer_enabled:
            consumers.append(TopicConsumer(settings.kafka_bootstrap_servers, settings.revocations_topic,
                                           f"{settings.group_prefix}-revocations",
                                           lambda value: apply_message(revocation_list, value),
                                           revocation_list.mark_caught_up,
                                           start_seconds_ago=settings.revocations_lookback))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for consumer in consumers:
            consumer.start()
        logger.info("Servicio ms-matching-geo inicializado correctamente.")
        yield
        for consumer in consumers:
            consumer.stop()
        logger.info("Servicio ms-matching-geo detenido.")

    app = FastAPI(
        title="Geo Matching Service",
        description="Técnicos compatibles con una categoría y una zona de atención, con la réplica del estado que "
        "publica ms-users.",
        lifespan=lifespan,
    )
    app.state.container = Container(
        matching_service=MatchingService(directory),
        jwt_validator=JwtValidator(settings.jwt_public_key, settings.jwt_issuer, settings.jwt_audience),
        revocation_client=revocation_checker,
        internal_api_key=settings.internal_api_key,
    )
    register_error_handlers(app)
    register_prometheus_metrics(app)
    app.include_router(router)

    @app.get("/health", tags=["health"])
    def health():
        return {
            "service": "ms-matching-geo",
            "status": "UP",
        }

    return app
