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

    # Agnes AI OpenAI-compatible hub (local BYOK). Never log the raw key.
    agnes_enabled: bool = False
    agnes_api_key: str = Field(default="", description="User BYOK for Agnes hub")
    agnes_base_url: str = Field(default="https://apihub.agnes-ai.com/v1")
    agnes_image_model: str = Field(default="agnes-image-2.1-flash")
    agnes_video_model: str = Field(default="agnes-video-v2.0")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, value: object) -> object:
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",") if part.strip()]
            return items
        return value

    def agnes_configured(self) -> bool:
        """True when BYOK is present and hub is enabled."""
        return bool(self.agnes_enabled and self.agnes_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear settings cache (tests only)."""
    get_settings.cache_clear()
