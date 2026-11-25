"""API-05: request bodies of the alert endpoints (app/schemas/alerts.py).

They must accept what `AlertSubscribeRequest` / `AlertTokenRequest` in docs/api/openapi.yaml
accept, reject the rest, and never echo the submitted email in an error message.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.alerts import AlertSubscribeRequest, AlertTokenRequest
from app.schemas.query import PointQuery


def test_email_is_trimmed_and_lower_cased():
    body = AlertSubscribeRequest.model_validate({"email": "  Someone@Example.COM ", "zip": "95928"})
    assert body.email == "someone@example.com"


def test_location_is_zip_or_point():
    by_zip = AlertSubscribeRequest.model_validate({"email": "a@b.co", "zip": "95928"})
    assert by_zip.location() == PointQuery(zip="95928")
    by_point = AlertSubscribeRequest.model_validate({"email": "a@b.co", "lat": 39.73, "lon": -121.84})
    assert by_point.location() == PointQuery(lat=39.73, lon=-121.84)


@pytest.mark.parametrize(
    "body",
    [
        {"email": "a@b.co"},  # no location
        {"email": "a@b.co", "lat": 39.7},  # lat without lon
        {"email": "a@b.co", "lon": -121.8},
        {"email": "a@b.co", "zip": "95928", "lat": 39.7, "lon": -121.8},  # both forms
        {"email": "a@b.co", "zip": "9592"},
        {"email": "a@b.co", "lat": 91, "lon": -121.8},
        {"email": "a@b.co", "lat": "39.7", "lon": "-121.8"},  # strings are not numbers
        {"email": "a@b.co", "lat": True, "lon": -121.8},
        {"email": "not-an-email", "zip": "95928"},
        {"email": "a@b.co" + "x" * 250, "zip": "95928"},
        {"zip": "95928"},
        {"email": "a@b.co", "zip": "95928", "name": "extra"},  # strict: no other fields
    ],
)
def test_bad_subscribe_bodies_are_rejected(body):
    with pytest.raises(ValidationError):
        AlertSubscribeRequest.model_validate(body)


def test_error_messages_do_not_repeat_the_email():
    with pytest.raises(ValidationError) as caught:
        AlertSubscribeRequest.model_validate({"email": "private.person@example.com"})
    # app/api/errors.py builds the 400 message from loc + msg only.
    assert all("private.person" not in e["msg"] for e in caught.value.errors())


def test_token_body_takes_any_string_up_to_128_chars():
    # The shape (43 base64url chars) is the service's check, giving 404 invalid_token.
    assert AlertTokenRequest.model_validate({"token": "short"}).token == "short"
    for bad in [{"token": ""}, {"token": "x" * 129}, {}, {"token": 5}, {"token": "a", "other": 1}]:
        with pytest.raises(ValidationError):
            AlertTokenRequest.model_validate(bad)
