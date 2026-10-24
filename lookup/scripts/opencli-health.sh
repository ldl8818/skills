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

context = {'scope': 'bridge_profile', 'diagnostic_only': True, 'action_tested': False,
           'profile': None}

def emit(state, next_step, **details):
    ready = state == 'ready'
    print(json.dumps(dict(context, ok=ready, state=state, next_step=next_step, **details),
                     ensure_ascii=False))
    sys.exit(0 if ready else 78)

try:
    selection = subprocess.run(['node', str(Path(sys.argv[1]) / 'opencli-profile.mjs')],
                               capture_output=True, text=True, timeout=5)
    if selection.returncode != 0:
        error = json.loads(selection.stderr).get('error')
        emit('profile_rejected', 'confirm_ego_lite_binding', error=error)
    context.update(json.loads(selection.stdout))
    # A Bridge diagnostic cannot qualify a separately selected CDP transport.
    if context['transport'] == 'cdp':
        emit('not_applicable', 'validate_selected_transport')
    run = subprocess.run(['node', str(Path(sys.argv[1]) / 'opencli-run.mjs'), 'doctor'],
                         capture_output=True, text=True)
    if run.stderr:
        print(run.stderr, file=sys.stderr, end='')
    envelope = json.loads(run.stdout)
    report = envelope.get('data', {})
    details = {'report': report, 'error': envelope.get('error'), 'exit_code': run.returncode}
    if run.returncode != 0 or envelope.get('ok') is False:
        emit('doctor_failed', 'inspect_doctor_error', **details)
    if not isinstance(report, dict):
        raise ValueError('invalid report shape')
    connectivity = report.get('connectivity')
    reasons = []
    if report.get('daemonStale') is True:
        reasons.append('daemon_stale')
    if report.get('daemonFlaky') is True or report.get('extensionFlaky') is True:
        reasons.append('connection_unstable')
    if report.get('daemonRunning') is False:
        reasons.append('daemon_stopped')
    if report.get('extensionConnected') is False:
        reasons.append('profile_disconnected')
    if isinstance(connectivity, dict) and connectivity.get('ok') is False:
        reasons.append('connectivity_failed')
    if reasons:
        emit(reasons[0], 'inspect_connection_evidence', reason_codes=reasons, **details)
    # Unknown/malformed evidence must not become a disconnected-profile verdict.
    if (envelope.get('ok') is not True
            or not isinstance(report.get('daemonRunning'), bool)
            or not isinstance(report.get('extensionConnected'), bool)
            or not isinstance(connectivity, dict)
            or not isinstance(connectivity.get('ok'), bool)
            or any(name in report and not isinstance(report[name], bool)
                   for name in ('daemonStale', 'daemonFlaky', 'extensionFlaky'))):
        emit('diagnostic_inconclusive', 'run_target_action', **details)
    emit('ready', 'run_target_action', reason_codes=[], **details)
except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
    emit('invalid_health_report', 'inspect_doctor_error', error=type(error).__name__)
PY
