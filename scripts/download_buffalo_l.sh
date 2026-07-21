#!/usr/bin/env bash
set -euo pipefail
MODELS="${HOME}/.insightface/models"
mkdir -p "${MODELS}"
cd "${MODELS}"
rm -f buffalo_l.zip
rm -rf buffalo_l
URL="https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
# Prefer ghproxy mirrors if direct fails
for u in \
  "$URL" \
  "https://ghproxy.net/$URL" \
  "https://mirror.ghproxy.com/$URL"
do
  echo "try $u"
  if curl -fL --retry 3 --retry-delay 2 --connect-timeout 30 --max-time 600 -o buffalo_l.zip "$u"; then
    break
  fi
  rm -f buffalo_l.zip
done
ls -la buffalo_l.zip
python3 - <<'PY'
import zipfile
from pathlib import Path
zpath = Path("buffalo_l.zip")
print("size", zpath.stat().st_size)
with zipfile.ZipFile(zpath) as zf:
    bad = zf.testzip()
    print("testzip", bad)
    if bad is not None:
        raise SystemExit(f"corrupt member {bad}")
    zf.extractall("buffalo_l")
# flatten if nested
import shutil
from pathlib import Path
root = Path("buffalo_l")
nested = root / "buffalo_l"
if nested.is_dir():
    for p in nested.iterdir():
        shutil.move(str(p), str(root / p.name))
    nested.rmdir()
print("onnx", list(root.rglob("*.onnx")))
PY
source "${HOME}/.cache/dramaforge-venv/bin/activate"
export PYTHONPATH="/mnt/d/调研/dramaforge/backend"
# Clear module-level InsightFace cache by new process
python - <<'PY'
import json
from app.consistency.image_embed import insightface_status, embedding_from_image_bytes
from pathlib import Path
st = insightface_status()
print(json.dumps(st, indent=2))
assert st.get("available") is True, st
assert st.get("backend") == "insightface+onnx", st
p = Path("/mnt/d/调研/dramaforge/fixtures/images/character_canonical")
jpg = next(p.glob("*.jpg"), None)
assert jpg is not None
emb = embedding_from_image_bytes(jpg.read_bytes())
assert len(emb) == 512
print("embedding_ok", len(emb))
PY
echo INSIGHTFACE_OK
