#!/usr/bin/env bash
# Start the full local factory stack with one command:
#   hypit runtime (whisperx.local + media.local + hyperframes.local programs)
#   factory API on :8100
#   one factory worker (a second worker races BEGIN IMMEDIATE — never run two)
# Logs go to .run/*.log, pids to .run/*.pid. Safe to re-run: running
# services are left alone.
#
# Workspace scoping: processes are launched via this checkout's absolute
# .venv path, so their command lines contain the checkout directory.
# All liveness/pgrep checks match on that absolute path — another
# checkout's factory processes never match.
set -u
umask 077
cd "$(dirname "$0")/.."
ROOT="$PWD"
PYBIN="$ROOT/.venv/bin/python"
# Worker/API logs are redirected files; without unbuffered stdio they
# can stay empty for the life of a long live run.
export PYTHONUNBUFFERED=1
mkdir -p .run

pid_alive() {
  # alive && cmdline belongs to THIS checkout's venv
  local pid="$1" want="$2"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o command= 2>/dev/null | grep -q "$PYBIN.*$want"
}
scoped_pgrep() { pgrep -f "$PYBIN -m modules.factory.cli $1" || true; }

echo "== hypit runtime (local programs) =="
./scripts/hypit.sh runtime up || echo "  (runtime up reported issues; programs status below shows what is live)"

echo "== factory api + worker =="
api_pid=$(cat .run/api.pid 2>/dev/null || true)
if pid_alive "$api_pid" "serve" || [ -n "$(scoped_pgrep serve)" ]; then
  echo "  api:    already running"
else
  nohup "$PYBIN" -m modules.factory.cli serve --port 8100 >/dev/null 2>&1 &
  echo $! > .run/api.pid
  disown
  echo "  api:    started (pid $(cat .run/api.pid)) -> .run/api.log"
fi
worker_pid=$(cat .run/worker.pid 2>/dev/null || true)
if pid_alive "$worker_pid" "worker" || [ -n "$(scoped_pgrep worker)" ]; then
  echo "  worker: already running (only one may run)"
else
  nohup "$PYBIN" -m modules.factory.cli worker >/dev/null 2>&1 &
  worker_pid=$!
  echo "$worker_pid" > .run/worker.pid
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
