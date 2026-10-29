"""Configuration is validated, not merely read."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings


def test_csv_and_json_lists_are_both_accepted():
    assert Settings(cors_origins="http://a,http://b").cors_origins == ["http://a", "http://b"]
    assert Settings(cors_origins='["http://a"]').cors_origins == ["http://a"]


def test_production_rejects_debug_and_wildcard_cors():
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            environment=Environment.PRODUCTION,
            debug=True,
            log_renderer="console",
            secret_key="x" * 40,
            cors_origins="*",
        )
    message = str(exc_info.value)
    assert "DEBUG must be false" in message
    assert "CORS_ORIGINS must not contain" in message


def test_production_accepts_a_safe_configuration():
    settings = Settings(
        _env_file=None,
        environment=Environment.PRODUCTION,
        debug=False,
        log_renderer="json",
        secret_key="s" * 48,
        database_url="postgresql+asyncpg://db.internal:5432/app",
        cors_origins="https://app.example.com",
    )
    assert settings.environment.is_deployed


def test_production_refuses_to_boot_without_an_explicit_secret_key():
    """A generated default would differ per replica and per restart, silently
    invalidating every issued token with no error anywhere."""
    with pytest.raises(ValidationError, match="SECRET_KEY must be set explicitly"):
        Settings(
            _env_file=None,
            environment=Environment.PRODUCTION,
            log_renderer="json",
            database_url="postgresql+asyncpg://db.internal:5432/app",
        )


def test_production_refuses_a_defaulted_or_localhost_database():
    with pytest.raises(ValidationError, match="DATABASE_URL must be set explicitly"):
        Settings(
            _env_file=None,
            environment=Environment.PRODUCTION,
            log_renderer="json",
            secret_key="s" * 48,
        )
    with pytest.raises(ValidationError, match="must not point at localhost"):
        Settings(
            _env_file=None,
            environment=Environment.PRODUCTION,
            log_renderer="json",
            secret_key="s" * 48,
            database_url="postgresql+asyncpg://localhost:5432/app",
        )


def test_list_settings_accept_csv_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    """Regression: pydantic-settings JSON-decodes complex fields read from the
    environment before validators run, which rejected the documented `A,B` form."""
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com,https://b.example.com")
    assert Settings(_env_file=None).cors_origins == [
        "https://a.example.com",
        "https://b.example.com",
    ]


def test_list_settings_accept_json_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORS_ORIGINS", '["https://a.example.com"]')
    assert Settings(_env_file=None).cors_origins == ["https://a.example.com"]
