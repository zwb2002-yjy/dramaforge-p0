"""Read-only evidence annotations; never a second model capability catalog.

Public notices are advisory, not account verification or execution policy.
Capabilities are always read from the selected immutable manifest.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class OfficialSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    url: str
    checked_at: date
    status: str = "documented_claim"


class LifecycleWarning(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    code: str = "VENDOR_RETIREMENT_ANNOUNCED"
    effective_at: datetime
    source: OfficialSource
    message: str = "Vendor retirement notice; do not silently change the frozen model."


_CHECKED = date(2026, 9, 24)
_AGNES_VIDEO = "https://wiki.agnes-ai.cn/zh-Hans/docs/agnes-video-v20"
_ARK_NOTICE = "https://docs.volcengine.com/docs/ark/model-deprecation-notice?lang=zh"
_SOURCES = {
    "agnes/agnes-image-2.1-flash": "https://wiki.agnes-ai.cn/zh-Hans/docs/agnes-image-21-flash",
    "agnes/agnes-video-v2.0": _AGNES_VIDEO,
    "volcengine/doubao-seedream-4-0-250828": _ARK_NOTICE,
    "volcengine/doubao-seedance-1-0-pro-250528": _ARK_NOTICE,
    "volcengine/doubao-seedance-2-0-260128": "https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh",
    "minimax/image-01": "https://platform.minimax.cn/docs/api-reference/image-generation-i2i",
    "minimax/MiniMax-H3": "https://platform.minimax.cn/docs/api-reference/video-generation-v2-create",
}


def official_sources(model_id: str) -> list[OfficialSource]:
    url = _SOURCES.get(model_id)
    return [OfficialSource(url=url, checked_at=_CHECKED)] if url else []


def lifecycle_warnings(model_id: str) -> list[LifecycleWarning]:
    if model_id == "agnes/agnes-video-v2.0":
        when, url = "2026-09-25T23:59:59+08:00", _AGNES_VIDEO
    elif model_id in {
        "volcengine/doubao-seedream-4-0-250828",
        "volcengine/doubao-seedance-1-0-pro-250528",
    }:
        when, url = "2026-11-24T14:00:00+08:00", _ARK_NOTICE
    else:
        return []
    return [
        LifecycleWarning(
            effective_at=datetime.fromisoformat(when),
            source=OfficialSource(url=url, checked_at=_CHECKED),
        )
    ]
