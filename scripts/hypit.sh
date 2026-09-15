#!/usr/bin/env bash
# Run the project's pinned Hypit without changing its selected video workspace.
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hypit_entry="$project_root/vendor/hypit-runtime/node_modules/.bin/hypit"
if [[ ! -x "$hypit_entry" ]]; then
  echo 'Hypit is missing. Follow docs/jimeng-hypit-workflow.md to restore version 0.1.8.' >&2
  exit 127
fi
# Node reads NODE_OPTIONS in the worker and its disposable renderer children.
# A file URL safely carries project paths containing spaces; existing options remain.
bootstrap_url="$(node --input-type=module -e 'import {pathToFileURL} from "node:url"; console.log(pathToFileURL(process.argv[1]).href)' "$project_root/scripts/hypit-node-bootstrap.mjs")"
export NODE_OPTIONS="${NODE_OPTIONS:-} --import=$bootstrap_url"
exec "$hypit_entry" "$@"
