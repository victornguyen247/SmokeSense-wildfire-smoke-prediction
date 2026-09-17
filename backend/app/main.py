"""FastAPI application entrypoint.

Keeps the web layer thin: create the app, register routers, expose a health
check. Business logic lives in app/services and ML inference in ml/.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

# When routers are added, import and include them here, e.g.:
# from app.api.routes import predictions, locations, alerts, city_history

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
)

# Allow the local frontend dev server to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness probe. Extend later to check DB and Redis connectivity."""
    return {"status": "ok", "environment": settings.environment}


# app.include_router(predictions.router, prefix="/api")
# app.include_router(locations.router, prefix="/api")
# app.include_router(alerts.router, prefix="/api")
# app.include_router(city_history.router, prefix="/api")