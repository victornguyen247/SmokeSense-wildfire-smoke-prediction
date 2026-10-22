"""API-01 contract tests: the app must match docs/api/openapi.yaml (PM-02).

Every response here is validated against the spec's schema for its path and status,
so CI fails when the implementation drifts from the contract. Runs in mock mode
against the fixtures, listed in docs/api/fixture_manifest.json.
"""

from __future__ import annotations

import json

import pytest
import yaml
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from app.api.deps import get_repository
from app.core.config import settings
from app.core.scope import CALIFORNIA_BBOX
from app.main import app
from app.schemas.query import Bbox
from app.services.scope_service import resolve_bbox

CONTRACT_DIR = settings.api_contract_dir
SPEC = yaml.safe_load((CONTRACT_DIR / "openapi.yaml").read_text(encoding="utf-8"))
MANIFEST = json.loads((CONTRACT_DIR / "fixture_manifest.json").read_text(encoding="utf-8"))["fixtures"]
SPEC_URI = "urn:smokesense:openapi"
REGISTRY = Registry().with_resource(SPEC_URI, Resource.from_contents(SPEC, default_specification=DRAFT202012))

FRONTEND_ORIGIN = "http://localhost:5173"
PARK_FIRE_BBOX = "-122.95,39.40,-121.50,40.10"
BBOX_PATHS = [
    "/api/v1/grid/cells",
    "/api/v1/forecast/grid",
    "/api/v1/forecast/monitors",
    "/api/v1/fires/active",
    "/api/v1/observations/pm25/latest",
]
# FastAPI's own pages, which serve the spec rather than being part of it.
NON_CONTRACT_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}

client = TestClient(app, raise_server_exceptions=False)


def fixture(name: str) -> dict:
    return json.loads((CONTRACT_DIR / "fixtures" / name).read_text(encoding="utf-8"))


def escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def assert_matches_spec(path: str, status: int, body: object) -> None:
    """Validate body against the spec's application/json schema for GET path at status."""
    responses = SPEC["paths"][path]["get"]["responses"]
    assert str(status) in responses, f"GET {path} returned {status}, which the spec doesn't list"
    pointer = f"/paths/{escape(path)}/get/responses/{status}"
    response = responses[str(status)]
    if "$ref" in response:
        pointer = response["$ref"].removeprefix("#")
    schema = {"$ref": f"{SPEC_URI}#{pointer}/content/application~1json/schema"}
    validator = Draft202012Validator(schema, registry=REGISTRY, format_checker=Draft202012Validator.FORMAT_CHECKER)
    problems = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:200]}" for e in validator.iter_errors(body)]
    assert not problems, f"GET {path} {status} doesn't match the spec:\n" + "\n".join(problems[:10])


