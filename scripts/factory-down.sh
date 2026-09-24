#!/usr/bin/env bash
# Stop the local factory stack started by factory-up.sh.
# Scoped to this checkout: kills only PIDs recorded in .run/*.pid whose
# interpreter and working directory match this checkout, plus matching
# orphans (even with a resolved system Python). Processes in another checkout
# (e.g. a sibling repo) are never matched — no bare module-name pkill.
# The hypit runtime down only touches this project's .hypit profile.
set -u
cd "$(dirname "$0")/.."
ROOT="$PWD"
PYBIN="$ROOT/.venv/bin/python"

stop_component() {
  # $1 = label (api|worker), $2 = process marker (serve|worker)
  local label="$1" marker="$2" pidfile=".run/$1.pid"
  local stopped=""
  stopped=$("$PYBIN" -m modules.factory.operations.processes "$ROOT" "$marker" --stop) || return 1
  rm -f "$pidfile"
  [ -n "$stopped" ] && echo "  $label: stopped" || echo "  $label: none"

}

stop_component api serve
stop_component worker worker
./scripts/hypit.sh programs down 2>/dev/null || true
./scripts/hypit.sh runtime down 2>/dev/null || true
sleep 1
left=$("$PYBIN" -m modules.factory.operations.processes "$ROOT" serve
       "$PYBIN" -m modules.factory.operations.processes "$ROOT" worker)
[ -z "$left" ] && echo "all factory processes for this checkout stopped" \
  || { echo "still running:"; echo "$left"; }
