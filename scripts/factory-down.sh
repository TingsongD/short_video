#!/usr/bin/env bash
# Stop the local factory stack started by factory-up.sh.
# Scoped to this project: the hypit runtime down only touches this
# project's .hypit profile — it will not kill another repo's runtime.
set -u
cd "$(dirname "$0")/.."

pkill -f "modules.factory.cli worker" 2>/dev/null && echo "worker: stopped" || echo "worker: none"
pkill -f "modules.factory.cli serve" 2>/dev/null && echo "api:    stopped" || echo "api:    none"
./scripts/hypit.sh programs down 2>/dev/null || true
./scripts/hypit.sh runtime down 2>/dev/null || true
sleep 1
left=$(pgrep -fl "modules.factory.cli" || true)
[ -z "$left" ] && echo "all factory processes stopped" || { echo "still running:"; echo "$left"; }
