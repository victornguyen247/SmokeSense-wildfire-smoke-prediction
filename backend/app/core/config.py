"""Application configuration.

Single source of truth for settings. Everything reads from here instead of
calling os.getenv directly, so config is typed and validated at startup.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# docs/api/ (the OpenAPI spec and its fixtures), found from this file: <repo>/backend/app/core/
# locally, and /code/app/core/ in Docker, where docker-compose mounts docs/api at /docs/api.
DEFAULT_API_CONTRACT_DIR = Path(__file__).resolve().parents[3] / "docs" / "api"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "SmokeSense API"
    environment: str = Field(default="development")  # development | staging | production
    debug: bool = Field(default=True)

    # --- API (API-01) ---
    # Serve docs/api/fixtures instead of the database. Stays on until the database
    # repository exists; with it off, every data route fails with internal_error.
    mock_mode: bool = True
    # Browser origins allowed to call the API, comma-separated (docs/api.md, "CORS").
    # Add the staging and production frontend origins here when they exist.
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_contract_dir: Path = DEFAULT_API_CONTRACT_DIR

    # --- Database (PostGIS) ---
    postgres_user: str = "smokesense"
    postgres_password: str = "smokesense"
    postgres_db: str = "smokesense"
    postgres_host: str = "db"
    postgres_port: int = 5432

    # --- Redis / Celery ---
    redis_url: str = "redis://redis:6379/0"

    # --- External data-source API keys ---
    # Obtain these from each provider; leave blank locally until needed.
    firms_map_key: str = ""       # NASA FIRMS
    airnow_api_key: str = ""      # EPA AirNow
    purpleair_api_key: str = ""   # PurpleAir
    # NWS API needs no key but requires a User-Agent identifying your app.
    nws_user_agent: str = "SmokeSense (contact@example.com)"

    # PurpleAir bills points per sensor-hour. Caps how many sensors the
    # DATA-03 batch pulls per event. Defaults to the same safe cap as the
    # connector's smoke test, so a .env that predates this setting stays
    # capped; set PURPLEAIR_MAX_SENSORS=0 to explicitly remove the cap.
    purpleair_max_sensors: int = 5

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        # Local Docker Postgres has no TLS; add ?sslmode=require only for hosted DBs.
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so the env file is parsed once per process."""
    return Settings()



settings = get_settings()