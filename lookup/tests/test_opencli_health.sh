#!/usr/bin/env bash
# Offline, bounded fixtures only; never invokes a real browser or platform.
set -uo pipefail
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$TEST_DIR/test_runtime.py" "$@"
