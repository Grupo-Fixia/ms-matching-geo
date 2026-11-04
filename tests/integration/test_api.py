"""Las dos rutas de punta a punta dentro del proceso: FastAPI real, ms-users simulado por el transporte de httpx."""
import httpx
import pytest

from tests.conftest import INTERNAL_KEY, build_client, item, make_token, page

PUBLIC = "/api/geo/matching/technicians"
INTERNAL = "/internal/matching/technicians"

# Centro de Bogotá y un punto en Chapinero, a unos 4 km.
CENTER = (4.598, -74.076)
CHAPINERO = (4.63, -74.06)

BODY = {"category": "PLUMBING", "city": "Bogotá"}
INTERNAL_HEADERS = {"X-Internal-Api-Key": INTERNAL_KEY}


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client_token(keys) -> str:
    return make_token(keys[0], roles=("ROLE_CLIENT",))


# ---------- Ruta pública ----------


def test_un_cliente_recibe_los_tecnicos_compatibles(client, users, client_token):
    users.on_search = lambda body: page(
        [item("t1", circle=(*CENTER, 5)), item("t2", name="Diana T.", categories=("PLUMBING", "ELECTRICAL"))]
    )

    response = client.post(PUBLIC, json=BODY, headers=bearer(client_token))

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"userId": "t1", "displayName": "Carlos G.", "categories": ["PLUMBING"], "city": "Bogotá"},
            {"userId": "t2", "displayName": "Diana T.", "categories": ["PLUMBING", "ELECTRICAL"], "city": "Bogotá"},
        ],
        "nextCursor": None,
    }
    assert users.search_bodies == [{"category": "PLUMBING", "city": "Bogotá", "limit": 20}]


def test_aplica_el_circulo_con_el_punto_de_la_solicitud(client, users, client_token):
    users.on_search = lambda body: page(
        [item("dentro", circle=(*CENTER, 5)), item("fuera", circle=(*CENTER, 2)), item("ciudad")]
    )

    response = client.post(
        PUBLIC, json={**BODY, "latitude": CHAPINERO[0], "longitude": CHAPINERO[1]}, headers=bearer(client_token)
    )

    assert [match["userId"] for match in response.json()["items"]] == ["dentro", "ciudad"]


def test_la_respuesta_nunca_revela_el_circulo_ni_distancias(client, users, client_token):
    users.on_search = lambda body: page([item("t1", circle=(*CENTER, 5))])

    text = client.post(
        PUBLIC, json={**BODY, "latitude": CHAPINERO[0], "longitude": CHAPINERO[1]}, headers=bearer(client_token)
    ).text.lower()

    for forbidden in ("circle", "radius", "latitude", "longitude", "distance", "4.598", "-74.076"):
        assert forbidden not in text


def test_pasa_el_cursor_y_devuelve_el_siguiente(client, users, client_token):
    users.on_search = lambda body: page([item("t1")], "siguiente") if body.get("cursor") == "actual" else page([])

    response = client.post(PUBLIC, json={**BODY, "limit": 1, "cursor": "actual"}, headers=bearer(client_token))

    assert response.json()["nextCursor"] == "siguiente"
    assert users.search_bodies[0]["cursor"] == "actual"
    assert users.search_bodies[0]["limit"] == 1


def test_consulta_a_ms_users_con_la_clave_interna_y_codifica_el_jti_en_la_ruta(client, users, keys):
    token = make_token(keys[0], jti="a/b..c")

    response = client.post(PUBLIC, json=BODY, headers=bearer(token))

    assert response.status_code == 200
    assert users.revocation_paths == ["/internal/tokens/a%2Fb..c/status"]
    assert set(users.api_keys) == {INTERNAL_KEY}


def _unauthorized_body(response) -> dict:
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["content-type"].startswith("application/problem+json")
    return response.json()


