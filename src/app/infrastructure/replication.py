"""Réplica local del estado de los técnicos que publica ms-users (GC-547, cero dependencias síncronas).

ms-matching-geo ya no llama a `/internal/technicians/search` de ms-users: consume `tecnico.estado` del tópico
`fixia.users.technician-states`, guarda en memoria la última versión de cada técnico y busca ahí, con las mismas reglas
que aplicaba ms-users (categoría, ciudad, verificación exigida y franja del momento esperado). El círculo de la zona,
que revela el domicilio aproximado, se usa para filtrar y nunca sale de este servicio.
"""
import base64
import binascii
import json
import logging
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable
from datetime import datetime, time as clock_time, timedelta, timezone

from src.app.application.errors import InvalidCursor, UpstreamUnavailable
from src.app.domain.models import Candidate, CandidatePage, Category, ZoneCircle

logger = logging.getLogger(__name__)

TECHNICIAN_STATE = "tecnico.estado"
# Colombia no tiene horario de verano: UTC-5 fijo, igual que America/Bogota en ms-users.
COLOMBIA = timezone(timedelta(hours=-5))
DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


def _normalize(city: str) -> str:
    without_accents = "".join(
        char for char in unicodedata.normalize("NFD", city.strip()) if unicodedata.category(char) != "Mn"
    )
    return without_accents.lower()


class TechnicianReplica:
    """Estados de técnicos por id, con la versión de mayor secuencia. Segura entre hilos."""

    def __init__(self) -> None:
        self._states: dict[str, tuple[int, bool, dict]] = {}
        self._lock = threading.Lock()
        self._loaded = False

    def apply_message(self, value: bytes | str | None) -> None:
        """Aplica un mensaje del tópico. Otros tipos se ignoran; uno inválido lanza `ValueError`."""
        if value is None:
            raise ValueError("Mensaje vacío")
        try:
            root = json.loads(value)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("El mensaje no es JSON válido") from error
        if not isinstance(root, dict) or root.get("eventType") != TECHNICIAN_STATE:
            return
        aggregate = root.get("aggregate")
        data = root.get("data")
        if not isinstance(aggregate, dict) or not isinstance(data, dict):
            raise ValueError("Falta aggregate o data")
        key = aggregate.get("id")
        sequence = aggregate.get("sequence")
        if not isinstance(key, str) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("Falta aggregate.id o aggregate.sequence")
        self.apply(key, sequence, bool(root.get("removed", False)), data)

    def apply(self, key: str, sequence: int, removed: bool, data: dict) -> bool:
        """Guarda la versión si es más nueva que la que hay. Devuelve si se aplicó."""
        with self._lock:
            current = self._states.get(key)
            if current is not None and current[0] >= sequence:
                return False
            self._states[key] = (sequence, removed, data)
            return True

    def mark_loaded(self) -> None:
        """El consumidor confirmó con el broker que leyó todo lo publicado: ya se puede buscar."""
        self._loaded = True

    def is_loaded(self) -> bool:
        return self._loaded

    def active_technicians(self) -> list[dict]:
        with self._lock:
            states = [data for _, removed, data in self._states.values() if not removed and data.get("active")]
        return sorted(states, key=lambda state: state["userId"])


def _available(state: dict, expected_at: datetime) -> bool:
    local = expected_at.astimezone(COLOMBIA)
    day = DAYS[local.weekday()]
    moment = local.time().replace(tzinfo=None)
    for slot in state.get("availability") or []:
        if slot.get("dayOfWeek") != day:
            continue
        start = clock_time.fromisoformat(slot["startTime"])
        end = clock_time.fromisoformat(slot["endTime"])
        if start <= moment < end:
            return True
    return False


def _encode(user_id: str) -> str:
    return base64.urlsafe_b64encode(user_id.encode()).decode().rstrip("=")


def _decode(cursor: str) -> str:
    try:
        decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        uuid.UUID(decoded)
        return decoded
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise InvalidCursor() from error


