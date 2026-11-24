"""Verify the frozen restic release and install its Linux/amd64 binary in the image."""

import argparse
import base64
import bz2
import hashlib
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.request import urlopen

VERSION = "0.19.1"
ARCHIVE = f"restic_{VERSION}_linux_amd64.bz2"
DIGEST = "f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c"
SIGNER = "CF8F18F2844575973F79D4E191A6868BD3F7A907"


def install(target: Path, assets_dir: Path | None) -> None:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("the frozen maintenance binary requires Linux/amd64")
    with tempfile.TemporaryDirectory() as work:
        root = Path(work)
        assets = assets_dir or root
        if assets_dir is None:
            base = f"https://github.com/restic/restic/releases/download/v{VERSION}"
            for filename in (ARCHIVE, "SHA256SUMS", "SHA256SUMS.asc"):
                with (
                    urlopen(f"{base}/{filename}", timeout=90) as response,
                    (root / filename).open("xb") as stream,
                ):
                    shutil.copyfileobj(response, stream)
        # gpgv expects a binary OpenPGP keyring. The checked-in key is public ASCII armor.
        armor = Path(__file__).with_name("restic-release-key.asc").read_text("ascii")
        payload = "".join(line for line in armor.splitlines() if line and line[0] not in "-=")
        keyring = root / "release.gpg"
        keyring.write_bytes(base64.b64decode(payload, validate=True))
        signature = subprocess.run(
            [
                "gpgv",
                "--homedir",
                str(root),
                "--keyring",
                str(keyring),
                "--status-fd",
                "1",
                str(assets / "SHA256SUMS.asc"),
                str(assets / "SHA256SUMS"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if not any(
            line.startswith(f"[GNUPG:] VALIDSIG {SIGNER} ")
            for line in signature.stdout.splitlines()
        ):
            raise RuntimeError("unexpected restic release signer")
        entries = [line.split() for line in (assets / "SHA256SUMS").read_text("ascii").splitlines()]
        if [row[0] for row in entries if len(row) == 2 and row[1].lstrip("*") == ARCHIVE] != [
            DIGEST
        ]:
            raise RuntimeError("release manifest differs from the frozen checksum")
        with (assets / ARCHIVE).open("rb") as archive:
            if hashlib.file_digest(archive, "sha256").hexdigest() != DIGEST:
                raise RuntimeError("restic release checksum mismatch")
            archive.seek(0)
            with bz2.BZ2File(archive) as plain, target.open("xb") as output:
                shutil.copyfileobj(plain, output)
        target.chmod(0o755)
        subprocess.run([str(target), "version"], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument(
        "--assets-dir", type=Path, help="verified release inputs on offline build media"
    )
    args = parser.parse_args()
    install(args.target, args.assets_dir)