def test_toda_credencial_invalida_da_el_mismo_401(client, users, keys, other_keys):
    users.revoked.add("revocado")
    cases = {
        "sin cabecera": {},
        "esquema Basic": {"Authorization": "Basic abc"},
        "token basura": bearer("no-es-un-jwt"),
        "token vencido": bearer(make_token(keys[0], expires_in=-60)),
        "firma de otra clave": bearer(make_token(other_keys[0])),
        "emisor incorrecto": bearer(make_token(keys[0], issuer="https://otro.example")),
        "audiencia incorrecta": bearer(make_token(keys[0], audience="https://otra.example")),
        "sin jti": bearer(make_token(keys[0], omit=("jti",))),
        "token revocado": bearer(make_token(keys[0], jti="revocado")),
    }

    bodies = {}
    for name, headers in cases.items():
        bodies[name] = _unauthorized_body(client.post(PUBLIC, json=BODY, headers=headers))
        bodies[name].pop("instance")

    assert all(body == next(iter(bodies.values())) for body in bodies.values())
    assert bodies["sin cabecera"]["title"] == "No autenticado"
    assert users.search_bodies == []


@pytest.mark.parametrize(
    "failure",
    [
        lambda: httpx.Response(500),
        lambda: httpx.Response(200, json={"revoked": "no"}),
        lambda: httpx.Response(200, content=b"no es json"),
        lambda: httpx.Response(200, json={}),
    ],
)
def test_si_no_se_puede_comprobar_la_revocacion_el_token_se_rechaza(client, users, client_token, failure):
    users.revocation_error = failure

    _unauthorized_body(client.post(PUBLIC, json=BODY, headers=bearer(client_token)))
    assert users.search_bodies == []


def test_si_ms_users_no_responde_a_la_revocacion_el_token_se_rechaza(keys, client_token):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("sin respuesta", request=request)

    client = build_client(keys[1], down)

    _unauthorized_body(client.post(PUBLIC, json=BODY, headers=bearer(client_token)))


@pytest.mark.parametrize("role", ["ROLE_PROFESSIONAL", "ROLE_COMPANY"])
def test_solo_un_cliente_puede_usar_la_ruta_publica(client, keys, role):
    response = client.post(PUBLIC, json=BODY, headers=bearer(make_token(keys[0], roles=(role,))))

    assert response.status_code == 403
    assert response.json()["title"] == "Acceso denegado"


def test_un_token_revocado_con_rol_incorrecto_sigue_siendo_401(client, users, keys):
    users.revoked.add("r")

    response = client.post(PUBLIC, json=BODY, headers=bearer(make_token(keys[0], roles=("ROLE_PROFESSIONAL",), jti="r")))

    assert response.status_code == 401


def test_la_clave_interna_sola_no_abre_la_ruta_publica(client):
    assert client.post(PUBLIC, json=BODY, headers=INTERNAL_HEADERS).status_code == 401


# ---------- Ruta interna ----------


def test_la_ruta_interna_responde_lo_mismo_con_la_clave(client, users):
    users.on_search = lambda body: page([item("t1", circle=(*CENTER, 5))])

    response = client.post(INTERNAL, json=BODY, headers=INTERNAL_HEADERS)

    assert response.status_code == 200
    assert response.json()["items"] == [
        {"userId": "t1", "displayName": "Carlos G.", "categories": ["PLUMBING"], "city": "Bogotá"}
    ]


