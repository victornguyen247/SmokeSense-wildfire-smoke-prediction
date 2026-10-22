"""FastAPI application entrypoint.

Keeps the web layer thin: create the app, register middleware, error handlers and
routers. Business logic lives in app/services and ML inference in ml/.
The contract is docs/api/openapi.yaml (PM-02); see docs/api.md.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.contract import load_contract
from app.api.errors import register_error_handlers
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
)

# /openapi.json and /docs serve the hand-written contract, not a generated schema.
app.openapi = load_contract

# Error handling first, so it sits inside CORS and its 500s still get CORS headers.
register_error_handlers(app)

# Only the known frontend origins, read-only, no cookies (docs/api.md, "CORS").
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Content-Type"],
)

# The grid responses are large and compress ~10x (docs/api.md, "/grid/cells").
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness probe, kept at the root for existing deploy checks."""
    return {"status": "ok", "environment": settings.environment}
