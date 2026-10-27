"""API-01 app shell: the error shape, CORS, compression and the served spec."""

from __future__ import annotations

import asyncio

import yaml
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from app.api.errors import UnexpectedErrorMiddleware, handle_validation_error
from app.core.config import settings
from app.main import app

SPEC = yaml.safe_load((settings.api_contract_dir / "openapi.yaml").read_text(encoding="utf-8"))
SPEC_URI = "urn:smokesense:openapi"
REGISTRY = Registry().with_resource(SPEC_URI, Resource.from_contents(SPEC, default_specification=DRAFT202012))
FRONTEND_ORIGIN = "http://localhost:5173"

client = TestClient(app)


def assert_spec_schema(name: str, body: object) -> None:
    schema = {"$ref": f"{SPEC_URI}#/components/schemas/{name}"}
    Draft202012Validator(schema, registry=REGISTRY).validate(body)


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    assert_spec_schema("Error", response.json())
    assert response.json()["code"] == code


def test_health_matches_the_spec():
    response = client.get("/health")
    assert response.status_code == 200
    assert_spec_schema("Health", response.json())


def test_openapi_json_is_the_hand_written_spec():
    assert client.get("/openapi.json").json() == SPEC


def test_unknown_route_is_not_found():
    assert_error(client.get("/api/v1/nope"), 404, "not_found")


def test_non_get_is_rejected_with_error_shape():
    assert_error(client.post("/health"), 405, "not_found")


def test_validation_errors_are_400_not_422():
    def code_for(field: str) -> tuple[int, dict]:
        exc = RequestValidationError([{"loc": ("query", field), "msg": "bad value", "type": "value_error"}])
        response = asyncio.run(handle_validation_error(None, exc))
        return response.status_code, yaml.safe_load(response.body)

    assert code_for("lat") == (400, {"code": "invalid_query", "message": "lat: bad value"})
    assert code_for("bbox")[1]["code"] == "invalid_bbox"


def test_unexpected_error_is_internal_error_without_details():
    async def broken_app(scope, receive, send):
        raise RuntimeError("secret detail that must not leak")

    response = TestClient(UnexpectedErrorMiddleware(broken_app), raise_server_exceptions=False).get("/")
    assert_error(response, 500, "internal_error")
    assert "secret" not in response.text and "Traceback" not in response.text


def test_cors_allows_the_frontend_origin_read_only():
    response = client.options(
        "/health",
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert response.headers["access-control-allow-methods"] == "GET"
    assert "access-control-allow-credentials" not in response.headers


def test_cors_rejects_unknown_origins():
    response = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
    preflight = client.options(
        "/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 400


def test_cors_origins_setting_is_comma_separated(monkeypatch):
    monkeypatch.setattr(settings, "cors_allowed_origins", " https://a.example , https://b.example,")
    assert settings.cors_origins == ["https://a.example", "https://b.example"]


def test_large_responses_are_gzipped_small_ones_are_not():
    gzip = {"Accept-Encoding": "gzip"}
    assert client.get("/openapi.json", headers=gzip).headers.get("content-encoding") == "gzip"
    assert "content-encoding" not in client.get("/health", headers=gzip).headers
