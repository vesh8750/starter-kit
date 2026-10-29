"""Application factory.

``create_app()`` rather than a module-level ``app = FastAPI()`` so that tests can build
an isolated instance with overridden settings, and so that nothing is constructed as an
import side effect.

Run locally:      make dev
Run in a server:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.api.v1 import api_router
from app.core.config import Environment, Settings, get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware.setup import install_middleware
from app.core.openapi import configure_openapi
from app.core.responses import ORJSONResponse
from app.lifespan import lifespan
from app.observability.health import router as health_router
from app.observability.metrics import metrics_endpoint


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    show_docs = settings.environment is not Environment.PRODUCTION

    app = FastAPI(
        title=f"{settings.project_name} API",
        version=__version__,
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
        root_path=settings.root_path,
        docs_url="/docs" if show_docs else None,
        redoc_url="/redoc" if show_docs else None,
        openapi_url="/openapi.json" if show_docs else None,
    )

    # The lifespan and any code holding only the app must see *these* settings, not
    # whatever get_settings() happens to return. Without this, create_app(test_settings)
    # silently builds an app whose startup uses the process-wide configuration.
    app.state.settings = settings

    install_middleware(app, settings)
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    if settings.metrics_enabled:
        app.add_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)

    configure_openapi(app, settings)
    return app


app = create_app()
