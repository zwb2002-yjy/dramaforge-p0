#!/usr/bin/env bash
set -euo pipefail
MODELS="${HOME}/.insightface/models"
ZIP="${MODELS}/buffalo_l.zip"
DEST="${MODELS}/buffalo_l"
mkdir -p "${MODELS}"
if [[ ! -f "${ZIP}" ]]; then
  echo "missing ${ZIP}" >&2
  exit 1
fi
rm -rf "${DEST}"
mkdir -p "${DEST}"
python3 - <<PY
import zipfile
from pathlib import Path
z = Path("${ZIP}")
print("zip_size", z.stat().st_size)
with zipfile.ZipFile(z) as zf:
    zf.extractall("${DEST}")
print("extracted", list(Path("${DEST}").rglob("*.onnx"))[:10])
PY
# If nested buffalo_l/buffalo_l, flatten
if [[ -d "${DEST}/buffalo_l" ]]; then
  shopt -s dotglob
  mv "${DEST}/buffalo_l"/* "${DEST}/" || true
  rmdir "${DEST}/buffalo_l" 2>/dev/null || true
fi
ls -la "${DEST}"
source "${HOME}/.cache/dramaforge-venv/bin/activate"
export PYTHONPATH="/mnt/d/调研/dramaforge/backend"
python - <<'PY'
from app.consistency.image_embed import insightface_status, embedding_from_image_bytes
from pathlib import Path
import json
st = insightface_status()
print(json.dumps(st, indent=2))
if st.get("available"):
    # smoke: embed a fixture face if present
    p = Path("/mnt/d/调研/dramaforge/fixtures/images/character_canonical")
    jpg = next(p.glob("*.jpg"), None)
    if jpg:
        emb = embedding_from_image_bytes(jpg.read_bytes())
        print("embedding_len", len(emb), "norm_ok", abs(sum(x*x for x in emb)-1.0) < 1e-3)
PY
