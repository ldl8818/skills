#!/usr/bin/env node
// Lookup policy boundary; execution and async lifecycle belong to OpenCLI.
import { spawn, spawnSync } from 'node:child_process'

function fail(code, message) {
  console.error(JSON.stringify({error: {code, message}, phase: 'entry', outcome_unknown: false, retryable: false}))
  process.exit(78)
}
const args = process.argv.slice(2)
const options = args.slice(0, args.includes('--') ? args.indexOf('--') : args.length)
const profile = process.env.LOOKUP_OPENCLI_PROFILE ?? 'ego-lite'
if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(profile)) {
  fail('OPENCLI_PROFILE_REJECTED', 'LOOKUP_OPENCLI_PROFILE must name the intended profile')
}
function values(name) {
  return options.flatMap((arg, index) => arg === name ? [options[index + 1] ?? '']
    : arg.startsWith(name + '=') ? [arg.slice(name.length + 1)] : [])
}
if (values('--profile').some(value => value !== profile)) {
  fail('OPENCLI_PROFILE_REJECTED', '--profile must match LOOKUP_OPENCLI_PROFILE')
}
if (process.env.OPENCLI_CDP_ENDPOINT) {
  fail('OPENCLI_TRANSPORT_REJECTED', 'The selected profile uses Browser Bridge; unset OPENCLI_CDP_ENDPOINT')
}
if (process.env.OPENCLI_DAEMON_PORT?.trim()) {
  fail('OPENCLI_CONFIG_REJECTED', 'OpenCLI 2 no longer supports OPENCLI_DAEMON_PORT; remove the old setting')
}
const command = args.filter((arg, index) => arg !== '--profile' && !arg.startsWith('--profile=')
  && args[index - 1] !== '--profile' && arg !== '--')
const sites = values('--site')
if (command[0] === 'auth' && ['status', 'refresh'].includes(command[1])
    && !options.some(arg => ['--help', '-h'].includes(arg))
    && (!sites.length || sites.some(value => !value.split(',').some(site => site.trim())))) {
  fail('OPENCLI_AUTH_SITE_REQUIRED', 'Auth checks require an explicit --site list')
}
const budget = process.env.LOOKUP_OPENCLI_TIMEOUT_MS ?? '90000'
if (!/^[0-9]+$/.test(budget) || !Number.isSafeInteger(Number(budget))
    || Number(budget) < 1 || Number(budget) > 3600000) {
  fail('OPENCLI_RUN_CONFIG_INVALID', 'LOOKUP_OPENCLI_TIMEOUT_MS must be an integer from 1 to 3600000')
}
const env = {...process.env, OPENCLI_PROFILE: profile, OPENCLI_CLOSE_OWNED_TAB: '1'}
const started = Date.now()
const version = spawnSync('opencli', ['--version'], {
  env, encoding: 'utf8', timeout: Math.min(5000, Number(budget)), maxBuffer: 65536,
})
if (version.error || version.status !== 0) {
  fail('OPENCLI_VERSION_UNAVAILABLE', 'Cannot read the installed opencli --version')
}
const match = /^2\.(\d+)\.(\d+)\s*$/.exec(version.stdout)
if (!match || (Number(match[1]) === 0 && Number(match[2]) < 2)) {
  fail('OPENCLI_VERSION_UNSUPPORTED', 'Requires OpenCLI >=2.0.2 <3; qualify changed contracts before upgrading')
}
const remaining = Number(budget) - (Date.now() - started)
if (remaining <= 0) fail('OPENCLI_ENTRY_TIMEOUT', 'Budget exhausted before dispatch')
const child = spawn('opencli', args, {env, stdio: 'inherit', shell: false})
let stoppedCode
let killTimer
function stop(signal, code, reason) {
  if (stoppedCode) return
  stoppedCode = code
  console.error(JSON.stringify({error: {code: 'OUTCOME_UNKNOWN', original_code: reason,
    message: 'CLI stopped; browser work may continue. Inspect the original outcome before retrying.'},
  phase: 'action', outcome_unknown: true, retryable: false}))
  child.kill(signal)
  killTimer = setTimeout(() => child.kill('SIGKILL'), 500)
}
const timer = setTimeout(() => stop('SIGTERM', 75, 'OPENCLI_RUN_DEADLINE_EXCEEDED'), remaining)
for (const [signal, code] of [['SIGINT', 130], ['SIGTERM', 143], ['SIGHUP', 129]]) {
  process.on(signal, () => stop(signal, code, 'OPENCLI_RUN_INTERRUPTED'))
}
child.on('error', error => {
  clearTimeout(timer)
  clearTimeout(killTimer)
  fail('OPENCLI_START_FAILED', error.message)
})
child.on('close', (code, signal) => {
  clearTimeout(timer)
  clearTimeout(killTimer)
  process.exitCode = stoppedCode ?? code ?? (signal === 'SIGINT' ? 130 : signal === 'SIGHUP' ? 129 : 143)
})
