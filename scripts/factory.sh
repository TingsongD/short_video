#!/usr/bin/env bash
# Viral Video Factory launcher — wraps `python -m modules.factory.cli`.
# Usage: scripts/factory.sh doctor|start|status|stop|drain|backup|restore ...
set -euo pipefail
cd "$(dirname "$0")/.."
# Absolute venv path: the process command line then carries this
# checkout's directory, so factory-up/down pidfile + scoped-pgrep
# matching never confuses it with another checkout's processes.
exec "$PWD/.venv/bin/python" -m modules.factory.cli --root . "$@"
