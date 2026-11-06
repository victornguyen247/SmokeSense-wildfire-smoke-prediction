"""Application configuration.

Single source of truth for settings. Everything reads from here instead of
calling os.getenv directly, so config is typed and validated at startup.
"""

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationInfo, field_validator
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
    # Serve docs/api/fixtures instead of the database. Deployments must set this explicitly.
    mock_mode: bool = True
    # Browser origins allowed to call the API, comma-separated (docs/api.md, "CORS").
    # Add the staging and production frontend origins here when they exist.
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_contract_dir: Path = DEFAULT_API_CONTRACT_DIR
    # /meta: a forecast is stale when its cycle is older than this.
    forecast_stale_after_minutes: int = 150  # about two missed hourly cycles
    # /meta: a source is stale when its last successful run finished longer ago than this.
    freshness_stale_after_minutes_airnow: int = 150  # hourly at :25
    freshness_stale_after_minutes_firms: int = 90  # every 30 min
    freshness_stale_after_minutes_nws_obs: int = 150  # hourly at :05

    # --- Database (PostGIS) ---
    postgres_user: str = "smokesense"
    postgres_password: str = "smokesense"
    postgres_db: str = "smokesense"
    postgres_host: str = "db"
    postgres_port: int = 5432

    # Cloud database (e.g. Neon). When set it replaces the POSTGRES_* settings above;
    # leave empty to use the local Docker Postgres.
    cloud_database_url: str = Field(default="", validation_alias="DATABASE_URL")

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

    # --- Model registry (mlops/registry.py) ---
    # "local" keeps archives in a folder; "s3" uses any S3-compatible bucket (Cloudflare R2).
    # S3 credentials are NOT settings: boto3 reads AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.
    registry_backend: str = "local"  # local | s3
    registry_local_dir: str = "data/registry"
    registry_cache_dir: str = "data/registry_cache"
    registry_s3_bucket: str = "smoke-sense"
    registry_s3_prefix: str = "models"
    registry_s3_endpoint_url: str = ""  # R2: https://<account-id>.r2.cloudflarestorage.com

    @field_validator(
        "forecast_stale_after_minutes",
        "freshness_stale_after_minutes_airnow",
        "freshness_stale_after_minutes_firms",
        "freshness_stale_after_minutes_nws_obs",
        mode="before",
    )
    @classmethod
    def minutes_or_default(cls, value: object, info: ValidationInfo) -> object:
        """A blank or bad value means the default: .env.example leaves these blank, and a
        display threshold must not stop the API or the workers from starting."""
        default = cls.model_fields[info.field_name].default
        text = str(value).strip()
        if not text:
            return default
        if text.isdecimal() and int(text) >= 1:
            return int(text)
        logging.getLogger(__name__).error(
            "%s=%r is not a positive whole number; using %s", info.field_name, text, default
        )
        return default

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        if self.cloud_database_url:
            url = self.cloud_database_url.strip()
            for prefix in ("postgresql://", "postgres://"):
                if url.startswith(prefix):  # pick the psycopg 3 driver the project installs
                    return "postgresql+psycopg://" + url[len(prefix):]
            return url
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