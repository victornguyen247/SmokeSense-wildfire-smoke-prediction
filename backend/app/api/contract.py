"""Serves docs/api/openapi.yaml as the app's OpenAPI document.

The hand-written spec is the contract, so /openapi.json and /docs show it rather than
the schema FastAPI would generate from the code, which could disagree with it. The
contract tests (backend/tests/test_api_contract.py) keep the code and the spec in step.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from app.core.config import settings


@lru_cache
def load_contract() -> dict[str, Any]:
    spec_path = settings.api_contract_dir / "openapi.yaml"
    return yaml.safe_load(spec_path.read_text(encoding="utf-8"))
