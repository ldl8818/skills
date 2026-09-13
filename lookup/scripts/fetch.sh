#!/usr/bin/env bash
# Fetch from the source locally; remote fallback belongs to Lookup routing.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
exec python3 "$SCRIPT_DIR/fetch_local.py" "$@"
