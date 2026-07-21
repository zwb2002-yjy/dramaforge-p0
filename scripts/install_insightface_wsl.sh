#!/usr/bin/env bash
# Install InsightFace + ONNX into formal WSL venv for P0 face gate.
set -euo pipefail
VENV="${HOME}/.cache/dramaforge-venv"
PYTHON="${VENV}/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  python3 -m venv "$VENV"
  PYTHON="${VENV}/bin/python"
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"
pip install -U pip setuptools wheel
pip install "insightface>=0.7" onnxruntime opencv-python-headless pillow numpy
python - <<'PY'
import insightface
print("insightface", insightface.__version__)
from insightface.app import FaceAnalysis
app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
app.prepare(ctx_id=-1, det_size=(640, 640))
print("buffalo_l_ready")
PY
