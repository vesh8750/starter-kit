"""Prometheus metrics.

A pull-based ``/metrics`` endpoint with RED metrics (Rate, Errors, Duration) covers the
operational questions that actually get asked in an incident. Distributed tracing
(OpenTelemetry) is a deliberate omission: it is worth adding the moment this service
calls two or three others, and nothing here prevents it -- the request id already
propagates, which is what makes traces correlatable.

Route *templates* are used as labels (``/api/v1/pets/{pet_id}``), never raw paths, so
cardinality stays bounded no matter how many ids are requested.
"""

from __future__ import annotations

import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REGISTRY = CollectorRegistry(auto_describe=True)

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    labelnames=("method", "path", "status"),
    registry=REGISTRY,
)

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency.",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return

        method: str = scope.get("method", "")
        status_code = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = _route_template(scope)
            REQUEST_DURATION.labels(method=method, path=path).observe(time.perf_counter() - started)
            REQUEST_COUNT.labels(method=method, path=path, status=str(status_code)).inc()


def _route_template(scope: Scope) -> str:
    """Return the full parameterised path, e.g. ``/api/v1/pets/{pet_id}``.

    ``scope["route"].path`` is relative to the router that was included, so the mount
    prefix has to be recovered. It is recovered structurally -- drop from the concrete
    request path exactly as many trailing segments as the route template has -- rather
    than by substituting parameter values out of the path, which silently corrupts the
    label whenever a value equals a literal segment (``/pets/pets`` became
    ``/{pet_id}/pets``). Route templates drive metric cardinality, so a wrong label is a
    wrong dashboard for as long as the series is retained.

    Walking FastAPI's router tree was the other option and was rejected: the include
    machinery is private and changed shape between versions, and leaf ``Route`` objects
    are shared between mounts, so they cannot be keyed by identity.

    Unmatched requests collapse to a single label so a scanner probing random URLs
    cannot create unbounded time series.
    """
    route = scope.get("route")
    if route is None:
        return "__unmatched__"
    template = str(getattr(route, "path", "") or "")
    request_path = str(scope.get("path", ""))
    if not template:
        return request_path or "__unmatched__"
    # A `:path` converter swallows slashes, so segment arithmetic does not apply.
    if ":path}" in template:
        return template

    template_segments = len(template.strip("/").split("/")) if template.strip("/") else 0
    request_segments = request_path.strip("/").split("/") if request_path.strip("/") else []
    if template_segments > len(request_segments):
        return template
    prefix_segments = request_segments[: len(request_segments) - template_segments]
    prefix = "/" + "/".join(prefix_segments) if prefix_segments else ""
    return f"{prefix}{template}"


async def metrics_endpoint(_: Request) -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
