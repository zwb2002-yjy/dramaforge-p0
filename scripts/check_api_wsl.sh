#!/usr/bin/env bash
curl -sS -w "\nHTTP=%{http_code}\n" http://127.0.0.1:8010/health || echo CURL_FAIL
ss -ltn 2>/dev/null | grep 8010 || true
if [ -f ~/.cache/dramaforge-api.pid ]; then
  pid=$(cat ~/.cache/dramaforge-api.pid)
  echo PID=$pid
  ps -p "$pid" -o pid,cmd 2>&1 || echo DEAD
fi
tail -5 ~/.cache/dramaforge-api.log 2>/dev/null || true
