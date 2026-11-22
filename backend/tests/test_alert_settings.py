"""API-05: ALERTS_TOKEN_SECRET is required outside development, and a startup error
never prints the settings it was given (they hold API keys and the secret)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import MIN_TOKEN_SECRET_BYTES, Settings

GOOD_SECRET = "k" * MIN_TOKEN_SECRET_BYTES


def make(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_development_starts_without_a_secret():
    assert make(environment="development", alerts_token_secret="").alerts_token_secret == ""


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize("secret", ["", "k" * (MIN_TOKEN_SECRET_BYTES - 1)])
def test_staging_and_production_refuse_a_missing_or_short_secret(environment, secret):
    with pytest.raises(ValidationError, match="ALERTS_TOKEN_SECRET"):
        make(environment=environment, alerts_token_secret=secret)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_staging_and_production_start_with_a_long_enough_secret(environment):
    assert make(environment=environment, alerts_token_secret=GOOD_SECRET).alerts_token_secret == GOOD_SECRET


def test_a_startup_error_does_not_print_other_settings():
    with pytest.raises(ValidationError) as caught:
        make(environment="staging", alerts_token_secret="short-secret", airnow_api_key="AIRNOW-KEY-123")
    text = str(caught.value)
    assert "AIRNOW-KEY-123" not in text
    assert "short-secret" not in text
