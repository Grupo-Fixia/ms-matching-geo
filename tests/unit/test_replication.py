"""Réplica local de técnicos y revocación sin ms-users (GC-547): las mismas reglas que aplicaba ms-users al buscar, y
la lista de revocados que solo decide si está al día."""
import json
from datetime import datetime, timezone

import pytest

from src.app.application.errors import InvalidCursor, RevocationCheckFailed, UpstreamUnavailable
from src.app.domain.models import Category
from src.app.infrastructure.replication import ReplicatedTechnicianDirectory, TechnicianReplica
from src.app.infrastructure.revocation import ReplicatedRevocationChecker, RevocationList, apply_message

ANA = "00000000-0000-4000-8000-00000000000a"
BETO = "00000000-0000-4000-8000-00000000000b"
CARLA = "00000000-0000-4000-8000-00000000000c"
# Martes 2026-11-24 a las 10:00 en Bogotá.
TUESDAY_10AM = datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)
NOW = 1_800_000_000.0


def state(user_id: str, city: str = "Bogotá", active: bool = True, categories=("PLUMBING",), radius=None,
          verified: bool = True) -> dict:
    coverage = {"city": city}
    if radius is not None:
        coverage.update({"latitude": 4.65, "longitude": -74.05, "radiusKm": radius})
    return {
        "userId": user_id,
        "active": active,
        "displayName": "Técnico",
        "verificationRequirementMet": verified,
        "categories": list(categories),
        "coverage": coverage,
        "availability": [{"dayOfWeek": "TUESDAY", "startTime": "08:00", "endTime": "12:00"}],
    }


def message(user_id: str, sequence: int, data: dict, removed: bool = False) -> str:
    return json.dumps({"eventType": "tecnico.estado", "aggregate": {"type": "TechnicianState", "id": user_id,
                                                                      "sequence": sequence},
                       "removed": removed, "data": data})


@pytest.fixture
def replica() -> TechnicianReplica:
    replica = TechnicianReplica()
    replica.mark_loaded()
    return replica


def test_busca_por_categoria_ciudad_verificacion_y_franja(replica):
    replica.apply_message(message(ANA, 1, state(ANA, radius=5)))
    replica.apply_message(message(BETO, 1, state(BETO, categories=("ELECTRICAL",))))
    replica.apply_message(message(CARLA, 1, state(CARLA, city="Cali")))
    directory = ReplicatedTechnicianDirectory(replica)

    found = directory.search(Category.PLUMBING, "  bogota ", 10, None, TUESDAY_10AM)

    assert [candidate.user_id for candidate in found.items] == [ANA]
    assert found.items[0].circle.radius_km == 5
    assert found.next_cursor is None
    assert directory.search(Category.PLUMBING, "Bogotá", 10, None,
                            datetime(2026, 11, 24, 18, 0, tzinfo=timezone.utc)).items == []


def test_excluye_inactivos_sin_verificacion_exigida_y_eliminados(replica):
    replica.apply_message(message(ANA, 1, state(ANA, active=False)))
    replica.apply_message(message(BETO, 1, state(BETO, verified=False)))
    replica.apply_message(message(CARLA, 1, state(CARLA)))
    replica.apply_message(message(CARLA, 2, {}, removed=True))

    assert ReplicatedTechnicianDirectory(replica).search(Category.PLUMBING, "Bogotá", 10, None).items == []


def test_pagina_con_cursor_y_rechaza_uno_ajeno(replica):
    for user in (ANA, BETO, CARLA):
        replica.apply_message(message(user, 1, state(user)))
    directory = ReplicatedTechnicianDirectory(replica)

    first = directory.search(Category.PLUMBING, "Bogotá", 2, None)
    second = directory.search(Category.PLUMBING, "Bogotá", 2, first.next_cursor)

    assert [c.user_id for c in first.items] == [ANA, BETO]
    assert [c.user_id for c in second.items] == [CARLA]
    assert second.next_cursor is None
    with pytest.raises(InvalidCursor):
        directory.search(Category.PLUMBING, "Bogotá", 2, "no-es-un-cursor")


def test_una_version_atrasada_no_deshace_una_mas_nueva(replica):
    replica.apply_message(message(ANA, 5, state(ANA)))
    replica.apply_message(message(ANA, 4, state(ANA, active=False)))

    assert len(ReplicatedTechnicianDirectory(replica).search(Category.PLUMBING, "Bogotá", 10, None).items) == 1


def test_sin_replica_cargada_responde_no_disponible():
    with pytest.raises(UpstreamUnavailable):
        ReplicatedTechnicianDirectory(TechnicianReplica()).search(Category.PLUMBING, "Bogotá", 10, None)


def test_un_mensaje_invalido_se_rechaza_y_otros_tipos_se_ignoran(replica):
    replica.apply_message(json.dumps({"eventType": "empresa.estado"}))
    with pytest.raises(ValueError):
        replica.apply_message(b"{no es json")
    with pytest.raises(ValueError):
        replica.apply_message(json.dumps({"eventType": "tecnico.estado", "aggregate": {"id": ANA}, "data": {}}))


# ---------- Revocación ----------


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> float:
        return self.now


def test_la_lista_decide_sin_ms_users_y_falla_cerrado_si_se_atrasa():
    clock = Clock()
    revocations = RevocationList(max_staleness=5.0, clock=clock)
    checker = ReplicatedRevocationChecker(revocations)

    with pytest.raises(RevocationCheckFailed):
        checker.is_revoked("jti-1")

    revocations.mark_caught_up()
    revocations.add("jti-revocado", NOW + 600)
    assert checker.is_revoked("jti-1") is False
    assert checker.is_revoked("jti-revocado") is True

    clock.now = NOW + 6
    with pytest.raises(RevocationCheckFailed):
        checker.is_revoked("jti-1")
    assert checker.is_revoked("jti-revocado") is True


def test_sesion_revocada_llega_a_la_lista_con_cualquier_precision_de_fecha():
    for expires in ("2999-01-01T00:00:00Z", "2999-01-01T00:00:00.123456789Z"):
        revocations = RevocationList()
        apply_message(revocations, json.dumps({"eventType": "sesion.revocada",
                                               "data": {"jti": "a", "expiresAt": expires}}))
        assert revocations.contains("a") is True
    with pytest.raises(ValueError):
        apply_message(RevocationList(), json.dumps({"eventType": "sesion.revocada", "data": {"jti": "a",
                                                                                             "expiresAt": "mañana"}}))