class ReplicatedTechnicianDirectory:
    """Implementa el puerto `TechnicianDirectory` con la réplica local, sin llamar a ms-users. Mientras la réplica no
    haya cargado responde `UpstreamUnavailable` (502), igual que cuando ms-users no respondía."""

    def __init__(self, replica: TechnicianReplica) -> None:
        self._replica = replica

    def search(
        self, category: Category, city: str, limit: int, cursor: str | None, expected_at: datetime | None = None
    ) -> CandidatePage:
        after = _decode(cursor) if cursor is not None else None
        if not self._replica.is_loaded():
            raise UpstreamUnavailable("La réplica de técnicos aún no está cargada")
        wanted_city = _normalize(city)
        items: list[Candidate] = []
        last: str | None = None
        more = False
        for state in self._replica.active_technicians():
            if after is not None and state["userId"] <= after:
                continue
            coverage = state.get("coverage") or {}
            if (
                not state.get("verificationRequirementMet")
                or category.value not in (state.get("categories") or [])
                or not coverage.get("city")
                or _normalize(coverage["city"]) != wanted_city
                or (expected_at is not None and not _available(state, expected_at))
            ):
                continue
            if len(items) == limit:
                more = True
                break
            circle = (
                ZoneCircle(coverage["latitude"], coverage["longitude"], coverage["radiusKm"])
                if coverage.get("radiusKm") is not None
                else None
            )
            items.append(
                Candidate(
                    user_id=state["userId"],
                    display_name=state.get("displayName") or "",
                    categories=tuple(state.get("categories") or []),
                    city=coverage["city"],
                    circle=circle,
                )
            )
            last = state["userId"]
        return CandidatePage(items=items, next_cursor=_encode(last) if more and last else None)


class TopicConsumer:
    """Hilo que lee un tópico completo con un grupo único y sin confirmar offsets: cada instancia lo lee todo. Al
    arrancar empieza en `start_seconds_ago` (o desde el principio si es None). Tras cada intervalo sin mensajes pregunta
    al broker el último offset de cada partición y, solo si la posición lo alcanzó, llama a `on_caught_up`. Si el
    broker no responde no lo llama."""

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_prefix: str,
        on_message: Callable[[bytes | None], None],
        on_caught_up: Callable[[], None],
        start_seconds_ago: float | None = None,
        idle_interval: float = 1.0,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._group_id = f"{group_prefix}-{uuid.uuid4()}"
        self._on_message = on_message
        self._on_caught_up = on_caught_up
        self._start_seconds_ago = start_seconds_ago
        self._idle_interval = idle_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"consumer-{self._topic}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        from confluent_kafka import OFFSET_BEGINNING, OFFSET_END, Consumer, KafkaException

        consumer = Consumer({
            "bootstrap.servers": self._bootstrap_servers,
            "group.id": self._group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest" if self._start_seconds_ago is None else "latest",
        })

        def on_assign(kafka_consumer, partitions):
            if self._start_seconds_ago is None:
                for partition in partitions:
                    partition.offset = OFFSET_BEGINNING
                kafka_consumer.assign(partitions)
                return
            since_ms = int((time.time() - self._start_seconds_ago) * 1000)
            for partition in partitions:
                partition.offset = since_ms
            try:
                found = kafka_consumer.offsets_for_times(partitions, timeout=5)
                for partition in found:
                    if partition.offset < 0:
                        partition.offset = OFFSET_END
            except KafkaException:
                # Sin respuesta del broker: se relee todo lo retenido, que también cubre lo pedido.
                found = partitions
                for partition in found:
                    partition.offset = OFFSET_BEGINNING
            kafka_consumer.assign(found)

        consumer.subscribe([self._topic], on_assign=on_assign)
        logger.info("Consumidor suscrito a %s", self._topic)
        try:
            while not self._stop.is_set():
                message = consumer.poll(self._idle_interval)
                if message is None:
                    self._check_caught_up(consumer, KafkaException)
                    continue
                if message.error():
                    logger.warning("No se pudo leer de %s: %s", self._topic, message.error())
                    continue
                try:
                    self._on_message(message.value())
                except ValueError as error:
                    # Solo dónde estaba el mensaje: nunca su contenido.
                    logger.error("Mensaje inválido en %s-%s@%s, se salta (%s)", message.topic(),
                                 message.partition(), message.offset(), error)
        finally:
            consumer.close()

    def _check_caught_up(self, consumer, kafka_exception) -> None:
        partitions = consumer.assignment()
        if not partitions:
            return
        try:
            positions = consumer.position(partitions)
            for partition in positions:
                _, high = consumer.get_watermark_offsets(partition, timeout=0.5)
                if (partition.offset < 0 and high != 0) or (partition.offset >= 0 and partition.offset < high):
                    return
        except kafka_exception:
            return
        self._on_caught_up()
