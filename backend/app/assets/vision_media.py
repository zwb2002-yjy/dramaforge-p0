"""Prepare exactly the still or video frame selected by a project owner."""

from __future__ import annotations

import hashlib
import io
import math
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import anyio
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.from_artifact_service import MediaSource, read_media_source
from app.assets.source_processors.contracts import MAX_IMAGE_PIXELS
from app.shared.errors import NotFoundError, ValidationAppError
from app.shared.vision import MAX_VISION_BYTES, ArtifactVisionInput, VisionTransform
from app.storage.materialized import (
    MAX_IMAGE_INPUT_BYTES,
    MAX_MEDIA_INPUT_BYTES,
    MediaTransferError,
    materialize_stream,
)
from app.storage.minio_store import ObjectStore

_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


def _invalid(message: str) -> ValidationAppError:
    return ValidationAppError(message, details={"code": "DIRECTOR_VISION_INPUT_INVALID"})


async def resolve_visual_artifact(
    session: AsyncSession,
    project_id: UUID,
    part: ArtifactVisionInput,
    *,
    lock: bool = False,
) -> MediaSource:
    source = await read_media_source(session, artifact_id=part.artifact_id, lock=lock)
    if not source or source.project_id != project_id or source.storage_state != "available":
        raise NotFoundError("画面不可用")
    if source.content_hash != part.expected_content_hash:
        raise _invalid("画面版本已改变，请重新选择")
    if source.artifact_type == "video" and source.mime_type == "video/mp4":
        if part.transform.frame_time_ms is None:
            raise _invalid("请选择视频中的一帧")
    elif source.artifact_type != "image" or source.mime_type not in _FORMATS:
        raise _invalid("此素材格式不支持识图")
    elif part.transform.frame_time_ms is not None:
        raise _invalid("静态图片没有视频时间点")
    return source


@dataclass(frozen=True)
class VisionFrame:
    width: int
    height: int
    png: bytes = field(repr=False)

    def evidence(self, part: ArtifactVisionInput) -> dict[str, object]:
        return {
            **part.model_dump(mode="json"),
            "processor": "director-frame-png-v1",
            "width": self.width,
            "height": self.height,
            "mime_type": "image/png",
            "byte_size": len(self.png),
            "content_hash": hashlib.sha256(self.png).hexdigest(),
        }


def _prepare(path: Path, mime: str, transform: VisionTransform) -> VisionFrame:
    if mime == "video/mp4":
        assert transform.frame_time_ms is not None
        frame_path = path.with_name("frame.png")
        # Restrict the demuxer and protocols to this local MP4. Demuxer external
        # data references remain disabled. One output frame, capped decoding size.
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-protocol_whitelist",
                    "file",
                    "-f",
                    "mov",
                    "-max_pixels",
                    str(MAX_IMAGE_PIXELS),
                    "-ss",
                    f"{transform.frame_time_ms // 1000}.{transform.frame_time_ms % 1000:03d}",
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-an",
                    "-threads",
                    "1",
                    str(frame_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _invalid("所选视频帧无法解码") from exc
        if result.returncode or not frame_path.exists():
            raise _invalid("所选时间点没有可解码的视频帧")
        path, mime = frame_path, "image/png"
    try:
        with Image.open(path, formats=[_FORMATS[mime]]) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS or getattr(image, "n_frames", 1) != 1:
                raise _invalid("图片超出像素上限或包含多帧")
            oriented = ImageOps.exif_transpose(image)
            if transform.crop:
                x0, y0, x1, y1 = transform.crop
                w, h = oriented.size
                oriented = oriented.crop(
                    (math.floor(x0 * w), math.floor(y0 * h), math.ceil(x1 * w), math.ceil(y1 * h))
                )
            oriented.thumbnail((transform.max_edge, transform.max_edge), Image.Resampling.LANCZOS)
            rgba = oriented.convert("RGBA")
            clean = Image.new("RGB", rgba.size, "white")
            clean.paste(rgba, mask=rgba.getchannel("A"))
            buffer = io.BytesIO()
            clean.save(buffer, format="PNG")
            png = buffer.getvalue()
            if len(png) > MAX_VISION_BYTES:
                raise _invalid("处理后的图片超过 4 MiB")
            return VisionFrame(clean.width, clean.height, png)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise _invalid("画面格式或字节无效") from exc


async def prepare_vision_frame(
    source: MediaSource,
    part: ArtifactVisionInput,
    store: ObjectStore,
) -> VisionFrame:
    """No open DB transaction. Verify size and original digest before decoding."""
    limit = MAX_MEDIA_INPUT_BYTES if source.artifact_type == "video" else MAX_IMAGE_INPUT_BYTES
    with tempfile.TemporaryDirectory(prefix="df-vision-") as work:
        path = Path(work) / "source"
        try:
            await materialize_stream(
                store.iter_bytes(object_key=source.object_key),
                destination=path,
                max_bytes=limit,
                expected_size=source.byte_size,
                expected_hash=part.expected_content_hash,
            )
        except (KeyError, MediaTransferError) as exc:
            raise _invalid("素材内容与已选版本不符或超出处理上限") from exc
        return await anyio.to_thread.run_sync(_prepare, path, source.mime_type, part.transform)
