"""Resolve visual file fragments from the current immutable extraction only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.source_models import SourceExtraction, SourceFragment
from app.assets.source_processors import images, media, pdf
from app.shared.errors import NotFoundError, ValidationAppError
from app.shared.vision import FileVisionInput


@dataclass(frozen=True)
class FileVisualSource:
    extraction_id: UUID
    object_key: str
    byte_size: int
    decoder: str
    index: int
    bbox: tuple[int, int, int, int] | None
    image_size: tuple[int, int] | None


def _invalid() -> ValidationAppError:
    return ValidationAppError(
        "此片段没有可核对的画面定位", details={"code": "VISION_FRAGMENT_INVALID"}
    )


def _index(locator: dict[str, object], key: str) -> int:
    value = locator.get(key)
    if type(value) is not int or value < 0:
        raise _invalid()
    return value


async def resolve_file_visual(
    session: AsyncSession,
    project_id: UUID,
    part: FileVisionInput,
    *,
    lock: bool = False,
) -> FileVisualSource:
    query = (
        select(ProjectFileRevision, SourceExtraction, SourceFragment)
        .select_from(ProjectFile)
        .join(ProjectFileRevision, ProjectFileRevision.file_id == ProjectFile.id)
        .join(SourceExtraction, SourceExtraction.id == ProjectFileRevision.current_extraction_id)
        .join(SourceFragment, SourceFragment.extraction_id == SourceExtraction.id)
        .where(
            ProjectFile.project_id == project_id,
            ProjectFile.detached_at.is_(None),
            ProjectFile.content_version == ProjectFileRevision.number,
            ProjectFileRevision.id == part.file_revision_id,
            ProjectFileRevision.project_id == project_id,
            ProjectFileRevision.status == "parsed",
            SourceExtraction.project_id == project_id,
            SourceExtraction.file_revision_id == part.file_revision_id,
            SourceExtraction.file_id == ProjectFile.id,
            SourceExtraction.attempt == ProjectFileRevision.attempt,
            SourceExtraction.extraction_schema_version == 2,
            SourceFragment.project_id == project_id,
            SourceFragment.file_revision_id == part.file_revision_id,
            SourceFragment.id == part.source_fragment_id,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update(read=True, of=[ProjectFile, ProjectFileRevision])
    result = (await session.execute(query)).one_or_none()
    if result is None:
        raise NotFoundError("文件或片段已变更，请在资料页重新选择")
    revision, extraction, fragment = result
    if revision.content_hash != part.expected_content_hash:
        raise _invalid()
    locator = fragment.locator
    box = None
    image_size = None
    if fragment.extraction_method == "ocr":
        bbox = locator.get("bbox")
        if not isinstance(bbox, dict):
            raise _invalid()
        x, y, w, h = (_index(bbox, k) for k in ("x", "y", "width", "height"))
        if w == 0 or h == 0:
            raise _invalid()
        box = (x, y, x + w, y + h)
    elif fragment.extraction_method == "visual_input":
        w, h = _index(locator, "image_width"), _index(locator, "image_height")
        if w == 0 or h == 0 or locator.get("bbox") != {"x": 0, "y": 0, "width": w, "height": h}:
            raise _invalid()
    suffix = Path(revision.filename).suffix.lower()
    if (
        extraction.parser_key == pdf.PARSER_KEY
        and suffix == ".pdf"
        and fragment.locator_kind == "page_region"
        and fragment.extraction_method in {"native_text", "ocr"}
    ):
        decoder = "pdf"
        index = _index(locator, "page_start")
        if locator.get("page_end") != index + 1 or (
            box and locator.get("raster_dpi") != pdf.RASTER_DPI
        ):
            raise _invalid()
    elif fragment.locator_kind == "image_region" and fragment.extraction_method in {
        "visual_input",
        "ocr",
    }:
        if extraction.parser_key == images.PARSER_KEY and suffix in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".tif",
            ".tiff",
        }:
            decoder = {
                ".png": "PNG",
                ".jpg": "JPEG",
                ".jpeg": "JPEG",
                ".webp": "WEBP",
                ".tif": "TIFF",
                ".tiff": "TIFF",
            }[suffix]
            index = _index(locator, "frame")
            image_size = (_index(locator, "image_width"), _index(locator, "image_height"))
        elif extraction.parser_key == media.PARSER_KEY and suffix in media.VIDEO_EXTENSIONS:
            decoder = "matroska" if suffix == ".mkv" else "mov"
            index = _index(locator, "time_ms")
        else:
            raise _invalid()
    else:
        raise _invalid()
    if part.transform.frame_time_ms is not None and (
        decoder not in {"matroska", "mov"} or part.transform.frame_time_ms != index
    ):
        raise _invalid()
    return FileVisualSource(
        extraction.id, revision.object_key, revision.byte_size, decoder, index, box, image_size
    )
