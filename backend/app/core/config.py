"""Application configuration.

Single source of truth for settings. Everything reads from here instead of
calling os.getenv directly, so config is typed and validated at startup.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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