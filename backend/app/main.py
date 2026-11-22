"""FastAPI application entrypoint.

Keeps the web layer thin: create the app, register middleware, error handlers and
routers. Routes (app/api/routes) parse requests, services (app/services) apply the
rules, and repositories (app/repositories) fetch the data; ML inference is in ml/.
The contract is docs/api/openapi.yaml (PM-02); see docs/api.md.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.contract import load_contract
from app.api.errors import register_error_handlers
from app.api.routes import fires, forecast, meta, observations
from app.core.config import settings
from app.core.logging import mask_access_log_queries
from app.services import meta_service

API_PREFIX = "/api/v1"

# Alert tokens can be in the query string (one-click unsubscribe); keep them out of the
# access log (docs/alerts.md section 2, "Tokens stay out of logs").
mask_access_log_queries()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
)

# /openapi.json and /docs serve the hand-written contract, not a generated schema.
app.openapi = load_contract

# Error handling first, so it sits inside CORS and its 500s still get CORS headers.
register_error_handlers(app)

# Only the known frontend origins, no cookies (docs/api.md, "CORS"). POST is for the
# alert endpoints (docs/alerts.md section 2); every other route still answers POST with
# 405, so allowing it here for all paths opens nothing else.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# The grid responses are large and compress ~10x (docs/api.md, "/grid/cells").
app.add_middleware(GZipMiddleware, minimum_size=1000)

for router in (forecast.router, fires.router, observations.router, meta.router):
    app.include_router(router, prefix=API_PREFIX)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness probe, kept at the root for existing deploy checks."""
    return meta_service.health()
