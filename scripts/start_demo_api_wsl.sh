#!/bin/bash
set -uo pipefail
REPO=/mnt/d/调研/dramaforge
VENV=$HOME/.cache/dramaforge-venv
LOG=$HOME/.cache/dramaforge-api.log
PIDF=$HOME/.cache/dramaforge-api.pid
SUP=$HOME/.cache/dramaforge-api-supervisor.pid
mkdir -p $HOME/.cache
sudo pg_ctlcluster 16 main start || true

# stop old supervisor
if [ -f "$SUP" ]; then
  kill "$(cat $SUP)" 2>/dev/null || true
  rm -f "$SUP"
fi
if command -v fuser >/dev/null; then fuser -k 8010/tcp 2>/dev/null || true; fi

# load env
if [ -f "$REPO/.env" ]; then set -a; source "$REPO/.env"; set +a; fi
export APP_ENV=development
export DATABASE_URL=postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge
export DRAMA_FORCE_MEMORY_STORE=1
export PYTHONPATH=$REPO/backend
export CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
export SESSION_SECRET=${SESSION_SECRET:-dev-only-change-me-to-a-long-random-string}
export BYOK_FERNET_KEY=${BYOK_FERNET_KEY:-dev-only-fernet-key-replace-in-prod==}

start_api() {
  cd $REPO/backend
  : > "$LOG"
  setsid $VENV/bin/uvicorn app.main:app --host 0.0.0.0 --port 8010 >>"$LOG" 2>&1 < /dev/null &
  echo $! > "$PIDF"
  sleep 2
}

# supervisor loop in background
setsid bash -c '
  VENV='"$VENV"'; REPO='"$REPO"'; LOG='"$LOG"'; PIDF='"$PIDF"'
  export APP_ENV=development
  export DATABASE_URL=postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge
  export DRAMA_FORCE_MEMORY_STORE=1
  export PYTHONPATH=$REPO/backend
  export CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
  if [ -f '"$REPO"'/.env ]; then set -a; source '"$REPO"'/.env; set +a; fi
  export APP_ENV=development
  export DATABASE_URL=postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge
  export DRAMA_FORCE_MEMORY_STORE=1
  while true; do
    if ! curl -sf http://127.0.0.1:8010/health >/dev/null 2>&1; then
      sudo pg_ctlcluster 16 main start >/dev/null 2>&1 || true
      if command -v fuser >/dev/null; then fuser -k 8010/tcp 2>/dev/null || true; fi
      sleep 1
      cd $REPO/backend
      setsid $VENV/bin/uvicorn app.main:app --host 0.0.0.0 --port 8010 >>"$LOG" 2>&1 < /dev/null &
      echo $! > "$PIDF"
      sleep 3
    fi
    sleep 5
  done
' >/dev/null 2>&1 < /dev/null &
echo $! > "$SUP"
sleep 4
curl -sS http://127.0.0.1:8010/health || { echo FAIL; tail -30 $LOG; exit 1; }
echo
echo SUP=$(cat $SUP) API_PID=$(cat $PIDF)