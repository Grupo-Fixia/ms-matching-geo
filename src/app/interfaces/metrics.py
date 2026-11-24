"""Instrumentación de métricas HTTP en formato Prometheus texto 0.0.4 sin etiqueta uri=UNKNOWN."""
from __future__ import annotations

import re
import threading
import time

from fastapi import FastAPI, Request, Response

_UUID_SEGMENT = re.compile(
    r"(?<=/)[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)"
)


class PrometheusMetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str, int], list[float]] = {}

    def record(self, method: str, uri: str, status: int, duration_seconds: float) -> None:
        key = (method, uri, status)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = [1.0, duration_seconds]
            else:
                entry[0] += 1.0
                entry[1] += duration_seconds

    def render(self) -> str:
        lines = [
            "# HELP http_server_requests_seconds Duration of HTTP server requests in seconds",
            "# TYPE http_server_requests_seconds summary",
        ]
        with self._lock:
            snapshot = sorted(self._entries.items(), key=lambda item: (item[0][1], item[0][0], item[0][2]))
        for (method, uri, status), (count, total_sec) in snapshot:
            if 200 <= status < 300:
                outcome = "SUCCESS"
            elif 400 <= status < 500:
                outcome = "CLIENT_ERROR"
            elif status >= 500:
                outcome = "SERVER_ERROR"
            else:
                outcome = "INFORMATIONAL"
            labels = f'method="{method}",outcome="{outcome}",status="{status}",uri="{uri}"'
            lines.append(f"http_server_requests_seconds_count{{{labels}}} {int(count)}")
            lines.append(f"http_server_requests_seconds_sum{{{labels}}} {total_sec:.6f}")
        lines.append("")
        return "\n".join(lines)


def resolve_uri_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    raw_path = request.url.path or "/"
    return _UUID_SEGMENT.sub("{id}", raw_path)


def register_prometheus_metrics(app: FastAPI) -> PrometheusMetricsRegistry:
    registry = PrometheusMetricsRegistry()
    app.state.metrics_registry = registry

    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next):
        path = request.url.path or "/"
        if request.method == "GET" and path in ("/metrics", "/actuator/prometheus"):
            return Response(
                content=registry.render(),
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        uri = resolve_uri_template(request)
        registry.record(request.method, uri, response.status_code, elapsed)
        return response

    return registry
