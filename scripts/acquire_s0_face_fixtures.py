#!/usr/bin/env python3
"""Materialize ignored S0-A images from pinned InsightFace test assets."""

from __future__ import annotations

import io
import subprocess
import urllib.request
from pathlib import Path

from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "images" / "character_canonical"
UPSTREAM_URL = "https://github.com/deepinsight/insightface.git"
UPSTREAM_COMMIT = "1456819742fd09bc4ad5293856a143a3e807c78e"
SOURCE_DIR = REPO_ROOT / "tmp" / "insightface-source"

# Keys intentionally match the existing desensitized fixture manifest.
IDENTITY_SOURCES = {
    "biden": "cpp-package/inspireface/test_res/data/bulk/Rob_Lowe_0001.jpg",
    "men_1": "cpp-package/inspireface/test_res/data/bulk/Nathalie_Baye_0002.jpg",
    "men_10": "cpp-package/inspireface/test_res/data/search/Mary_Katherine_Smart_0001_5k.jpg",
    "men_11": "cpp-package/inspireface/test_res/data/search/Teresa_Williams_0001_1k.jpg",
    "men_13": "cpp-package/inspireface/test_res/data/bulk/r0.jpg",
    "men_14": "cpp-package/inspireface/test_res/data/bulk/woman.png",
    "men_15": "cpp-package/inspireface/test_res/data/bulk/yifei.jpg",
    "men_16": "cpp-package/inspireface/test_res/data/bulk/kun.jpg",
    "men_17": "cpp-package/inspireface/test_res/data/bulk/jntm.jpg",
    "men_18": "cpp-package/inspireface/test_res/data/attribute/1423.jpg",
    "men_19": "cpp-package/inspireface/test_res/data/bulk/face_sample.png",
    "men_2": "cpp-package/inspireface/test_res/data/bulk/woman_search.jpeg",
    "men_20": "cpp-package/inspireface/test_res/data/bulk/image_T1.jpeg",
}
NO_FACE_SOURCE = "cpp-package/inspireface/test_res/data/crop/no_face.png"


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def ensure_source_checkout() -> Path:
    if not SOURCE_DIR.is_dir():
        SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--filter=blob:none", UPSTREAM_URL, str(SOURCE_DIR))
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{UPSTREAM_COMMIT}^{{commit}}"],
        cwd=SOURCE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not present:
        run("git", "fetch", "--depth=1", "origin", UPSTREAM_COMMIT, cwd=SOURCE_DIR)
    run("git", "checkout", "--detach", UPSTREAM_COMMIT, cwd=SOURCE_DIR)
    return SOURCE_DIR


def source_image(repo: Path, source_path: str):
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{UPSTREAM_COMMIT}:{source_path}"], cwd=repo
        )
    except subprocess.CalledProcessError:
        url = (
            "https://raw.githubusercontent.com/deepinsight/insightface/"
            f"{UPSTREAM_COMMIT}/{source_path}"
        )
        with urllib.request.urlopen(url, timeout=60) as response:  # nosec B310: pinned HTTPS URL
            raw = response.read()
    with Image.open(io.BytesIO(raw)) as opened:
        return opened.convert("RGB")


def write_image(path: Path, image) -> None:
    image.save(path, format="JPEG", quality=95)


def center_crop(image):
    width, height = image.size
    inset_x = max(1, int(width * 0.06))
    inset_y = max(1, int(height * 0.06))
    return image.crop((inset_x, inset_y, width - inset_x, height - inset_y))


def main() -> int:
    source = ensure_source_checkout()
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for sample_id, source_path in IDENTITY_SOURCES.items():
        image = source_image(source, source_path)
        write_image(FIXTURE_DIR / f"{sample_id}_v00.jpg", image)
        write_image(FIXTURE_DIR / f"{sample_id}_v00_flip.jpg", image.transpose(Image.Transpose.FLIP_LEFT_RIGHT))
        write_image(FIXTURE_DIR / f"{sample_id}_v00_crop.jpg", center_crop(image))

    no_face = source_image(source, NO_FACE_SOURCE)
    for index in range(5):
        write_image(FIXTURE_DIR / f"anom_noface_{index:02d}.jpg", no_face)
        blurred = no_face.filter(ImageFilter.GaussianBlur(radius=index + 1))
        write_image(FIXTURE_DIR / f"anom_lowq_{index:02d}.jpg", blurred)

    print(f"materialized {len(IDENTITY_SOURCES) * 3 + 10} ignored S0-A fixture images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
