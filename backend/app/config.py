"""Application configuration loaded from environment variables."""

import ipaddress
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
    session_cookie_secure: bool = Field(
        default=False,
        description=(
            "Mark session and CSRF cookies Secure. Enable only when the public "
            "origin is HTTPS; the loopback HTTP installer must keep this false."
        ),
    )

    database_url: str = Field(
        default="postgresql+asyncpg://dramaforge:dramaforge@localhost:5432/dramaforge",
        description="SQLAlchemy async DSN using asyncpg",
    )
    database_ssl: bool = Field(
        default=False,
        description="Enable TLS for PostgreSQL connections; local Compose defaults to false",
    )
    # Connection-pool sizing per process (backend-review 1.4): every container
    # shares one PostgreSQL, so each role states its own ceiling. The Compose
    # services set these per role (api 20+10, worker-default 10+5,
    # worker-heavy 5+5, dispatcher 3+2); the sum stays well under the
    # PostgreSQL max_connections budget.
    db_pool_size: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Steady pool connections per process engine",
    )
    db_max_overflow: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Burst connections allowed beyond db_pool_size",
    )
    db_pool_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Seconds a checkout waits for a free connection before failing",
    )
    db_pool_recycle_seconds: int = Field(
        default=1800,
        ge=30,
        le=86400,
        description="Recycle connections older than this to survive idle resets",
    )
    director_runtime_engine: Literal["langgraph"] = Field(
        default="langgraph",
        description="The single durable Director execution engine",
    )
    director_checkpoint_database_url: str = Field(
        default="",
        description="Dedicated psycopg DSN for the private Director checkpoint schema",
    )
    byok_rotation_database_url: str = Field(
        default="",
        description=(
            "Dedicated maintenance DSN for BYOK key rotation; never used by the API or workers"
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
    agnes_image_request_timeout_seconds: float = Field(
        default=300.0,
        ge=60.0,
        le=360.0,
        description="Agnes synchronous image request timeout within the vendor's 60-360s range",
    )
    agnes_max_concurrent_submissions: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Maximum concurrent Agnes paid create requests per worker process",
    )

    # Volcengine Ark profile (local BYOK). Never log the raw key.
    volcengine_enabled: bool = False
    volcengine_api_key: str = Field(default="", description="User BYOK for Volcengine Ark")
    volcengine_base_url: str = Field(default="https://ark.cn-beijing.volces.com/api/v3")
    volcengine_image_model: str = Field(default="doubao-seedream-4-0-250828")
    volcengine_video_model: str = Field(default="doubao-seedance-2-0-260128")

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
    # Workspace-supplied provider base_urls decide where encrypted provider
    # credentials are sent. Private self-hosted deployments are a supported
    # product feature (joint review 6-4); this explicit operator opt-in
    # admits private and loopback destinations (never link-local/metadata)
    # for authenticated self-hosted networks.
    provider_base_url_allow_private: bool = Field(
        default=False,
        description="Authorize private/loopback provider base_urls for self-hosted deployments",
    )
    # Scoped plaintext-HTTP trust for provider base_urls (joint-review
    # follow-up: local model deployments must not require a global security
    # downgrade). Declaring a network authorizes, for exactly those
    # addresses: http:// base_urls (IP literals at write time) and
    # connection-time egress. Link-local, multicast, unspecified and
    # reserved addresses stay blocked even when a network claims them.
    provider_trusted_http_networks: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description=(
            "Comma-separated IPv4/IPv6 CIDRs authorized for plaintext HTTP "
            "provider base_urls, e.g. PROVIDER_TRUSTED_HTTP_NETWORKS=172.18.6.0/24"
        ),
    )

    # Generic OpenAI-compatible media protocol. This is a protocol connection,
    # not a supplier-specific plugin: the workspace supplies URL + key and picks
    # discovered image/video model ids from the UI.
    openai_compatible_media_enabled: bool = False
    openai_compatible_media_auth_mode: str = Field(default="bearer", pattern="^(bearer|none)$")
    openai_compatible_media_api_key: str = Field(
        default="", description="Workspace BYOK for OpenAI-compatible image/video APIs"
    )
    openai_compatible_media_base_url: str = Field(default="https://api.openai.com/v1")
    openai_compatible_media_image_model: str = Field(default="")
    openai_compatible_media_video_model: str = Field(default="")
    openai_compatible_media_timeout_seconds: float = Field(default=300.0, ge=30.0, le=900.0)
    # LiteLLM Gateway backend (spec §24–§26, §113; fix spec §3/§22). Text models
    # registered in the V3 registry with ``backend.kind="litellm"`` submit
    # through this OpenAI-compatible gateway. ``LITELLM_API_KEY`` is the
    # DramaForge restricted data key used to call the gateway — NOT an upstream
    # provider key (fix spec §22/§57).
    litellm_gateway_url: str = Field(
        default="",
        description=(
            "LiteLLM Gateway base URL; canonical dev value http://litellm:4000 "
            "(fix spec §19/§20 — adapter always appends /v1/chat/completions)"
        ),
    )
    litellm_api_key: str = Field(
        default="", repr=False, exclude=True, description="LiteLLM data key"
    )
    litellm_model_admin_key: str = Field(default="", repr=False, exclude=True)
    # Logical alias the ``litellm/script-quality`` bootstrap bridge sends to the
    # gateway (fix spec §32/§33). DramaForge
    # requests the logical group, the LiteLLM Router picks the deployment.
    litellm_text_gateway_model: str = Field(
        default="script-quality",
        description="Logical gateway model alias used by the litellm/script-quality bridge",
    )
    # Static logical aliases registered as ``litellm/<alias>`` text models
    # (fix spec §34/§41/§104). Profile slots (planning.brief/script/storyboard)
    # can bind these even before discovery runs.
    litellm_logical_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["script-quality", "script-fast"],
        description="Comma-separated LiteLLM logical aliases registered at bootstrap",
    )
    # Speech is explicit and opt-in; network speech never falls back to local speech.
    tts_enabled: bool = False
    tts_engine: str = "edge-tts"
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_proxy: str | None = Field(default=None, repr=False, exclude=True)

    @field_validator(
        "cors_origins", "litellm_logical_models", "provider_trusted_http_networks", mode="before"
    )
    @classmethod
    def split_csv_lists(cls, value: object) -> object:
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",") if part.strip()]
            return items
        return value

    @field_validator("provider_trusted_http_networks", mode="after")
    @classmethod
    def validate_trusted_http_networks(cls, value: list[str]) -> list[str]:
        """Canonicalize and bound the plaintext-HTTP trust scope.

        A whole-address-space network would silently turn the scoped policy
        into a global "any HTTP destination" downgrade, so /0 is rejected.
        """

        canonical: list[str] = []
        for entry in value:
            try:
                network = ipaddress.ip_network(entry, strict=False)
            except ValueError as exc:
                raise ValueError(
                    f"PROVIDER_TRUSTED_HTTP_NETWORKS entry is not a valid network: {entry}"
                ) from exc
            if network.prefixlen == 0:
                raise ValueError(
                    "PROVIDER_TRUSTED_HTTP_NETWORKS must not cover the whole address space"
                )
            canonical.append(network.with_prefixlen)
        return canonical

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

    def provider_trusted_network_objects(
        self,
    ) -> tuple["ipaddress.IPv4Network | ipaddress.IPv6Network", ...]:
        """Parsed, canonical trusted networks for the scoped HTTP policy."""
        return tuple(ipaddress.ip_network(entry) for entry in self.provider_trusted_http_networks)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear settings cache (tests only)."""
    get_settings.cache_clear()
