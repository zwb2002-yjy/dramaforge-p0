"""File fragments keep their immutable extraction location during visual preparation."""

import io
import subprocess

import pytest
from app.assets.source_processors import ocr
from app.assets.vision_files import resolve_file_visual
from app.assets.vision_media import prepare_vision_frame
from app.shared.errors import NotFoundError, ValidationAppError
from app.shared.vision import FileVisionInput, VisionTransform
from PIL import Image
from test_project_files import sources as sources
from test_source_parser import _pdf_bytes


@pytest.mark.parametrize("fmt", ["tiff", "scanned_pdf", "video", "native_pdf"])
async def test_file_preview_uses_the_selected_page_frame_and_crop(
    session, sources, fmt, monkeypatch, tmp_path
):
    service, other = sources

    def fixed_line(image_path, *, language):
        with Image.open(image_path) as im:
            # Select an interior area of the right half of the actual OCR raster.
            x, y = im.width * 3 // 4, im.height // 4
        return [ocr.OcrLine("灯", x, y, 24, 12, 99, 1, 1, 1)], {"language": language}

    monkeypatch.setattr(ocr, "ocr_image", fixed_line)
    left = Image.new("RGB", (160, 80), "red")
    right = left.copy()
    right.paste("blue", (80, 0, 160, 80))
    buf = io.BytesIO()
    if fmt == "tiff":
        left.save(buf, "TIFF", save_all=True, append_images=[right])
        ext = "tiff"
    elif fmt == "scanned_pdf":
        left.save(buf, "PDF", save_all=True, append_images=[right])
        ext = "pdf"
    elif fmt == "native_pdf":
        buf.write(_pdf_bytes("Check this page"))
        ext = "pdf"
    else:
        path = tmp_path / "input.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=red:s=1600x160:d=1:r=10",
                "-vf",
                "drawbox=x=800:y=0:w=800:h=160:c=blue:t=fill",
                "-c:v",
                "libx264",
                str(path),
            ],
            check=True,
        )
        buf.write(path.read_bytes())
        ext = "mp4"
    rev = await service.upload(
        filename="test." + ext,
        data=buf.getvalue(),
        mime_type="application/octet-stream",
        request_key="visual",
    )
    parsed = await service.extract(rev.id)
    fragments, _ = await service.list_fragments(parsed.current_extraction_id)
    if fmt == "native_pdf":
        selected = fragments[0]
    else:
        selected = [f for f in fragments if f.extraction_method == "ocr"][-1]
    part = FileVisionInput(
        kind="file",
        file_revision_id=rev.id,
        source_fragment_id=selected.id,
        expected_content_hash=rev.content_hash,
    )
    src = await resolve_file_visual(session, service.project_id, part)
    frame = await prepare_vision_frame(src, part, service.store)
    if fmt != "native_pdf":
        pixels = Image.open(io.BytesIO(frame.png))
        assert pixels.size == (24, 12)
        r, g, b = pixels.getpixel((12, 6))
        assert b > 200 and r < 30 and g < 30
        narrower = part.model_copy(update={"transform": VisionTransform(crop=(0, 0, 0.5, 1))})
        assert (await prepare_vision_frame(src, narrower, service.store)).width == 12
    else:
        assert max(frame.width, frame.height) == 1024
    evidence = frame.evidence(part)
    assert evidence["extraction_id"] == str(parsed.current_extraction_id)
    assert evidence["source_fragment_id"] == str(selected.id)
    with pytest.raises(NotFoundError):
        await resolve_file_visual(session, other.project_id, part)
    with pytest.raises(ValidationAppError):
        await resolve_file_visual(
            session, service.project_id, part.model_copy(update={"expected_content_hash": "f" * 64})
        )
    if fmt == "video":
        bad = part.model_copy(update={"transform": VisionTransform(frame_time_ms=src.index + 20)})
        with pytest.raises(ValidationAppError):
            await resolve_file_visual(session, service.project_id, bad)
    parent, _ = await service.read_revision(rev.id)
    await service.unlink(parent.id, expected_version=parent.version)
    with pytest.raises(NotFoundError):
        await resolve_file_visual(session, service.project_id, part)
