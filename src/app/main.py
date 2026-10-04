from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Servicio ms-matching-geo inicializado correctamente."
    )
    yield
    logger.info(
        "Servicio ms-matching-geo detenido."
    )


app = FastAPI(
    title="Geo Matching Service",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    return {
        "service": "ms-matching-geo",
        "status": "UP",
    }
