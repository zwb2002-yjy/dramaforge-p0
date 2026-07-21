#!/usr/bin/env bash
# Print only JSON insightface_status (no download side effects if models present).
set -euo pipefail
source "${HOME}/.cache/dramaforge-venv/bin/activate"
export PYTHONPATH="/mnt/d/调研/dramaforge/backend"
python /mnt/d/调研/dramaforge/scripts/check_insightface.py
