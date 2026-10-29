"""Middleware installation and ordering.

Starlette applies middleware in reverse registration order, so the **last** one added is
the outermost. The order below is deliberate:

    RequestContext   (outermost -- every log line and every error carries the request id)
      SecurityHeaders (applies to all responses, including errors)
        Metrics       (measures the real handler, not our own bookkeeping)
          CORS
            TrustedHost / HTTPSRedirect (deployed only)
              GZip
                application routes

CORS sits inside the error-producing layers so that a browser can actually read a 500
response instead of being told it is a CORS failure.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import Settings
from app.core.context import REQUEST_ID_HEADER
from app.core.middleware.body_limit import MaxBodySizeMiddleware
from app.core.middleware.request_context import RequestContextMiddleware
from app.core.middleware.security_headers import SecurityHeadersMiddleware
from app.observability.metrics import MetricsMiddleware


def install_middleware(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=settings.max_request_body_bytes)

    if settings.trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
            max_age=600,
        )

    if settings.metrics_enabled:
        app.add_middleware(MetricsMiddleware)

    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=settings.environment.is_deployed,
        docs_paths=frozenset({"/docs", "/redoc"}),
    )
    app.add_middleware(RequestContextMiddleware)
