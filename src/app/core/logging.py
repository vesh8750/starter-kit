"""Structured logging setup.

One logger style for the whole application: ``structlog.get_logger(__name__)``, called
with an event name and keyword fields (``log.info("pet.created", pet_id=...)``) rather
than interpolated strings. Standard-library loggers (uvicorn, sqlalchemy, third-party
packages) are routed through the same pipeline so that *all* output shares one format.

Renderer is chosen by configuration: human-readable colour locally, JSON when deployed.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import Settings
from app.core.context import get_request_id

_NOISY_LOGGERS = {
    "uvicorn.access": logging.WARNING,  # replaced by our own access log
    "sqlalchemy.engine": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
}


def _add_request_id(_: object, __: str, event_dict: EventDict) -> EventDict:
    """Stamp every log line with the current correlation id, when inside a request."""
    request_id = get_request_id()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)
    return event_dict


def _drop_color_message(_: object, __: str, event_dict: EventDict) -> EventDict:
    """uvicorn duplicates `event` into `color_message`; it is noise once reformatted."""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging. Idempotent; safe to call in tests."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_request_id,
        _drop_color_message,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: Processor
    if settings.log_renderer == "json":
        renderer = structlog.processors.JSONRenderer()
        shared.append(structlog.processors.format_exc_info)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)

    for name, level in _NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(level)
    if settings.database_echo:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Preferred entry point: ``log = get_logger(__name__)`` at module level."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def bind_log_context(**values: Any) -> None:
    """Bind fields to every log line emitted for the rest of this request/task."""
    structlog.contextvars.bind_contextvars(**values)


def clear_log_context() -> None:
    structlog.contextvars.clear_contextvars()


__all__ = [
    "bind_log_context",
    "clear_log_context",
    "configure_logging",
    "get_logger",
]
