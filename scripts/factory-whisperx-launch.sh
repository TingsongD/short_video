#!/usr/bin/env bash
# Runtime serviceCommand, launched from the pinned local runtime's dataRoot.
set -euo pipefail
umask 077
factory_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" == Darwin ]]; then
  whisperx_host_root="$HOME/Library/Application Support/Hypit"
else
  whisperx_host_root="${XDG_DATA_HOME:-$HOME/.local/share}/Hypit"
fi
whisperx_program_root="${FACTORY_WHISPERX_PROGRAM_ROOT:-$whisperx_host_root/programs/whisperx-whisperx.local-127.0.0.1%3A8765}"
whisperx_python="$whisperx_program_root/.venv/bin/python"
if [[ ! -x "$whisperx_python" ]]; then
  echo 'Existing WhisperX environment missing; restore the pinned runtime before starting.' >&2
  exit 1
fi
exec "$whisperx_python" "$factory_root/scripts/factory-whisperx.py" \
  --port 8765 --model small --device cpu --compute int8 --batch-size 8 \
  --nltk-data "$whisperx_program_root/nltk_data"
