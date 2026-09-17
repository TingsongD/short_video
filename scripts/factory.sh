#!/usr/bin/env bash
# Viral Video Factory launcher — wraps `python -m modules.factory.cli`.
# Usage: scripts/factory.sh doctor|start|status|stop|drain|backup|restore ...
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m modules.factory.cli --root . "$@"
