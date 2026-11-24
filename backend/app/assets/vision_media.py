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
from app.assets.source_processors.contracts import MAX_IMAGE_PIXELS, MAX_SOURCE_BYTES
from app.assets.source_processors.media import FRAME_MAX_WIDTH
from app.assets.source_processors.pdf import RASTER_DPI
from app.assets.vision_files import FileVisualSource, resolve_file_visual
from app.assets.vision_public import public_visual_source
from app.shared.errors import NotFoundError, ValidationAppError
from app.shared.vision import (
    MAX_VISION_BYTES,
    ArtifactVisionInput,
    FileVisionInput,
    PublicVisionInput,
    SourceMediaInput,
    VisionTransform,
)
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
    return _validate_media(source, part)


def _validate_media(
    source: MediaSource, part: ArtifactVisionInput | PublicVisionInput,
) -> MediaSource:
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


async def resolve_visual_source(
    session: AsyncSession,
    project_id: UUID,
    part: SourceMediaInput,
    *,
    lock: bool = False,
    preview: bool = False,
) -> MediaSource | FileVisualSource:
    if isinstance(part, FileVisionInput):
        return await resolve_file_visual(session, project_id, part, lock=lock)
    if isinstance(part, PublicVisionInput):
        source, _ = await public_visual_source(
            session, project_id, part, lock=lock, preview=preview,
        )
        return _validate_media(source, part)
    return await resolve_visual_artifact(session, project_id, part, lock=lock)


@dataclass(frozen=True)
class VisionFrame:
    width: int
    height: int
    png: bytes = field(repr=False)
    fragment_location: dict[str, object] = field(default_factory=dict)

    def evidence(self, part: SourceMediaInput) -> dict[str, object]:
        return {
            **part.model_dump(mode="json"),
            **self.fragment_location,
            "processor": "file-fragment-png-v1" if part.kind == "file" else "director-frame-png-v1",
            "width": self.width,
            "height": self.height,
            "mime_type": "image/png",
            "byte_size": len(self.png),
            "content_hash": hashlib.sha256(self.png).hexdigest(),
        }


def _prepare(
    path: Path, source: MediaSource | FileVisualSource, transform: VisionTransform
) -> VisionFrame:
    file = source if isinstance(source, FileVisualSource) else None
    decoder = (
        source.decoder
        if isinstance(source, FileVisualSource)
        else ("mov" if source.mime_type == "video/mp4" else _FORMATS[source.mime_type])
    )
    frame_path = path.with_name("frame.png")
    command: list[str] = []
    bbox = file.bbox if file else None
    if decoder in {"mov", "matroska"}:
        time_ms = file.index if file else transform.frame_time_ms
        assert time_ms is not None
        # OCR rectangles are in the parser's sampled PNG coordinate system.
        scale = ["-vf", f"scale='min({FRAME_MAX_WIDTH},iw)':-2"] if bbox else []
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-protocol_whitelist",
            "file",
            "-f",
            decoder,
            "-max_pixels",
            str(MAX_IMAGE_PIXELS),
            "-ss",
            f"{time_ms // 1000}.{time_ms % 1000:03d}",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-an",
            *scale,
            "-threads",
            "1",
            str(frame_path),
        ]
    elif decoder == "pdf" and file:
        # Poppler uses a one-based page number and the OCR parser used 150 dpi.
        page = str(file.index + 1)
        region = ["-scale-to", "2048"]
        if bbox:
            x, y, right, bottom = bbox
            if (right - x) * (bottom - y) > MAX_IMAGE_PIXELS:
                raise _invalid("资料片段超过像素上限")
            region = [
                "-r",
                str(RASTER_DPI),
                "-x",
                str(x),
                "-y",
                str(y),
                "-W",
                str(right - x),
                "-H",
                str(bottom - y),
            ]
            bbox = None  # Poppler already rendered just the authorized rectangle.
        command = [
            "pdftoppm",
            "-f",
            page,
            "-l",
            page,
            "-singlefile",
            *region,
            "-png",
            str(path),
            str(frame_path.with_suffix("")),
        ]
    if command:
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _invalid("所选资料画面无法解码") from exc
        if result.returncode or not frame_path.is_file():
            raise _invalid("所选位置没有可解码的画面")
        path, decoder = frame_path, "PNG"
    try:
        with Image.open(path, formats=[decoder]) as image:
            if file and file.image_size:
                image.seek(file.index)
            elif getattr(image, "n_frames", 1) != 1:
                raise _invalid("请选择单张画面")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise _invalid("图片超出像素上限")
            oriented = ImageOps.exif_transpose(image)
            if file and file.image_size and oriented.size != file.image_size:
                raise _invalid("资料片段坐标与当前原件不符")
            if bbox:
                if bbox[2] > oriented.width or bbox[3] > oriented.height:
                    raise _invalid("片段取景越界")
                oriented = oriented.crop(bbox)
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
            location: dict[str, object] = {}
            if file:
                position = {
                    "pdf": "page_index",
                    "matroska": "frame_time_ms",
                    "mov": "frame_time_ms",
                }.get(file.decoder, "frame_index")
                location = {
                    "extraction_id": str(file.extraction_id),
                    position: file.index,
                    "source_pixel_bounds": list(file.bbox) if file.bbox else None,
                }
            return VisionFrame(clean.width, clean.height, png, location)
    except (
        OSError,
        EOFError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        raise _invalid("画面格式或字节无效") from exc


async def prepare_vision_frame(
    source: MediaSource | FileVisualSource,
    part: SourceMediaInput,
    store: ObjectStore,
) -> VisionFrame:
    """No open DB transaction. Verify size and original digest before decoding."""
    limit = (
        MAX_SOURCE_BYTES
        if isinstance(source, FileVisualSource)
        else (MAX_MEDIA_INPUT_BYTES if source.artifact_type == "video" else MAX_IMAGE_INPUT_BYTES)
    )
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
        return await anyio.to_thread.run_sync(_prepare, path, source, part.transform)
