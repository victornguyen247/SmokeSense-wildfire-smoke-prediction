"""Request bodies of the alert endpoints (docs/alerts.md section 2).

They mirror `AlertSubscribeRequest` and `AlertTokenRequest` in docs/api/openapi.yaml.
Responses are plain dicts checked by the contract tests, like every other endpoint.
A validation error is 400 invalid_query (app/api/errors.py), and its message never
repeats the submitted value, so an email can't end up in a response or a log.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.query import PointQuery

# Deliberately loose (one @, a dot in the domain, no spaces): the confirmation email is
# the real check. email-validator is not a dependency.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class AlertSubscribeRequest(BaseModel):
    """An email plus exactly one location form: `zip`, or `lat` + `lon`."""

    # strict: JSON types as the spec says (no "39.7" strings or true as a number).
    model_config = ConfigDict(extra="forbid", strict=True)

    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)
    zip: str | None = Field(default=None, pattern=r"^[0-9]{5}$")
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        # Trimmed and lower-cased before the checks, as the spec says.
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def one_location_form(self) -> AlertSubscribeRequest:
        has_point = self.lat is not None or self.lon is not None
        if self.zip is not None and has_point:
            raise ValueError("Pass either lat and lon, or zip, not both.")
        if self.zip is None and (self.lat is None or self.lon is None):
            raise ValueError("Pass lat and lon together, or zip.")
        return self

    def location(self) -> PointQuery:
        """The location in the form the point lookup takes (same as /forecast/point)."""
        if self.zip is not None:
            return PointQuery(zip=self.zip)
        return PointQuery(lat=self.lat, lon=self.lon)


class AlertTokenRequest(BaseModel):
    """Body of /alerts/confirm and /alerts/unsubscribe. The token's shape is checked by
    the service (404 invalid_token, not 400), so the token pages show one message."""

    model_config = ConfigDict(extra="forbid", strict=True)

    token: str = Field(min_length=1, max_length=128)
