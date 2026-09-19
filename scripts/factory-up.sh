#!/usr/bin/env bash
# Start the full local factory stack with one command:
#   hypit runtime (whisperx.local + media.local + hyperframes.local programs)
#   factory API on :8100
#   one factory worker (a second worker races BEGIN IMMEDIATE — never run two)
# Logs go to .run/*.log. Safe to re-run: running services are left alone.
set -u
cd "$(dirname "$0")/.."
mkdir -p .run

echo "== hypit runtime (local programs) =="
./scripts/hypit.sh runtime up || echo "  (runtime up reported issues; programs status below shows what is live)"

echo "== factory api + worker =="
if pgrep -f "modules.factory.cli serve" >/dev/null; then
  echo "  api:    already running"
else
  nohup .venv/bin/python -m modules.factory.cli serve --port 8100 >> .run/api.log 2>&1 &
  disown
  echo "  api:    started (pid $!) -> .run/api.log"
fi
if pgrep -f "modules.factory.cli worker" >/dev/null; then
  echo "  worker: already running (only one may run)"
else
  nohup .venv/bin/python -m modules.factory.cli worker >> .run/worker.log 2>&1 &
  worker_pid=$!
  disown
  sleep 2
  if kill -0 "$worker_pid" 2>/dev/null; then
    echo "  worker: started (pid $worker_pid) -> .run/worker.log"
  else
    echo "  worker: EXITED within 2s of launch — check .run/worker.log" >&2
    tail -5 .run/worker.log >&2 || true
  fi
fi

echo "== waiting for api health =="
for _ in $(seq 1 40); do
  curl -sf -m 2 http://127.0.0.1:8100/api/health >/dev/null 2>&1 && break
  sleep 0.5
done
curl -s -m 2 http://127.0.0.1:8100/api/health || echo "api did not answer; check .run/api.log"
echo
./scripts/hypit.sh programs status 2>/dev/null | tail -8
echo "dashboard: http://127.0.0.1:8100/"
