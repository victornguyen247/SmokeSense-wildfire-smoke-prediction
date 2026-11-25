"""The alert routes over HTTP (API-05): body parsing, RFC 8058 one-click, error shapes.

Mock mode, with the repository swapped for a fake where a test needs to see the calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_alert_repository
from app.core.tokens import token_hash
from app.main import app
from test_alert_service import FakeRepo

client = TestClient(app, raise_server_exceptions=False)
TOKEN = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
UNSUBSCRIBE = "/api/v1/alerts/unsubscribe"


@pytest.fixture
def repo():
    fake = FakeRepo()
    app.dependency_overrides[get_alert_repository] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_alert_repository, None)


def test_one_click_post_takes_the_token_from_the_query(repo):
    response = client.post(
        f"{UNSUBSCRIBE}?token={TOKEN}",
        content="List-Unsubscribe=One-Click",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "unsubscribed"}
    assert repo.unsubscribed == [token_hash(TOKEN)]


def test_json_unsubscribe(repo):
    response = client.post(UNSUBSCRIBE, json={"token": TOKEN})
    assert (response.status_code, response.json()) == (200, {"status": "unsubscribed"})
    assert repo.unsubscribed == [token_hash(TOKEN)]


@pytest.mark.parametrize(
    "kwargs",
    [
        {},  # no body, no query token
        {"content": "List-Unsubscribe=One-Click", "headers": {"Content-Type": "application/x-www-form-urlencoded"}},
        {"json": {}},
        {"json": {"token": TOKEN, "extra": 1}},
        {"json": {"token": 43}},
        {"json": ["not", "an", "object"]},
    ],
)
def test_bad_unsubscribe_bodies_are_400_invalid_query(repo, kwargs):
    response = client.post(UNSUBSCRIBE, **kwargs)
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_query"
    assert not repo.unsubscribed


def test_an_over_long_query_token_is_400(repo):
    assert client.post(f"{UNSUBSCRIBE}?token={'A' * 129}").status_code == 400


@pytest.mark.parametrize("path", ["/api/v1/alerts/confirm", UNSUBSCRIBE])
def test_malformed_tokens_are_404_invalid_token(path):
    response = client.post(path, json={"token": "not-a-token"})
    assert response.status_code == 404
    assert response.json()["code"] == "invalid_token"


@pytest.mark.parametrize(
    "body",
    [
        {"email": "someone@example.com"},
        {"email": "someone@example.com", "zip": "95928", "lat": 39.7, "lon": -121.8},
        {"email": "someone@example.com", "lat": 39.7},
        {"email": "not-an-email", "zip": "95928"},
        {"email": "someone@example.com", "zip": 95928},
        {"email": "someone@example.com", "lat": "39.7", "lon": "-121.8"},
        {"email": "someone@example.com", "zip": "95928", "name": "x"},
    ],
)
def test_bad_subscribe_bodies_are_400_invalid_query(body):
    response = client.post("/api/v1/alerts/subscriptions", json=body)
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_query"
    assert "someone@example.com" not in response.text


def test_subscribe_out_of_scope_is_404():
    response = client.post(
        "/api/v1/alerts/subscriptions", json={"email": "someone@example.com", "lat": 45.52, "lon": -122.68}
    )
    assert response.status_code == 404
    assert response.json()["code"] == "out_of_scope"


def test_integer_coordinates_are_accepted():
    response = client.post(
        "/api/v1/alerts/subscriptions", json={"email": "Someone@Example.com ", "lat": 39, "lon": -122}
    )
    assert response.status_code == 202


def test_get_is_405_on_alert_paths():
    response = client.get("/api/v1/alerts/confirm")
    assert response.status_code == 405
    assert response.json()["code"] == "not_found"
