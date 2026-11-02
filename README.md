# ms-matching-geo

Microservicio de **Matching Geo** de Fixia (Python 3.12 + FastAPI). Dado una categoría de servicio y una zona, devuelve los
técnicos compatibles con los datos reales de la plataforma: consulta a `ms-users` (dueño de los datos del técnico,
ADR-015/022) y aplica el círculo de la zona de atención de cada técnico.

## Alcance de esta versión

- Filtra por **especialidad** (categoría) y **zona de atención** (ciudad y, si el técnico la definió, círculo de centro y radio).
- **Fuera de alcance:** disponibilidad, verificación, ranking por distancia o reputación, PostGIS y eventos. La
  disponibilidad y la verificación siguen evaluándose en `ms-users` con la elegibilidad
  (`POST /internal/technicians/{userId}/eligibility`, ADR-041).
- Sin base de datos propia: es una vista de consulta sobre `ms-users`.

## Rutas

| Ruta | Acceso | Quién la llama |
| --- | --- | --- |
| `POST /api/geo/matching/technicians` | `Authorization: Bearer <JWT de ms-users>`, rol `CLIENT` | Frontend (por Traefik, prefijo `/api/geo`) |
| `POST /internal/matching/technicians` | Cabecera `X-Internal-Api-Key` | Otros microservicios (ms-services); Traefik no la publica |
| `GET /health` | Libre | Sondas de salud |

Contrato completo en [`docs/openapi.yaml`](docs/openapi.yaml) (generado desde el código; una prueba falla si se desvía).

**Entrada:** `{category, city, latitude?, longitude?, limit?, cursor?}`. `category` es una de `PLUMBING`, `ELECTRICAL`,
`MAINTENANCE`, `LOCKSMITHING`, `PAINTING`, `CARPENTRY`. `limit` de 1 a 50 (20 por defecto). `latitude` y `longitude` van
juntas o ninguna: son el punto aproximado de la solicitud.

**Salida:** `{items: [{userId, displayName, categories, city}], nextCursor}`.

- **Zona:** un técnico coincide si atiende la ciudad (sin distinguir mayúsculas ni tildes) y, si definió un círculo y la
  consulta trae el punto, el punto cae dentro del radio (haversine). Si no hay círculo o no se envía el punto, basta la
  ciudad. Es la misma regla que `CoverageZone.covers` de ms-users.
- **No se devuelve** distancia, centro ni radio de la zona, ni datos de contacto: el círculo revela el domicilio aproximado
  del técnico y nunca sale de este servicio.
- **Paginación por cursor** (ADR-044): una consulta revisa como máximo 1500 técnicos (3 llamadas a ms-users). Una página puede
  venir corta, o vacía, con `nextCursor` no nulo: hay que seguir pidiendo hasta que sea nulo. El cursor es opaco.
- **Errores** en problem+json (RFC 7807): `400` datos o cursor inválidos, `401` credencial ausente o inválida (siempre la
  misma respuesta), `403` rol no permitido, `502` si ms-users no responde o responde algo inválido (nunca una lista vacía,
  que parecería que no hay técnicos).

## Seguridad

- **Ruta pública (ADR-039):** valida el JWT con la clave pública de ms-users (RS256 fijo; vigencia con 5 s de tolerancia,
  emisor, audiencia y claims `exp`, `iss`, `aud`, `jti`, `sub`) y consulta la revocación en
  `GET /internal/tokens/{jti}/status`, sin caché y **fallando cerrado**: si ms-users no responde, el token se rechaza. Solo
  el rol `ROLE_CLIENT` (claim `roles`) puede usarla.
- **Ruta interna (ADR-040):** clave compartida `X-Internal-Api-Key` (`INTERNAL_API_KEY`), comparada sobre hashes SHA-256 en
  tiempo constante. Sin clave configurada, rechaza todo. La clave es simétrica y su rotación es manual hasta que se
  integren Vault (ADR-028) y mTLS (ADR-019).
- **Riesgo aceptado:** cualquier cliente autenticado puede consultar técnicos por categoría y ciudad (es el catálogo de
  RF-029). Se acota con `limit` ≤ 50 y sin datos de contacto ni distancia; el límite de tasa corresponde a Traefik en QA y
  Producción.

## Configuración

Ver [`.env.example`](.env.example). `JWT_PUBLIC_KEY` es obligatoria; sin `INTERNAL_API_KEY` el servicio arranca pero rechaza
todo y lo avisa en el log.

| Variable | Por defecto | Descripción |
| --- | --- | --- |
| `JWT_PUBLIC_KEY` | — (obligatoria) | Clave pública X.509 de ms-users, en PEM |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `https://auth.fixia.com` / `https://api.fixia.com` | Los mismos de ms-users |
| `USERS_BASE_URL` | `http://ms-users:8080` | URL interna de ms-users |
| `INTERNAL_API_KEY` | vacía | Clave de las rutas `/internal/**` |
| `USERS_CONNECT_TIMEOUT` / `USERS_READ_TIMEOUT` | `1s` / `2s` | Esperas hacia ms-users |

## Estructura

Clean Architecture bajo `src/app/` (regla de dependencia hacia adentro):

- `domain/` — modelos y reglas de zona (`zone.py`), sin dependencias de HTTP.
- `application/` — caso de uso (`matching_service.py`) y el puerto `TechnicianDirectory`.
- `infrastructure/` — cliente de ms-users, consulta de revocación y validador JWT.
- `interfaces/` — rutas, esquemas, seguridad y errores de FastAPI.
- `main.py` — `create_app()`; uvicorn la arranca con `--factory`.

## Desarrollo

```bash
uv venv --python 3.12 .venv                    # o python3.12 -m venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt

.venv/bin/python -m pytest --cov=src/app --cov-fail-under=85     # lo mismo que corre el CI
.venv/bin/python -m scripts.export_openapi                        # regenerar docs/openapi.yaml tras cambiar el contrato

set -a; source .env; set +a                                       # ver .env.example
.venv/bin/uvicorn src.app.main:create_app --factory --port 8000
```

Las pruebas no necesitan ms-users: lo simulan con el transporte de `httpx` y firman los tokens con un par RSA propio.

## Docker

```bash
docker build -t ms-matching-geo .
docker run --rm -p 8000:8000 --env-file .env ms-matching-geo
```

En DEV lo levanta `ms-orchestrator` (perfil `services` o `full`) y Traefik enruta `/api/geo` al puerto 8000.
