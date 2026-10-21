#!/usr/bin/env bash
# Native doctor owns connection probing/startup; this facade validates its report.
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 - "$SELF_DIR" <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys

try:
    run = subprocess.run(['node', str(Path(sys.argv[1]) / 'opencli-run.mjs'), 'doctor'],
                         capture_output=True, text=True)
    if run.stderr:
        print(run.stderr, file=sys.stderr, end='')
    envelope = json.loads(run.stdout)
    report = envelope.get('data', {})
    ready = (run.returncode == 0 and envelope.get('ok') is True
             and report.get('daemonRunning') is True
             and report.get('extensionConnected') is True
             and report.get('connectivity', {}).get('ok') is True
             and not report.get('daemonStale') and not report.get('daemonFlaky')
             and not report.get('extensionFlaky'))
    print(json.dumps({'ok': ready, 'state': 'ready' if ready else 'not_ready',
                      'profile': os.environ.get('LOOKUP_OPENCLI_PROFILE', 'ego-lite'),
                      'report': report, 'error': envelope.get('error')}, ensure_ascii=False))
    sys.exit(0 if ready else 78)
except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
    print(json.dumps({'ok': False, 'state': 'invalid_health_report', 'error': type(error).__name__}))
    sys.exit(78)
PY
