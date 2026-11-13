"""Transport profiles: the wire protocol through which a model is called.

A :class:`TransportProfile` explicitly acknowledges that provider protocols
differ (spec §22). It is *not* an attempt to make them identical — it is the
place where endpoint method/path, auth scheme, encoding, response mode, poll and
cancel contracts are declared. Business code never sees these values; the
Runtime owns their application. Profiles declare protocol facts only: they do
not build model payloads, bind credentials, or execute requests. Media compilers
own ``wire_request``; runtimes send it without recompilation and own network,
polling and resume. A declaration is not an executable transport implementation.

``Provider == Protocol`` is forbidden: one provider may own several profiles
(e.g. an OpenAI-compatible gateway plus a native task API), and the same protocol
may be reached through different connections (official / corporate gateway /
local gateway — spec §23.1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuthSpec(BaseModel):
    """Credential scheme for a transport profile (spec §22). Only *how* the
    credential is applied — the credential itself lives in the keyring and is
    referenced by id, never embedded here."""

    model_config = ConfigDict(frozen=True)

    scheme: Literal["bearer", "api_key_header", "query", "custom", "none"]
    header_name: str | None = None
    prefix: str | None = None


class PollSpec(BaseModel):
    """Async task polling contract (spec §22)."""

    model_config = ConfigDict(frozen=True)

    method: str
    path_template: str
    default_interval_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class TransportProfile(BaseModel):
    """One wire protocol declaration (spec §22)."""

    model_config = ConfigDict(frozen=True)

    id: str
    method: str
    path_template: str
    auth: AuthSpec
    content_type: str
    request_encoding: Literal["json", "multipart", "form", "custom"]
    response_mode: Literal["sync", "async_poll", "async_webhook"]
    poll: PollSpec | None = None
    cancel_path_template: str | None = None

    @model_validator(mode="after")
    def require_poll_contract(self) -> TransportProfile:
        if self.response_mode == "async_poll" and self.poll is None:
            raise ValueError("async_poll transport requires a poll contract")
        return self
