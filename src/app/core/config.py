"""Typed application configuration.

Configuration is read once from the environment (and `.env` locally), validated by
Pydantic, and exposed through :func:`get_settings`. Nothing in the codebase should
read ``os.environ`` directly -- if a value is configurable, it belongs here so that
it is documented, typed and validated at startup rather than at first use.
"""

from __future__ import annotations

import json
import secrets
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BeforeValidator,
    Field,
    PostgresDsn,
    RedisDsn,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_deployed(self) -> bool:
        return self in {Environment.STAGING, Environment.PRODUCTION}


def _split_csv(value: object) -> object:
    """Accept both `A,B` and `["A","B"]` for list-valued settings.

    pydantic-settings only JSON-decodes complex fields when they come from the
    environment, so handling both shapes here keeps `.env` files and direct
    construction (tests, scripts) behaving identically.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return [item.strip() for item in text.split(",") if item.strip()]


# NoDecode stops pydantic-settings from JSON-decoding the raw environment value before
# validation, which would reject the comma-separated form outright. _split_csv then
# handles both shapes itself.
CsvList = Annotated[list[str], NoDecode, BeforeValidator(_split_csv)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # -- application ---------------------------------------------------------
    project_name: str = "pet"
    environment: Environment = Environment.LOCAL
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    root_path: str = ""

    # -- observability -------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_renderer: Literal["console", "json"] = "console"
    metrics_enabled: bool = True

    # -- security ------------------------------------------------------------
    # No default in deployed environments -- see _enforce_deployment_safety. A generated
    # default is convenient locally and catastrophic in production: every replica and
    # every restart would sign with a different key, silently invalidating all tokens.
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48), min_length=32)
    jwt_algorithm: Literal["HS256", "HS512"] = "HS256"
    access_token_ttl_seconds: int = Field(default=3600, gt=0)
    cors_origins: CsvList = Field(default_factory=list)
    trusted_hosts: CsvList = Field(default_factory=list)

    # -- database ------------------------------------------------------------
    database_url: PostgresDsn = PostgresDsn("postgresql+asyncpg://localhost:5432/pet_dev")
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    database_echo: bool = False
    database_statement_timeout_ms: int = Field(default=15_000, ge=0)

    # -- cache ---------------------------------------------------------------
    cache_backend: Literal["memory", "redis"] = "memory"
    cache_default_ttl_seconds: int = Field(default=300, gt=0)
    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")

    # -- storage -------------------------------------------------------------
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: Path = Path("var/uploads")
    storage_public_base_url: str = "http://localhost:8000/static"
    storage_max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    # Global ceiling applied before any body is buffered. Must be >= the largest
    # per-endpoint upload limit, or those endpoints can never receive a full payload.
    max_request_body_bytes: int = Field(default=12 * 1024 * 1024, gt=0)

    # -- outbound http -------------------------------------------------------
    http_timeout_seconds: float = Field(default=10.0, gt=0)
    http_max_retries: int = Field(default=2, ge=0)
    http_max_connections: int = Field(default=100, gt=0)

    @property
    def database_host(self) -> str | None:
        """First host of the DSN. ``PostgresDsn`` is a multi-host URL, so there is no
        plain ``.host`` attribute."""
        hosts = self.database_url.hosts()
        return hosts[0].get("host") if hosts else None

    @property
    def database_url_str(self) -> str:
        return str(self.database_url)

    @property
    def sync_database_url(self) -> str:
        """Blocking URL, used by tooling that cannot speak asyncio (e.g. psql dumps)."""
        return self.database_url_str.replace("+asyncpg", "")

    @model_validator(mode="after")
    def _enforce_deployment_safety(self) -> Self:
        """Fail fast on configurations that are unsafe outside a developer laptop.

        Every check here exists because the *convenient* default is dangerous once
        deployed. Failing the deploy is always cheaper than discovering it in production.
        """
        if not self.environment.is_deployed:
            return self
        problems: list[str] = []
        if self.debug:
            problems.append("DEBUG must be false")
        if self.log_renderer != "json":
            problems.append("LOG_RENDERER must be 'json'")
        # Explicitly set, not defaulted: a generated key differs per replica and per
        # restart, so tokens would fail verification at random with no error anywhere.
        if "secret_key" not in self.model_fields_set:
            problems.append("SECRET_KEY must be set explicitly (never defaulted)")
        elif "dev-only" in self.secret_key or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be a strong generated value")
        # Likewise: defaulting to localhost means a production pod quietly fails to find
        # a database instead of telling you the variable is missing.
        if "database_url" not in self.model_fields_set:
            problems.append("DATABASE_URL must be set explicitly")
        elif self.database_host in {"localhost", "127.0.0.1"}:
            problems.append("DATABASE_URL must not point at localhost")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must not contain '*'")
        if self.max_request_body_bytes < self.storage_max_upload_bytes:
            problems.append(
                "MAX_REQUEST_BODY_BYTES must be >= STORAGE_MAX_UPLOAD_BYTES, "
                "otherwise uploads are rejected before the endpoint sees them"
            )
        if problems:
            raise ValueError(
                f"Invalid configuration for environment={self.environment}: " + "; ".join(problems)
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so that every caller -- including FastAPI dependencies -- sees the same
    validated object. Tests override it via ``app.dependency_overrides`` or by
    calling ``get_settings.cache_clear()``.
    """
    return Settings()
