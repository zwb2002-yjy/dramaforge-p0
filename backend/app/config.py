"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime settings. Secrets must come from env, never defaults with real keys."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "DramaForge"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    # NoDecode: accept comma-separated env values instead of JSON arrays.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    database_url: str = Field(
        default="postgresql+asyncpg://dramaforge:dramaforge@localhost:5432/dramaforge",
        description="SQLAlchemy async DSN using asyncpg",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    minio_endpoint: str = Field(default="http://localhost:9000")
    minio_access_key: str = Field(default="minioadmin")
    minio_secret_key: str = Field(default="minioadmin")
    minio_bucket: str = Field(default="dramaforge")
    minio_region: str = Field(default="us-east-1")

    session_secret: str = Field(
        default="dev-only-change-me-to-a-long-random-string",
        min_length=16,
    )
    byok_fernet_key: str = Field(
        default="dev-only-fernet-key-replace-in-prod==",
        min_length=16,
        description="Fernet key material for encrypting user BYOK; replace in production",
    )

    arq_default_queue_name: str = "dramaforge:default"
    arq_heavy_queue_name: str = "dramaforge:heavy"
    worker_kind: Literal["default", "heavy"] = "default"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, value: object) -> object:
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",") if part.strip()]
            return items
        return value


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear settings cache (tests only)."""
    get_settings.cache_clear()