@pytest.mark.parametrize("headers", [{}, {"X-Internal-Api-Key": "otra"}, {"X-Internal-Api-Key": ""}])
def test_la_ruta_interna_rechaza_una_clave_ausente_o_incorrecta(client, headers):
    response = client.post(INTERNAL, json=BODY, headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"] == "Se requiere autenticación válida"


def test_un_jwt_no_abre_la_ruta_interna(client, client_token):
    assert client.post(INTERNAL, json=BODY, headers=bearer(client_token)).status_code == 401


def test_sin_clave_interna_configurada_la_ruta_interna_rechaza_todo(keys, users):
    client = build_client(keys[1], users, internal_api_key="")

    assert client.post(INTERNAL, json=BODY, headers={"X-Internal-Api-Key": ""}).status_code == 401
    assert client.post(INTERNAL, json=BODY, headers=INTERNAL_HEADERS).status_code == 401


# ---------- Validación (misma para las dos rutas) ----------


@pytest.mark.parametrize(
    "body,field",
    [
        ({"city": "Bogotá"}, "category"),
        ({"category": "NO_EXISTE", "city": "Bogotá"}, "category"),
        ({"category": "PLUMBING"}, "city"),
        ({"category": "PLUMBING", "city": "   "}, "city"),
        ({"category": "PLUMBING", "city": "x" * 101}, "city"),
        ({**BODY, "limit": 0}, "limit"),
        ({**BODY, "limit": 51}, "limit"),
        ({**BODY, "latitude": 91, "longitude": 0}, "latitude"),
        ({**BODY, "latitude": 0, "longitude": -181}, "longitude"),
        ({**BODY, "latitude": 4.6}, ""),
        ({**BODY, "longitude": -74.0}, ""),
    ],
)
def test_rechaza_una_consulta_invalida_con_400(client, body, field):
    response = client.post(INTERNAL, json=body, headers=INTERNAL_HEADERS)

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    errors = response.json()["errors"]
    assert errors and all({"field", "message"} <= set(error) for error in errors)
    if field:
        assert field in [error["field"] for error in errors]


def test_el_mensaje_de_las_coordenadas_incompletas_esta_en_espanol(client):
    response = client.post(INTERNAL, json={**BODY, "latitude": 4.6}, headers=INTERNAL_HEADERS)

    assert "La latitud y la longitud deben indicarse juntas" in [e["message"] for e in response.json()["errors"]]


def test_un_cuerpo_que_no_es_json_da_400(client):
    response = client.post(INTERNAL, content=b"{no es json", headers={**INTERNAL_HEADERS, "Content-Type": "application/json"})

    assert response.status_code == 400
    assert response.json()["title"] == "Solicitud inválida"


def test_acepta_el_limite_nulo_y_los_extremos(client, users):
    for limit in (None, 1, 50):
        assert client.post(INTERNAL, json={**BODY, "limit": limit}, headers=INTERNAL_HEADERS).status_code == 200
    assert [b["limit"] for b in users.search_bodies] == [20, 1, 50]


def test_la_ciudad_se_envia_sin_espacios_sobrantes(client, users):
    client.post(INTERNAL, json={**BODY, "city": "  Bogotá "}, headers=INTERNAL_HEADERS)

    assert users.search_bodies[0]["city"] == "Bogotá"


# ---------- Disponibilidad: expectedAt (GC-474) ----------


def test_envia_el_momento_esperado_a_ms_users_en_utc_terminado_en_z(client, users, client_token):
    # 09:00 en Bogotá (-05:00) son las 14:00 UTC.
    client.post(PUBLIC, json={**BODY, "expectedAt": "2026-10-19T09:00:00-05:00"}, headers=bearer(client_token))
    client.post(INTERNAL, json={**BODY, "expectedAt": "2026-10-19T14:00:00Z"}, headers=INTERNAL_HEADERS)

    assert [body["expectedAt"] for body in users.search_bodies] == ["2026-10-19T14:00:00Z"] * 2


@pytest.mark.parametrize("body", [BODY, {**BODY, "expectedAt": None}])
def test_sin_momento_esperado_ms_users_no_recibe_el_campo(client, users, body):
    client.post(INTERNAL, json=body, headers=INTERNAL_HEADERS)

    assert users.search_bodies == [{"category": "PLUMBING", "city": "Bogotá", "limit": 20}]


def test_la_disponibilidad_se_evalua_en_ms_users_y_se_refleja_en_el_resultado(client, users, client_token):
    users.on_search = lambda body: (
        page([item("disponible")]) if body.get("expectedAt") == "2026-10-19T14:00:00Z" else page([item("a"), item("b")])
    )

    with_time = client.post(
        PUBLIC, json={**BODY, "expectedAt": "2026-10-19T09:00:00-05:00"}, headers=bearer(client_token)
    ).json()
    without_time = client.post(PUBLIC, json=BODY, headers=bearer(client_token)).json()

    assert [match["userId"] for match in with_time["items"]] == ["disponible"]
    assert [match["userId"] for match in without_time["items"]] == ["a", "b"]


def test_el_momento_esperado_viaja_en_todas_las_llamadas_de_una_consulta_paginada(client, users, client_token):
    excluded = item("fuera-de-zona", circle=(*CENTER, 1))
    pages = iter([page([excluded], "c1"), page([excluded], "c2"), page([item("dentro")], None)])
    users.on_search = lambda body: next(pages)

    response = client.post(
        PUBLIC,
        json={**BODY, "latitude": CHAPINERO[0], "longitude": CHAPINERO[1], "expectedAt": "2026-10-19T14:00:00Z"},
        headers=bearer(client_token),
    )

    assert [match["userId"] for match in response.json()["items"]] == ["dentro"]
    assert [body["expectedAt"] for body in users.search_bodies] == ["2026-10-19T14:00:00Z"] * 3


@pytest.mark.parametrize(
    "value,message",
    [
        ("2026-10-19T09:00:00", "debe incluir zona horaria"),
        ("2026-10-19", "debe incluir zona horaria"),
        ("ayer por la tarde", "no es una fecha y hora ISO-8601 válida"),
        ("2026-13-45T25:61:00Z", "no es una fecha y hora ISO-8601 válida"),
    ],
)
def test_un_momento_esperado_ambiguo_o_invalido_da_400_con_mensaje_en_espanol(client, users, value, message):
    response = client.post(INTERNAL, json={**BODY, "expectedAt": value}, headers=INTERNAL_HEADERS)

    assert response.status_code == 400
    errors = response.json()["errors"]
    assert [error["field"] for error in errors] == ["expectedAt"]
    assert message in errors[0]["message"]
    assert users.search_bodies == []


# ---------- Cursor y fallos de ms-users ----------


def test_un_cursor_que_ms_users_rechaza_da_400(client, users):
    users.on_search = lambda body: httpx.Response(400, json={"detail": "El cursor no es válido"})

    response = client.post(INTERNAL, json={**BODY, "cursor": "falso"}, headers=INTERNAL_HEADERS)

    assert response.status_code == 400
    assert response.json()["detail"] == "El cursor no es válido"


@pytest.mark.parametrize(
    "answer",
    [
        lambda body: httpx.Response(400),  # sin cursor, un 400 de ms-users no es culpa del cliente
        lambda body: httpx.Response(401),
        lambda body: httpx.Response(500),
        lambda body: httpx.Response(200, content=b"no es json"),
        lambda body: httpx.Response(200, json={"items": "no es una lista"}),
        lambda body: httpx.Response(200, json={"items": [{"userId": "t1"}]}),
    ],
)
def test_si_ms_users_falla_o_responde_algo_invalido_da_502_y_no_una_lista_vacia(client, users, answer):
    users.on_search = answer

    response = client.post(INTERNAL, json=BODY, headers=INTERNAL_HEADERS)

    assert response.status_code == 502
    assert response.json()["title"] == "Servicio no disponible"
    assert "items" not in response.json()


def test_si_ms_users_no_responde_da_502(keys):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("tarda demasiado", request=request)

    client = build_client(keys[1], down)

    assert client.post(INTERNAL, json=BODY, headers=INTERNAL_HEADERS).status_code == 502


# ---------- Salud ----------


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"service": "ms-matching-geo", "status": "UP"}

