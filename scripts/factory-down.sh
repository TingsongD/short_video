#!/usr/bin/env bash
# Stop the local factory stack started by factory-up.sh.
# Scoped to this checkout: kills only PIDs recorded in .run/*.pid whose
# command line still runs THIS checkout's .venv python, plus orphans
# matching that absolute path. Workers or APIs from another checkout
# (e.g. a sibling repo) are never matched — no bare module-name pkill.
# The hypit runtime down only touches this project's .hypit profile.
set -u
cd "$(dirname "$0")/.."
ROOT="$PWD"
PYBIN="$ROOT/.venv/bin/python"

stop_component() {
  # $1 = label (api|worker), $2 = process marker (serve|worker)
  local label="$1" marker="$2" pidfile=".run/$1.pid"
  local pid="" stopped=""
  pid=$(cat "$pidfile" 2>/dev/null || true)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    if ps -p "$pid" -o command= 2>/dev/null | grep -q "$PYBIN.*$marker"; then
      kill "$pid" 2>/dev/null && stopped=1
    else
      echo "  $label: pidfile $pid is not this checkout's process — left alone"
    fi
  fi
  rm -f "$pidfile"
  # Orphans of this checkout (pidfile lost) still carry the venv path.
  for orphan in $(pgrep -f "$PYBIN -m modules.factory.cli $marker" || true); do
    kill "$orphan" 2>/dev/null && stopped=1
  done
  [ -n "$stopped" ] && echo "  $label: stopped" || echo "  $label: none"
}

stop_component api serve
stop_component worker worker
./scripts/hypit.sh programs down 2>/dev/null || true
./scripts/hypit.sh runtime down 2>/dev/null || true
sleep 1
left=$(pgrep -fl "$PYBIN -m modules.factory.cli" || true)
[ -z "$left" ] && echo "all factory processes for this checkout stopped" \
  || { echo "still running:"; echo "$left"; }
