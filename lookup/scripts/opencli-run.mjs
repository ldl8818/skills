#!/usr/bin/env node
// Compatibility runner for the verified OpenCLI 1.8.6–1.8.8 sync parse() entry.
// Upgrade gate: re-read upstream runCli(), remove this workaround once its
// async lifecycle is fixed, and keep the delayed-result/unknown-outcome tests.
import { access, readFile, realpath } from 'node:fs/promises'
import { constants } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

function fail(code, message) {
  const error = new Error(message)
  error.lookupExitCode = code
  throw error
}

async function findExecutable(name) {
  for (const directory of (process.env.PATH || '').split(path.delimiter)) {
    if (!directory) continue
    try {
      const candidate = path.join(directory, name)
      await access(candidate, constants.X_OK)
      return await realpath(candidate)
    } catch { /* Continue to the next PATH entry. */ }
  }
  fail(78, 'OPENCLI_RUN_EXECUTABLE_MISSING: opencli is not executable on PATH')
}

async function findOwningPackage(entry) {
  let directory = path.dirname(entry)
  while (true) {
    const packageJson = path.join(directory, 'package.json')
    try {
      const manifest = JSON.parse(await readFile(packageJson, 'utf8'))
      const declaredBin = typeof manifest.bin === 'string' ? manifest.bin : manifest.bin?.opencli
      if (declaredBin && await realpath(path.resolve(directory, declaredBin)) === entry) {
        return { packageJson, manifest }
      }
    } catch { /* Continue to the owning package. */ }
    const parent = path.dirname(directory)
    if (parent === directory) break
    directory = parent
  }
  fail(78, 'OPENCLI_RUN_PACKAGE_UNVERIFIED: cannot identify the owning OpenCLI package')
}

function optionValues(argv, name) {
  const values = []
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === name) values.push(argv[index + 1] ?? '')
    else if (argv[index].startsWith(name + '=')) values.push(argv[index].slice(name.length + 1))
  }
  return values
}

function milliseconds(value, fallback, name) {
  if (value === undefined) return fallback
  if (!/^[0-9]+$/.test(value) || !Number.isSafeInteger(Number(value))
      || Number(value) < 1 || Number(value) > 3600000) {
    fail(78, 'OPENCLI_RUN_CONFIG_INVALID: ' + name + ' must be an integer from 1 to 3600000')
  }
  return Number(value)
}

