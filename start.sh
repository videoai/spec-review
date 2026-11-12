#!/bin/sh
# Resolve the tool directory so this works from any current directory.
set -eu
tool_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.9 or newer is required. Install Python and try again.' >&2
  exit 1
fi
exec python3 "$tool_dir/server.py" --open "$@"
