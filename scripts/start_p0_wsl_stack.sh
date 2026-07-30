#!/usr/bin/env bash
# Formal non-Docker P0 stack inside WSL:
#   PostgreSQL + Redis + MinIO + API + Arq default/heavy workers + Outbox dispatcher
# Windows only runs the frontend (Vite :5173).
#
# Usage:
#   bash scripts/start_p0_wsl_stack.sh start
#   bash scripts/start_p0_wsl_stack.sh stop
#   bash scripts/start_p0_wsl_stack.sh status
#
# Formal path MUST NOT set DRAMA_FORCE_MEMORY_STORE=1.
set -euo pipefail

ACTION="${1:-start}"
API_PORT="${2:-8010}"
FE_PORT="${3:-5173}"
SCRIPT="$(readlink -f "$0" 2>/dev/null || realpath "$0")"
REPO="$(cd "$(dirname "$SCRIPT")/.." && pwd -P)"
if [[ ! -d "${REPO}/backend" && -d "/mnt/d/dramaforge/backend" ]]; then
  REPO="/mnt/d/dramaforge"
fi
VENV="${HOME}/.cache/dramaforge-venv"
PYTHON="${VENV}/bin/python"
RUN_DIR="${HOME}/.cache/dramaforge-run"
LOG_DIR="${RUN_DIR}/logs"
PID_DIR="${RUN_DIR}/pids"
MINIO_DATA="${RUN_DIR}/minio-data"
MINIO_BIN="${RUN_DIR}/minio"

mkdir -p "${LOG_DIR}" "${PID_DIR}" "${MINIO_DATA}"

log() { echo "[stack] $*"; }

bind_source_commit() {
  local status
  status="$(git -C "${REPO}" status --porcelain=v1 --untracked-files=normal)"
  if [[ -n "${status}" ]]; then
    echo "Formal stack requires a clean worktree; commit or remove local changes first." >&2
    git -C "${REPO}" status --short >&2
    exit 1
  fi
  SOURCE_COMMIT="$(git -C "${REPO}" rev-parse HEAD)"
  if [[ -z "${SOURCE_COMMIT}" ]]; then
    echo "Could not resolve source commit for ${REPO}" >&2
    exit 1
  fi
  export DRAMAFORGE_SOURCE_COMMIT="${SOURCE_COMMIT}"
}

