from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.security import (
    create_access_token,
    hash_password,
    principal_from_token,
    verify_password,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(secret_key="t" * 48)


def test_password_hashing_round_trip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_verify_password_is_safe_on_garbage_input():
    assert verify_password("x", "not-a-hash") is False


def test_token_round_trip_preserves_subject_and_scopes(settings: Settings):
    token = create_access_token(settings, subject="user-1", scopes={"pets:write"})
    principal = principal_from_token(settings, token.access_token)
    assert principal.subject == "user-1"
    assert principal.has_scope("pets:write")


def test_expired_token_is_rejected(settings: Settings):
    token = create_access_token(settings, subject="user-1", ttl=timedelta(seconds=-10))
    with pytest.raises(AuthenticationError):
        principal_from_token(settings, token.access_token)


def test_token_signed_with_another_key_is_rejected(settings: Settings):
    token = create_access_token(Settings(secret_key="o" * 48), subject="user-1")
    with pytest.raises(AuthenticationError):
        principal_from_token(settings, token.access_token)
