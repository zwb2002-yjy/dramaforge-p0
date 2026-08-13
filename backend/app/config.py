"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def project_env_file() -> Path:
    """Return the repository .env file regardless of the process working directory."""
    return Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Validated runtime settings. Secrets must come from env, never defaults with real keys."""

    model_config = SettingsConfigDict(
        env_file=project_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "DramaForge"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    source_commit: str = Field(
        default="",
        validation_alias=AliasChoices(
            "DRAMAFORGE_SOURCE_COMMIT",
            "SOURCE_COMMIT",
        ),
        description="Exact Git commit loaded by the API and Worker processes",
    )
    # NoDecode: accept comma-separated env values instead of JSON arrays.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    public_registration_enabled: bool = Field(
        default=False,
        description=(
            "Allow account creation after the first Owner bootstrap. Keep false for "
            "the default single-user self-hosted deployment."
        ),
    )

    database_url: str = Field(
        default="postgresql+asyncpg://dramaforge:dramaforge@localhost:5432/dramaforge",
        description="SQLAlchemy async DSN using asyncpg",
    )
    byok_rotation_database_url: str = Field(
        default="",
        description=(
            "Dedicated maintenance DSN for BYOK key rotation; never used by "
            "the API or workers"
        ),
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    minio_endpoint: str = Field(default="http://localhost:9000")
    minio_access_key: str = Field(default="minioadmin")
    minio_secret_key: str = Field(default="minioadmin")
    minio_bucket: str = Field(default="dramaforge")
    minio_region: str = Field(default="us-east-1")

    session_secret: str = Field(
        default="",
        min_length=16,
    )
    byok_fernet_key: str = Field(
        default="",
        min_length=16,
        description="Generated Fernet key material for encrypting user BYOK",
    )
    byok_primary_key_version: str = Field(
        default="legacy",
        min_length=1,
        max_length=80,
        description="Primary version used to encrypt persisted BYOK credentials",
    )
    byok_keyring: str = Field(
        default="",
        description="Comma-separated retained BYOK Fernet keys in version:key form",
    )

    arq_default_queue_name: str = "dramaforge:default"
    arq_heavy_queue_name: str = "dramaforge:heavy"
    arq_heavy_max_jobs: int = Field(
        default=4,
        ge=1,
        description="Maximum concurrent heavy media jobs per Arq worker process",
    )
    worker_kind: Literal["default", "heavy"] = "default"
    worker_token: str = Field(
        default="",
        description="Shared secret for /api/v1/worker/tick (local Worker substitute)",
    )

    # Agnes China profile (local BYOK). Never log the raw key.
    agnes_enabled: bool = False
    agnes_api_key: str = Field(default="", description="User BYOK for Agnes hub")
    agnes_base_url: str = Field(default="https://api.agnes-ai.cn/v1")
    agnes_image_model: str = Field(default="agnes-image-2.1-flash")
    agnes_video_model: str = Field(default="agnes-video-v2.0")

    # Volcengine Ark profile (local BYOK). Never log the raw key.
    volcengine_enabled: bool = False
    volcengine_api_key: str = Field(default="", description="User BYOK for Volcengine Ark")
    volcengine_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/v3"
    )
    volcengine_image_model: str = Field(default="doubao-seedream-4-0-250828")
    volcengine_video_model: str = Field(default="doubao-seedance-1-0-pro-250528")

    # MiniMax China profile (local BYOK). Never log the raw key.
    minimax_enabled: bool = False
    minimax_api_key: str = Field(default="", description="User BYOK for MiniMax")
    minimax_base_url: str = Field(default="https://api.minimaxi.com")
    minimax_image_model: str = Field(default="image-01")
    minimax_video_model: str = Field(default="MiniMax-H3")
    reference_public_base_url: str = Field(
        default="",
        description="Public HTTPS API origin used for short-lived Provider references",
    )
    reference_token_ttl_seconds: int = Field(default=3600, ge=60, le=86400)

    # Text LLM BYOK (Anthropic-compatible Messages API, e.g. baizhi / DeepSeek).
    text_llm_enabled: bool = False
    text_llm_api_key: str = Field(default="", description="User BYOK for text LLM")
    text_llm_base_url: str = Field(
        default="",
        description="Anthropic-compatible base, e.g. https://host/api/anthropic",
    )
    text_llm_model: str = Field(
        default="deepseek-v4-flash",
        description="Catalog id (baizhi dsv4flash → deepseek-v4-flash)",
    )
    text_llm_api_style: Literal["anthropic", "openai"] = "anthropic"

    # LiteLLM Gateway backend (spec §24–§26, §113; fix spec §3/§22). Text models
    # registered in the V3 registry with ``backend.kind="litellm"`` submit
    # through this OpenAI-compatible gateway. ``LITELLM_API_KEY`` is the
    # DramaForge Virtual/Master key used to call the gateway — NOT an upstream
    # provider key (fix spec §22/§57).
    litellm_gateway_url: str = Field(
        default="",
        description=(
            "LiteLLM Gateway base URL; canonical dev value http://litellm:4000 "
            "(fix spec §19/§20 — adapter always appends /v1/chat/completions)"
        ),
    )
    litellm_api_key: str = Field(default="", description="LiteLLM Gateway API key")
    # text.generate V3 router migration flag (spec §100–§101). When enabled,
    # Agent Brief/Plan resolve through ModelBindingResolver + CapabilityRouter.
    # Default OFF so the legacy OpenAI adapter path stays the production path
    # until the router path is stable.
    text_v3_router_enabled: bool = False
    # Logical alias the ``litellm/text-llm`` bootstrap bridge sends to the
    # gateway (fix spec §32/§33). Decoupled from TEXT_LLM_MODEL — DramaForge
    # requests the logical group, the LiteLLM Router picks the deployment.
    litellm_text_gateway_model: str = Field(
        default="legacy-text",
        description="Logical gateway model alias used by the litellm/text-llm bridge",
    )
    # Static logical aliases registered as ``litellm/<alias>`` text models
    # (fix spec §34/§41/§104). Profile slots (planning.brief/script/storyboard)
    # can bind these even before discovery runs.
    litellm_logical_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["script-quality", "script-fast"],
        description="Comma-separated LiteLLM logical aliases registered at bootstrap",
    )
    # Best-effort startup sync of ``GET /v1/models`` into the default registry
    # (fix spec §36/§37). Default OFF keeps app boot fast and gateway-independent;
    # admin refresh / tests call the sync service explicitly.
    litellm_discovery_startup: bool = False

    # Local TTS is opt-in for formal development verification.
    tts_enabled: bool = False
    tts_engine: str = "espeak-ng"
    tts_voice: str = "zh"
    insightface_enabled: bool = False
    insightface_model_name: str = "buffalo_l"
    insightface_model_root: str = "/models/insightface"

    # Stage A+B provider unification. All default OFF; each flips when the
    # matching stage lands. Resume never reads these flags (persisted state wins).
    provider_catalog_enabled: bool = False
    provider_unified_shadow: bool = False
    provider_unified_path_enabled: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, value: object) -> object:
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",") if part.strip()]
            return items
        return value

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Self:
        """Reject known development secrets before a production process starts."""
        if self.app_env != "production":
            return self
        unsafe = {
            "",
            "dev-only-change-me-to-a-long-random-string",
            "dev-only-fernet-key-replace-in-prod==",
            "dev-worker-token",
        }
        if self.session_secret.strip() in unsafe or len(self.session_secret.strip()) < 32:
            raise ValueError("SESSION_SECRET must be a generated production secret")
        if self.worker_token.strip() in unsafe or len(self.worker_token.strip()) < 32:
            raise ValueError("WORKER_TOKEN must be a generated production secret")
        try:
            from cryptography.fernet import Fernet

            Fernet(self.byok_fernet_key.strip().encode("ascii"))
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise ValueError("BYOK_FERNET_KEY must be a valid generated Fernet key") from exc
        if self.byok_fernet_key.strip() in unsafe:
            raise ValueError("BYOK_FERNET_KEY must not use the published example key")
        return self

    def agnes_configured(self) -> bool:
        """True when BYOK is present and hub is enabled."""
        return bool(self.agnes_enabled and self.agnes_api_key.strip())

    def volcengine_configured(self) -> bool:
        """True when BYOK is present and Ark is enabled."""
        return bool(self.volcengine_enabled and self.volcengine_api_key.strip())

    def minimax_configured(self) -> bool:
        """True when MiniMax BYOK is present and its profile is enabled."""
        return bool(self.minimax_enabled and self.minimax_api_key.strip())

    def text_llm_configured(self) -> bool:
        return bool(
            self.text_llm_enabled
            and self.text_llm_api_key.strip()
            and self.text_llm_base_url.strip()
        )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear settings cache (tests only)."""
    get_settings.cache_clear()
