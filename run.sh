#!/usr/bin/env bash
# M11 orchestration entry point — see modules/orchestrate/__main__.py
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -m modules.orchestrate "$@"
