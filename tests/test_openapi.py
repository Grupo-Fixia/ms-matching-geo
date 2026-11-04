"""El contrato publicado en docs/openapi.yaml debe ser el que genera la aplicación."""
import yaml

from scripts.export_openapi import OPENAPI_PATH, build_spec


def test_docs_openapi_coincide_con_la_aplicacion():
    published = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))

    assert published == build_spec(), "docs/openapi.yaml está desactualizado: ejecute `python -m scripts.export_openapi`"


def test_el_contrato_publica_las_dos_rutas_y_no_expone_el_circulo():
    spec = build_spec()

    assert set(spec["paths"]) == {"/api/geo/matching/technicians", "/internal/matching/technicians", "/health"}
    item = spec["components"]["schemas"]["MatchItem"]["properties"]
    assert set(item) == {"userId", "displayName", "categories", "city"}


def test_el_contrato_documenta_el_momento_esperado_opcional_con_zona_horaria():
    request = build_spec()["components"]["schemas"]["MatchRequest"]

    assert "expectedAt" in request["properties"]
    assert "expectedAt" not in request.get("required", [])