load_formal_env() {
  if [[ -f "${REPO}/.env" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%$'\r'}"
      case "$line" in
        ""|\#*) continue ;;
      esac
      key="${line%%=*}"
      value="${line#*=}"
      # Never inherit memory-store override for formal stack
      if [[ "$key" == "DRAMA_FORCE_MEMORY_STORE" ]]; then
        continue
      fi
      export "${key}=${value}" 2>/dev/null || true
    done < "${REPO}/.env"
  fi

  export APP_ENV="development"
  export DATABASE_URL="postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"
  export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
  export ARQ_HEAVY_MAX_JOBS="${ARQ_HEAVY_MAX_JOBS:-4}"
  export MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://127.0.0.1:9000}"
  export MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
  export MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"
  export MINIO_BUCKET="${MINIO_BUCKET:-dramaforge}"
  export MINIO_REGION="${MINIO_REGION:-us-east-1}"
  export PYTHONPATH="${REPO}/backend"
  export CORS_ORIGINS="http://localhost:${FE_PORT},http://127.0.0.1:${FE_PORT}"
  export SESSION_SECRET="${SESSION_SECRET:-dev-only-change-me-to-a-long-random-string}"
  export BYOK_FERNET_KEY="${BYOK_FERNET_KEY:-dev-only-fernet-key-replace-in-prod==}"
  if command -v espeak-ng >/dev/null 2>&1; then
    export TTS_ENABLED="true"
    export TTS_ENGINE="espeak-ng"
    export TTS_VOICE="${TTS_VOICE:-zh}"
  else
    export TTS_ENABLED="false"
  fi
  # Explicitly unset memory force for formal path
  unset DRAMA_FORCE_MEMORY_STORE || true
  export DRAMA_FORCE_MEMORY_STORE=""
}

ensure_postgres() {
  if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    return
  fi
  sudo pg_ctlcluster 16 main start 2>/dev/null || sudo service postgresql start 2>/dev/null || true
  for _ in $(seq 1 20); do
    pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1 && return
    sleep 1
  done
  echo "PostgreSQL not ready on 127.0.0.1:5432" >&2
  exit 1
}

ensure_redis() {
  if command -v redis-cli >/dev/null 2>&1 && redis-cli ping 2>/dev/null | grep -q PONG; then
    return
  fi
  if ! command -v redis-server >/dev/null 2>&1; then
    log "installing redis-server"
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq redis-server
  fi
  sudo service redis-server start 2>/dev/null || redis-server --daemonize yes
  for _ in $(seq 1 15); do
    redis-cli ping 2>/dev/null | grep -q PONG && return
    sleep 1
  done
  echo "Redis not ready" >&2
  exit 1
}

ensure_minio() {
  if curl -fsS --max-time 2 "http://127.0.0.1:9000/minio/health/live" >/dev/null 2>&1; then
    return
  fi
  if [[ ! -x "${MINIO_BIN}" ]]; then
    log "downloading MinIO binary (retries)"
    urls=(
      "https://dl.min.io/server/minio/release/linux-amd64/minio"
      "https://dl.minio.org.cn/server/minio/release/linux-amd64/minio"
    )
    ok=0
    for url in "${urls[@]}"; do
      if curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 180 \
        -o "${MINIO_BIN}.partial" "$url"; then
        mv "${MINIO_BIN}.partial" "${MINIO_BIN}"
        chmod +x "${MINIO_BIN}"
        ok=1
        break
      fi
    done
    if [[ "$ok" -ne 1 ]]; then
      # Fallback: if docker is available for image extract only (not required runtime)
      if command -v docker >/dev/null 2>&1; then
        log "extracting minio from docker image minio/minio"
        docker create --name df-minio-extract minio/minio >/dev/null 2>&1 || true
        docker cp df-minio-extract:/usr/bin/minio "${MINIO_BIN}" 2>/dev/null || \
          docker cp df-minio-extract:/minio "${MINIO_BIN}" 2>/dev/null || true
        docker rm -f df-minio-extract >/dev/null 2>&1 || true
        chmod +x "${MINIO_BIN}" 2>/dev/null || true
      fi
    fi
    if [[ ! -x "${MINIO_BIN}" ]]; then
      echo "MinIO binary unavailable (network/docker). Formal object store cannot start." >&2
      exit 1
    fi
  fi
  if [[ -f "${PID_DIR}/minio.pid" ]] && kill -0 "$(cat "${PID_DIR}/minio.pid")" 2>/dev/null; then
    return
  fi
  export MINIO_ROOT_USER="${MINIO_ACCESS_KEY:-minioadmin}"
  export MINIO_ROOT_PASSWORD="${MINIO_SECRET_KEY:-minioadmin}"
  nohup "${MINIO_BIN}" server "${MINIO_DATA}" --address ":9000" --console-address ":9001" \
    >"${LOG_DIR}/minio.log" 2>&1 &
  echo $! > "${PID_DIR}/minio.pid"
  for _ in $(seq 1 20); do
    curl -fsS --max-time 2 "http://127.0.0.1:9000/minio/health/live" >/dev/null 2>&1 && return
    sleep 1
  done
  echo "MinIO not ready; see ${LOG_DIR}/minio.log" >&2
  exit 1
}

ensure_ffmpeg() {
  if command -v ffmpeg >/dev/null 2>&1; then
    return
  fi
  # Keep formal export deterministic without requiring a privileged apt
  # install in WSL. Docker is only used to extract the pinned binary; runtime
  # still executes inside the WSL formal stack.
  if ! command -v docker >/dev/null 2>&1; then
    echo "FFmpeg unavailable: install ffmpeg or provide Docker for extraction." >&2
    exit 1
  fi
  if [[ ! -x "${RUN_DIR}/ffmpeg" ]]; then
    log "extracting FFmpeg binary from jrottenberg/ffmpeg:6.0-ubuntu"
    docker image inspect jrottenberg/ffmpeg:6.0-ubuntu >/dev/null 2>&1 || \
      docker pull jrottenberg/ffmpeg:6.0-ubuntu >/dev/null
    docker create --name df-ffmpeg-extract jrottenberg/ffmpeg:6.0-ubuntu >/dev/null
    docker cp df-ffmpeg-extract:/usr/local/bin/ffmpeg "${RUN_DIR}/ffmpeg"
    docker rm df-ffmpeg-extract >/dev/null
    chmod +x "${RUN_DIR}/ffmpeg"
  fi
  export PATH="${RUN_DIR}:${PATH}"
  command -v ffmpeg >/dev/null 2>&1 || {
    echo "FFmpeg extraction failed" >&2
    exit 1
  }
}

ensure_venv() {
  if [[ -x "${PYTHON}" ]]; then
    return
  fi
  python3 -m venv "${VENV}"
  "${PYTHON}" -m pip install --upgrade pip
  "${PYTHON}" -m pip install -e "${REPO}/backend"
}

run_migrations() {
  (
    cd "${REPO}/backend"
    "${PYTHON}" -m alembic -c alembic.ini upgrade head
  )
}

start_api() {
  if [[ -f "${PID_DIR}/api.pid" ]] && kill -0 "$(cat "${PID_DIR}/api.pid")" 2>/dev/null; then
    log "API already running pid=$(cat "${PID_DIR}/api.pid")"
    return
  fi
  # free port
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${API_PORT}/tcp" 2>/dev/null || true
  fi
  (
    cd "${REPO}/backend"
    nohup "${VENV}/bin/uvicorn" app.main:app --host 0.0.0.0 --port "${API_PORT}" \
      >"${LOG_DIR}/api.log" 2>&1 &
    echo $! > "${PID_DIR}/api.pid"
  )
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 "http://127.0.0.1:${API_PORT}/health" | grep -q '"db":"up"'; then
      log "API_READY port=${API_PORT}"
      return
    fi
    sleep 1
  done
  echo "API failed; see ${LOG_DIR}/api.log" >&2
  tail -40 "${LOG_DIR}/api.log" >&2 || true
  exit 1
}

start_arq_worker() {
  local kind="$1"  # default | heavy
  local unit="worker-${kind}"
  if [[ -f "${PID_DIR}/${unit}.pid" ]] && kill -0 "$(cat "${PID_DIR}/${unit}.pid")" 2>/dev/null; then
    log "${unit} already running"
    return
  fi
  local module="app.workers.default.WorkerSettings"
  if [[ "$kind" == "heavy" ]]; then
    module="app.workers.heavy.WorkerSettings"
  fi
  (
    cd "${REPO}/backend"
    nohup "${VENV}/bin/arq" "${module}" >"${LOG_DIR}/${unit}.log" 2>&1 &
    echo $! > "${PID_DIR}/${unit}.pid"
  )
  log "${unit} started pid=$(cat "${PID_DIR}/${unit}.pid")"
}

start_dispatcher() {
  if [[ -f "${PID_DIR}/dispatcher.pid" ]] && kill -0 "$(cat "${PID_DIR}/dispatcher.pid")" 2>/dev/null; then
    log "dispatcher already running"
    return
  fi
  cat > "${RUN_DIR}/outbox_dispatcher.py" <<'PY'
"""Resident Outbox → Arq dispatcher loop (formal stack)."""
from __future__ import annotations

import asyncio
import os
import sys
import time

REPO = os.environ.get("PYTHONPATH", "")
sys.path.insert(0, REPO.split(os.pathsep)[0] if REPO else ".")

from app.shared.model_registry import load_all_models

load_all_models()

async def once() -> int:
    from app.config import get_settings
    from app.runtime.scheduler import AgentRunScheduler, RedisStreamPublisher
    from app.shared.db import get_session_factory

    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        pub = RedisStreamPublisher(settings.redis_url)
        n = await AgentRunScheduler(session, publisher=pub).dispatch_pending(
            worker_id="resident-dispatcher"
        )
        return n

async def main() -> None:
    while True:
        try:
            n = await once()
            if n:
                print(f"dispatched={n}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"dispatcher_error={type(exc).__name__}:{exc}", flush=True)
        await asyncio.sleep(2.0)

if __name__ == "__main__":
    asyncio.run(main())
PY
  (
    cd "${REPO}/backend"
    nohup "${PYTHON}" "${RUN_DIR}/outbox_dispatcher.py" >"${LOG_DIR}/dispatcher.log" 2>&1 &
    echo $! > "${PID_DIR}/dispatcher.pid"
  )
  log "dispatcher started pid=$(cat "${PID_DIR}/dispatcher.pid")"
}

stop_pidfile() {
  local name="$1"
  if [[ -f "${PID_DIR}/${name}.pid" ]]; then
    local pid
    pid="$(cat "${PID_DIR}/${name}.pid")"
    kill "${pid}" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "${pid}" 2>/dev/null; then
      kill -9 "${pid}" 2>/dev/null || true
    fi
    rm -f "${PID_DIR}/${name}.pid"
    log "stopped ${name}"
  fi
}

stop_application_processes() {
  stop_pidfile dispatcher
  stop_pidfile worker-heavy
  stop_pidfile worker-default
  stop_pidfile api
}

do_stop() {
  stop_application_processes
  stop_pidfile minio
  log "STACK_STOPPED (PG/Redis left running as system services)"
}

do_status() {
  load_formal_env
  echo "REPO=${REPO}"
  echo "DRAMA_FORCE_MEMORY_STORE=${DRAMA_FORCE_MEMORY_STORE:-<unset>}"
  pg_isready -h 127.0.0.1 -p 5432 && echo "PG=ok" || echo "PG=down"
  redis-cli ping 2>/dev/null | grep -q PONG && echo "REDIS=ok" || echo "REDIS=down"
  curl -fsS --max-time 2 "http://127.0.0.1:9000/minio/health/live" >/dev/null 2>&1 && echo "MINIO=ok" || echo "MINIO=down"
  curl -fsS --max-time 2 "http://127.0.0.1:${API_PORT}/health" || echo "API=down"
  echo
  for n in api worker-default worker-heavy dispatcher minio; do
    if [[ -f "${PID_DIR}/${n}.pid" ]] && kill -0 "$(cat "${PID_DIR}/${n}.pid")" 2>/dev/null; then
      echo "PID ${n}=$(cat "${PID_DIR}/${n}.pid") alive"
    else
      echo "PID ${n}=dead"
    fi
  done
}

do_start() {
  load_formal_env
  bind_source_commit
  # Each formal stack run gets isolated Arq queues. Old Provider jobs can take
  # minutes or hours; reusing their queue would starve a fresh verification run
  # and make queued NodeRuns look like a Worker regression.
  local queue_suffix="${SOURCE_COMMIT:0:12}"
  export ARQ_DEFAULT_QUEUE_NAME="dramaforge:default:${queue_suffix}"
  export ARQ_HEAVY_QUEUE_NAME="dramaforge:heavy:${queue_suffix}"
  log "formal stack start REPO=${REPO}"
  log "SOURCE_COMMIT=${SOURCE_COMMIT}"
  log "ARQ_DEFAULT_QUEUE_NAME=${ARQ_DEFAULT_QUEUE_NAME}"
  log "ARQ_HEAVY_QUEUE_NAME=${ARQ_HEAVY_QUEUE_NAME}"
  log "DRAMA_FORCE_MEMORY_STORE=${DRAMA_FORCE_MEMORY_STORE:-<unset>} (must be empty)"
  ensure_postgres
  ensure_redis
  ensure_minio
  ensure_ffmpeg
  ensure_venv
  # Formal evidence cannot reuse API/Worker processes from an older checkout.
  stop_application_processes
  run_migrations
  start_api
  start_arq_worker default
  start_arq_worker heavy
  start_dispatcher
  do_status
  log "Windows: npm run dev in frontend only → http://127.0.0.1:${FE_PORT}/"
  log "API: http://127.0.0.1:${API_PORT}/health"
}

case "${ACTION}" in
  start) do_start ;;
  stop) do_stop ;;
  status) do_status ;;
  *)
    echo "usage: $0 {start|stop|status} [api-port] [fe-port]" >&2
    exit 2
    ;;
esac
