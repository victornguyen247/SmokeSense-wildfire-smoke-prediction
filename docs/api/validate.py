"""Validate docs/api/openapi.yaml and every fixture in docs/api/fixtures/ against it.

Run from anywhere: python docs/api/validate.py
Fails if the spec is invalid, a fixture does not match its response schema, a fixture
is not listed in FIXTURES, an operation has no 200 fixture, or an error response does
not use the shared Error schema.
"""

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate as validate_spec
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

HERE = Path(__file__).resolve().parent
SPEC_PATH = HERE / "openapi.yaml"
FIXTURE_DIR = HERE / "fixtures"
SPEC_URI = "urn:smokesense:openapi"
HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options"}
ERROR_SCHEMA = {"$ref": "#/components/schemas/Error"}

# fixture file -> (path, method, status); a list when one body serves several operations
FIXTURES = {
    "grid_cells.json": ("/api/v1/grid/cells", "get", "200"),
    "forecast_grid.json": ("/api/v1/forecast/grid", "get", "200"),
    "forecast_point.json": ("/api/v1/forecast/point", "get", "200"),
    "forecast_point_no_forecast.json": ("/api/v1/forecast/point", "get", "200"),
    "forecast_monitors.json": ("/api/v1/forecast/monitors", "get", "200"),
    "fires_active.json": ("/api/v1/fires/active", "get", "200"),
    "observations_pm25_latest.json": ("/api/v1/observations/pm25/latest", "get", "200"),
    "meta.json": ("/api/v1/meta", "get", "200"),
    "health.json": [("/health", "get", "200"), ("/api/v1/health", "get", "200")],
    "error_out_of_scope.json": ("/api/v1/forecast/point", "get", "404"),
    "error_invalid_query.json": ("/api/v1/forecast/point", "get", "400"),
}


def escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def resolve_response(spec: dict, path: str, method: str, status: str) -> tuple[str, dict]:
    """JSON pointer to the response and the response itself, following a response $ref."""
    pointer = f"/paths/{escape(path)}/{method}/responses/{status}"
    response = spec["paths"][path][method]["responses"][status]
    if "$ref" in response:
        pointer = response["$ref"].removeprefix("#")
        response = spec["components"]["responses"][pointer.rsplit("/", 1)[1]]
    return pointer, response


def schema_pointer(spec: dict, path: str, method: str, status: str) -> str:
    """JSON pointer to the response's application/json schema."""
    pointer, response = resolve_response(spec, path, method, status)
    if "application/json" not in response.get("content", {}):
        raise KeyError(f"{method.upper()} {path} {status} has no application/json schema")
    return f"{pointer}/content/application~1json/schema"


def main() -> int:
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    validate_spec(spec)
    print(f"ok    {SPEC_PATH.name}")

    registry = Registry().with_resource(SPEC_URI, Resource.from_contents(spec, default_specification=DRAFT202012))
    errors = []

    on_disk = {p.name for p in FIXTURE_DIR.glob("*.json")}
    for name in sorted(on_disk - FIXTURES.keys()):
        errors.append(f"{name}: not listed in FIXTURES in validate.py")
    for name in sorted(FIXTURES.keys() - on_disk):
        errors.append(f"{name}: listed in FIXTURES but missing")

    targets = {name: t if isinstance(t, list) else [t] for name, t in FIXTURES.items()}
    covered = {(p, m) for ts in targets.values() for p, m, s in ts if s == "200"}
    for path, ops in spec["paths"].items():
        for method in ops.keys() & HTTP_METHODS:
            if (path, method) not in covered:
                errors.append(f"{method.upper()} {path}: no 200 fixture")
            # Every 4xx/5xx must be the one Error shape, never FastAPI's 422 {"detail": [...]}.
            for status in ops[method].get("responses", {}):
                if status.startswith(("4", "5")):
                    _, response = resolve_response(spec, path, method, status)
                    schema = response.get("content", {}).get("application/json", {}).get("schema")
                    if schema != ERROR_SCHEMA:
                        errors.append(f"{method.upper()} {path} {status}: does not use the Error schema")

    for name, ts in targets.items():
        if name not in on_disk:
            continue
        instance = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        for path, method, status in ts:
            schema = {"$ref": f"{SPEC_URI}#{schema_pointer(spec, path, method, status)}"}
            validator = Draft202012Validator(
                schema, registry=registry, format_checker=Draft202012Validator.FORMAT_CHECKER
            )
            problems = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
            # A nested failure inside allOf also makes the root report every property as
            # unevaluated; show the specific errors when there are any.
            specific = [e for e in problems if e.validator != "unevaluatedProperties"]
            for e in (specific or problems)[:10]:
                where = "/".join(str(p) for p in e.absolute_path) or "(root)"
                errors.append(f"{name}: {method.upper()} {path} {status}: {where}: {e.message[:200]}")
            if not problems:
                print(f"ok    {name}  ({method.upper()} {path} {status})")

    for e in errors:
        print(f"FAIL  {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
