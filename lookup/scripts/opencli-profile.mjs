#!/usr/bin/env node
// A confirmed binding pins Browser Bridge routing independently of aliases/defaults.
import { readFileSync, realpathSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

function reject(code, message) {
  throw Object.assign(new Error(message), {code})
}
function readJson(path, required) {
  try {
    const value = JSON.parse(readFileSync(path, 'utf8'))
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error()
    return value
  } catch (error) {
    if (!required && error.code === 'ENOENT') return {}
    reject('OPENCLI_PROFILE_REJECTED', `Missing or invalid profile configuration: ${path}`)
  }
}
function validId(value) {
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(value)
}

export function resolveBinding(selectors = [], env = process.env) {
  const configRoot = env.XDG_CONFIG_HOME || join(homedir(), '.config')
  const binding = readJson(join(configRoot, 'lookup', 'opencli-binding.json'), true)
  if (binding.version !== 1 || binding.browser !== 'ego-lite' || !validId(binding.context_id)) {
    reject('OPENCLI_PROFILE_REJECTED', 'Confirm an actual ego-lite contextId in opencli-binding.json')
  }
  const transport = env.LOOKUP_OPENCLI_TRANSPORT ?? 'bridge'
  if (!['bridge', 'cdp'].includes(transport)) {
    reject('OPENCLI_TRANSPORT_REJECTED', 'LOOKUP_OPENCLI_TRANSPORT must be bridge or cdp')
  }
  if (transport === 'cdp') {
    let endpoint
    try { endpoint = new URL(env.OPENCLI_CDP_ENDPOINT ?? '') }
    catch { reject('OPENCLI_TRANSPORT_REJECTED', 'The CDP route requires a confirmed ego-lite endpoint') }
    if (!['http:', 'https:', 'ws:', 'wss:'].includes(endpoint.protocol)
        || !endpoint.hostname || endpoint.username || endpoint.password
        || env.OPENCLI_CDP_ENDPOINT !== binding.cdp_endpoint) {
      reject('OPENCLI_TRANSPORT_REJECTED', 'CDP endpoint must match the confirmed ego-lite binding')
    }
  } else if (env.OPENCLI_CDP_ENDPOINT) {
    reject('OPENCLI_TRANSPORT_REJECTED', 'Explicitly select the confirmed CDP route before setting an endpoint')
  }
  const profiles = readJson(join(env.OPENCLI_CONFIG_DIR || join(homedir(), '.opencli'),
    'browser-profiles.json'), false)
  const aliases = profiles.aliases ?? {}
  if (!aliases || typeof aliases !== 'object' || Array.isArray(aliases)) {
    reject('OPENCLI_PROFILE_REJECTED', 'Invalid OpenCLI aliases')
  }
  const selected = Object.hasOwn(env, 'LOOKUP_OPENCLI_PROFILE')
    ? env.LOOKUP_OPENCLI_PROFILE : binding.context_id
  for (const value of [binding.context_id, selected, ...selectors]) {
    const target = Object.hasOwn(aliases, value) ? aliases[value] : value
    if (!validId(value) || target !== binding.context_id) {
      reject('OPENCLI_PROFILE_REJECTED', 'Profile must resolve to the confirmed ego-lite contextId')
    }
  }
  return {profile: binding.context_id, browser: binding.browser, transport}
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { console.log(JSON.stringify(resolveBinding())) }
  catch (error) {
    console.error(JSON.stringify({error: {code: error.code, message: error.message},
      phase: 'entry', outcome_unknown: false, retryable: false}))
    process.exitCode = 78
  }
}