def assert_error_shape(response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json()["code"] == code
    error_schema = {"$ref": f"{SPEC_URI}#/components/schemas/Error"}
    Draft202012Validator(error_schema, registry=REGISTRY).validate(response.json())


# --- the routes are the spec's routes ---


def test_app_serves_exactly_the_spec_paths():
    served = {
        (route.path, method.lower())
        for route in app.routes
        if isinstance(route, APIRoute) and route.path not in NON_CONTRACT_PATHS
        for method in route.methods
    }
    in_spec = {(path, method) for path, ops in SPEC["paths"].items() for method in ops if method != "parameters"}
    assert served == in_spec


# --- every 200 matches its fixture and the spec ---

FIXTURE_TARGETS = [
    (name, target["path"])
    for name, targets in MANIFEST.items()
    for target in targets
    if target["status"] == 200
]


@pytest.mark.parametrize(("name", "path"), FIXTURE_TARGETS, ids=[f"{n}:{p}" for n, p in FIXTURE_TARGETS])
def test_mock_mode_serves_each_fixture(name, path):
    expected = fixture(name)
    params = {}
    if path == "/api/v1/forecast/point":
        params = {k: v for k, v in expected["query"].items() if k in ("lat", "lon", "zip") and v is not None}
    response = client.get(path, params=params)
    assert response.status_code == 200
    assert_matches_spec(path, 200, response.json())
    if name != "health.json":  # /health reports the running environment
        assert response.json() == expected


@pytest.mark.parametrize("path", BBOX_PATHS)
def test_bbox_routes_accept_a_bbox(path):
    response = client.get(path, params={"bbox": PARK_FIRE_BBOX})
    assert response.status_code == 200
    assert_matches_spec(path, 200, response.json())


def test_forecast_point_by_zip():
    response = client.get("/api/v1/forecast/point", params={"zip": "95926"})
    assert response.status_code == 200
    assert_matches_spec("/api/v1/forecast/point", 200, response.json())


# --- errors use the one Error shape, with the spec's status codes ---

POINT = "/api/v1/forecast/point"
POINT_ERRORS = [
    ({"lat": "39.7", "lon": "-121.8", "zip": "95926"}, 400, "invalid_query"),
    ({"lat": "39.7"}, 400, "invalid_query"),
    ({}, 400, "invalid_query"),
    ({"lat": "", "lon": "-121.8"}, 400, "invalid_query"),
    ({"lat": "91", "lon": "-121.8"}, 400, "invalid_query"),
    ({"lat": "abc", "lon": "-121.8"}, 400, "invalid_query"),
    ({"zip": "9592"}, 400, "invalid_query"),
    ({"zip": "97201"}, 404, "out_of_scope"),
    ({"lat": "45.52", "lon": "-122.68"}, 404, "out_of_scope"),
]


@pytest.mark.parametrize(("params", "status", "code"), POINT_ERRORS)
def test_forecast_point_errors(params, status, code):
    response = client.get(POINT, params=params)
    assert_error_shape(response, status, code)
    assert_matches_spec(POINT, status, response.json())


def test_error_fixtures_are_what_the_api_returns():
    out_of_scope = client.get(POINT, params={"lat": "45.52", "lon": "-122.68"})
    assert out_of_scope.json() == fixture("error_out_of_scope.json")
    both = client.get(POINT, params={"lat": "39.7", "lon": "-121.8", "zip": "95926"})
    assert both.json() == fixture("error_invalid_query.json")


BBOX_ERRORS = [
    ("abc", 400, "invalid_bbox"),
    ("", 400, "invalid_bbox"),
    ("-122,39,-121", 400, "invalid_bbox"),
    ("-121,40,-122,39", 400, "invalid_bbox"),
    ("-200,30,-190,35", 400, "invalid_bbox"),
    ("-100,30,-90,35", 404, "out_of_scope"),
]


@pytest.mark.parametrize("path", BBOX_PATHS)
@pytest.mark.parametrize(("bbox", "status", "code"), BBOX_ERRORS)
def test_bbox_errors(path, bbox, status, code):
    response = client.get(path, params={"bbox": bbox})
    assert_error_shape(response, status, code)
    assert_matches_spec(path, status, response.json())


def test_unexpected_error_is_internal_error_with_cors():
    def broken_repository():
        raise RuntimeError("secret detail that must not leak")

    app.dependency_overrides[get_repository] = broken_repository
    try:
        response = client.get("/api/v1/meta", headers={"Origin": FRONTEND_ORIGIN})
    finally:
        app.dependency_overrides.clear()
    assert_error_shape(response, 500, "internal_error")
    assert_matches_spec("/api/v1/meta", 500, response.json())
    assert "secret" not in response.text and "Traceback" not in response.text
    # Without CORS headers the browser would report a network error instead.
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_mock_mode_off_fails_data_routes_but_not_health(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", False)
    assert_error_shape(client.get("/api/v1/meta"), 500, "internal_error")
    assert client.get("/health").status_code == 200


# --- caching (CORS, gzip and the generic error cases are in test_api_app.py) ---


def test_grid_cells_are_cacheable():
    first = client.get("/api/v1/grid/cells")
    second = client.get("/api/v1/grid/cells")
    assert first.headers["cache-control"] == "public, max-age=86400"
    assert first.headers["etag"] == second.headers["etag"]


# --- scope rules ---


def test_bbox_defaults_to_and_is_clipped_to_california():
    assert resolve_bbox(None) == CALIFORNIA_BBOX
    clipped = resolve_bbox(Bbox(-130.0, 40.0, -120.0, 45.0))
    assert clipped == Bbox(CALIFORNIA_BBOX.min_lon, 40.0, -120.0, CALIFORNIA_BBOX.max_lat)


def test_point_near_the_no_forecast_fixture_gets_it():
    response = client.get(POINT, params={"lat": "39.8", "lon": "-122.9"})
    assert response.json()["cell"]["has_forecast"] is False
