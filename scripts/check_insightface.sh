#!/usr/bin/env bash
# Print only JSON insightface_status (no download side effects if models present).
set -euo pipefail
source "${HOME}/.cache/dramaforge-venv/bin/activate"
export PYTHONPATH="/mnt/d/dramaforge/backend"
python /mnt/d/dramaforge/scripts/check_insightface.py
