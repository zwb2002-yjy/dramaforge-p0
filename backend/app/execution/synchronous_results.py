"""Durable receipts for an already-returned synchronous image, never a new Create."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.execution.media_io import _MAX_PROVIDER_IMAGE_BYTES, _validate_provider_media
from app.execution.models import NodeRun, ProviderOperation
from app.providers.runtime import SubmissionResult
from app.shared.errors import ValidationAppError
from app.storage.minio_store import ObjectStore


class SynchronousImageReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    operation_id: UUID
    node_run_id: UUID
    artifact_uri: str | None = Field(default=None, min_length=1)
    object_key: str | None = Field(default=None, min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    byte_size: int | None = Field(default=None, ge=1, le=_MAX_PROVIDER_IMAGE_BYTES)

    @model_validator(mode="after")
    def require_one_result(self) -> "SynchronousImageReceipt":
        if self.artifact_uri is not None:
            fields = (self.object_key, self.content_hash, self.byte_size)
            if any(value is not None for value in fields):
                raise ValueError("URL receipts cannot contain stored object metadata")
        elif self.object_key is None or self.content_hash is None or self.byte_size is None:
            raise ValueError("stored image receipts require key, hash and size")
        return self


def receipt_object_key(*, run: NodeRun, operation: ProviderOperation) -> str:
    return f"projects/{run.project_id}/operations/{operation.id}/synchronous-image"


def synchronous_image_receipt(
    *, run: NodeRun, operation: ProviderOperation,
) -> SynchronousImageReceipt | None:
    raw = (operation.response_summary or {}).get("synchronous_result")
    if raw is None:
        return None
    try:
        receipt = SynchronousImageReceipt.model_validate(raw)
        if receipt.operation_id != operation.id or receipt.node_run_id != run.id:
            raise ValueError("synchronous result owner mismatch")
        if receipt.object_key is not None and receipt.object_key != receipt_object_key(
            run=run, operation=operation,
        ):
            raise ValueError("synchronous result object scope mismatch")
    except ValueError as exc:
        raise ValidationAppError(
            "Synchronous image receipt cannot be verified; do not resubmit",
            details={"code": "SYNCHRONOUS_RESULT_INVALID"},
        ) from exc
    return receipt


async def persist_synchronous_image_result(
    *, run: NodeRun, operation: ProviderOperation, result: SubmissionResult, store: ObjectStore,
) -> SynchronousImageReceipt:
    if result.artifact_bytes is not None:
        data = result.artifact_bytes
        if not data or len(data) > _MAX_PROVIDER_IMAGE_BYTES:
            raise ValidationAppError("PROVIDER_MEDIA_INVALID: synchronous image size")
        _validate_provider_media(kind="image", data=data[:64], content_type=None)
        stored = await store.put_bytes(
            object_key=receipt_object_key(run=run, operation=operation),
            data=data, mime_type="application/octet-stream",
        )
        return SynchronousImageReceipt(
            operation_id=operation.id, node_run_id=run.id, object_key=stored.object_key,
            content_hash=stored.content_hash, byte_size=stored.byte_size,
        )
    return SynchronousImageReceipt(
        operation_id=operation.id, node_run_id=run.id, artifact_uri=result.artifact_uri,
    )