let importTimer
let commandTimer
let restoreParse
let entryStarted = false
let dispatched = false
function emitLookupError(code, message, originalCode = code) {
  console.error(JSON.stringify({
    error: { code, original_code: originalCode, message },
    phase: dispatched ? 'action' : 'entry',
    outcome_unknown: entryStarted,
    retryable: false,
  }))
}
try {
  const args = process.argv.slice(2)
  const profile = process.env.LOOKUP_OPENCLI_PROFILE ?? 'ego-lite'
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(profile)) {
    fail(78, 'OPENCLI_PROFILE_REJECTED: LOOKUP_OPENCLI_PROFILE must name a configured profile alias')
  }
  if (optionValues(args, '--profile').some(value => value !== profile)) {
    fail(78, 'OPENCLI_PROFILE_REJECTED: --profile must match LOOKUP_OPENCLI_PROFILE (' + profile + ')')
  }
  if (process.env.OPENCLI_CDP_ENDPOINT) {
    fail(78, 'OPENCLI_TRANSPORT_REJECTED: unset OPENCLI_CDP_ENDPOINT; Lookup health verifies the extension transport only')
  }
  const daemonPort = process.env.OPENCLI_DAEMON_PORT ?? '19825'
  if (!/^[0-9]+$/.test(daemonPort) || Number(daemonPort) < 1 || Number(daemonPort) > 65535) {
    fail(78, 'OPENCLI_RUN_CONFIG_INVALID: OPENCLI_DAEMON_PORT must be from 1 to 65535')
  }
  process.env.OPENCLI_DAEMON_PORT = String(Number(daemonPort))
  // An inherited upstream profile must not silently override Lookup's gate.
  process.env.OPENCLI_PROFILE = profile

  const dispatchArgs = args.filter((arg, index) => arg !== '--profile'
    && !arg.startsWith('--profile=') && args[index - 1] !== '--profile')
  let index = dispatchArgs[0] === '--' ? 1 : 0
  const root = dispatchArgs[index++]
  if (root === 'auth' && dispatchArgs[index] === '--') index += 1
  if (root === 'auth' && ['status', 'refresh'].includes(dispatchArgs[index])) {
    const rawSites = optionValues(args, '--site').at(-1) || ''
    if (!rawSites.split(',').some(site => site.trim())) {
      fail(78, 'OPENCLI_AUTH_SITE_REQUIRED: lookup auth checks require an explicit --site list')
    }
  }

  const importTimeoutMs = milliseconds(
    process.env.OPENCLI_RUN_IMPORT_TIMEOUT_MS ?? process.env.OPENCLI_RUN_HARD_TIMEOUT_MS,
    15000, 'OPENCLI_RUN_IMPORT_TIMEOUT_MS')
  const totalTimeoutMs = milliseconds(process.env.LOOKUP_OPENCLI_TIMEOUT_MS, 90000, 'LOOKUP_OPENCLI_TIMEOUT_MS')
  importTimer = setTimeout(() => {
    emitLookupError(entryStarted ? 'OUTCOME_UNKNOWN' : 'ENTRY_TIMEOUT',
      'OPENCLI_RUN_IMPORT_TIMEOUT: no command dispatch within ' + importTimeoutMs
      + 'ms; outcome=' + (entryStarted ? 'unknown' : 'not_dispatched')
      + '; no automatic redispatch', 'OPENCLI_RUN_IMPORT_TIMEOUT')
    process.exit(75)
  }, importTimeoutMs)
  commandTimer = setTimeout(() => {
    emitLookupError(entryStarted ? 'OUTCOME_UNKNOWN' : 'ENTRY_TIMEOUT',
      'OPENCLI_RUN_DEADLINE_EXCEEDED: total deadline ' + totalTimeoutMs
      + 'ms; phase=' + (dispatched ? 'action' : 'entry')
      + '; outcome=' + (entryStarted ? 'unknown' : 'not_dispatched')
      + '; browser work may continue; inspect the original result before any retry',
      'OPENCLI_RUN_DEADLINE_EXCEEDED')
    process.exit(75)
  }, totalTimeoutMs)

  const entry = await findExecutable('opencli')
  const { packageJson, manifest } = await findOwningPackage(entry)
  let cliSource = ''
  try { cliSource = await readFile(path.join(path.dirname(entry), 'cli.js'), 'utf8') } catch {}
  const affectedVersion = manifest.name === '@jackwener/opencli' && /^1\.8\.[678]$/.test(manifest.version || '')
  const syncEntry = /export\s+function\s+runCli\s*\([^)]*\)\s*\{\s*createProgram\s*\([^)]*\)\.parse\(\);?\s*\}/.test(cliSource)
  if (!affectedVersion || !syncEntry) {
    fail(78, 'OPENCLI_RUN_COMPAT_UNVERIFIED: package/version/entry changed; requalify the runner before use (installed '
      + String(manifest.version || 'unknown') + '); retire the workaround after upstream awaits parseAsync')
  }

  const requireFromOpenCli = createRequire(packageJson)
  const commanderModule = await import(pathToFileURL(requireFromOpenCli.resolve('commander')).href)
  const Command = commanderModule.Command ?? commanderModule.default?.Command
  if (typeof Command?.prototype?.parseAsync !== 'function' || typeof Command.prototype.parse !== 'function') {
    fail(78, 'OPENCLI_RUN_COMPAT_UNVERIFIED: expected Commander parse/parseAsync APIs are unavailable')
  }
  const originalParse = Command.prototype.parse
  const originalParseAsync = Command.prototype.parseAsync
  let pendingParse
  Command.prototype.parse = function parseAndRetain(argv, options) {
    dispatched = true
    clearTimeout(importTimer)
    pendingParse = Promise.resolve(originalParseAsync.call(this, argv, options))
    pendingParse.catch(() => {}) // Preserve rejection for the awaited result below.
    return this
  }
  restoreParse = () => { Command.prototype.parse = originalParse }
  process.argv = [process.execPath, entry, ...args]
  entryStarted = true
  await import(pathToFileURL(entry).href)
  if (!pendingParse) fail(78, 'OPENCLI_RUN_COMPAT_UNVERIFIED: verified entry did not invoke Commander parse')
  await pendingParse
} catch (error) {
  const message = error?.message || String(error)
  if (error?.lookupExitCode !== undefined) emitLookupError(message.split(':', 1)[0], message)
  else console.error(message) // Preserve upstream's own diagnostics/format.
  process.exitCode = error?.lookupExitCode ?? 1
} finally {
  clearTimeout(importTimer)
  clearTimeout(commandTimer)
  restoreParse?.()
}
