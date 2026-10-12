#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec node --test "$ROOT_DIR/tests/test_match_site.mjs"
