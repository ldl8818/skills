#!/usr/bin/env node
// Read-only ego-browser v2 diagnostic. Agent ownership is not session ownership.
// Legacy hook names intentionally do nothing, so old hook installations cannot
// close another task, launch a browser, write state, or block the user's turn.
// Finish a proven current TaskSpace in its original task using the installed
// ego-browser Skill. Do not recreate a cross-session garbage collector here.
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const pExecFile = promisify(execFile)
const localBin = path.join(os.homedir(), '.local', 'bin', 'ego-browser')
const egoBin = fs.existsSync(localBin) ? localBin : 'ego-browser'
const [command, ...args] = process.argv.slice(2)

async function running() {
  try {
    await pExecFile('pgrep', ['-f', 'ego lite.app/Contents/MacOS/'], {
      timeout: 1500, killSignal: 'SIGKILL', maxBuffer: 65536,
    })
    return true
  } catch { return false }
}

async function list() {
  if (!(await running())) throw new Error('EGO_NOT_RUNNING: start ego lite explicitly before listing spaces')
  const request = pExecFile(egoBin, ['nodejs'], {
    timeout: 20000, killSignal: 'SIGKILL', maxBuffer: 1024 * 1024,
  })
  // v2 lists spaces without resuming, claiming, or taking over any space.
  request.child.stdin.end('console.log("@@LOOKUP_SPACES@@" + JSON.stringify(await listTaskSpaces()))')
  const { stdout, stderr } = await request
  const marker = '@@LOOKUP_SPACES@@'
  const line = (stdout + '\n' + stderr).split('\n').map(value => value.trim())
    .filter(value => value.startsWith(marker)).at(-1)
  if (!line) throw new Error('EGO_LIST_RESULT_INVALID: no structured result; inspect the installed ego-browser Skill')
  const spaces = JSON.parse(line.slice(marker.length))
  if (!Array.isArray(spaces)) throw new Error('EGO_LIST_RESULT_INVALID: expected an array')
  return {
    mode: 'diagnostic',
    sessionOwnership: 'unknown',
    cleanupEligible: false,
    note: 'Agent ownership does not prove ownership by this session. Finish only a TaskSpace recorded by the original task.',
    spaces: spaces.map(space => ({
      id: space.spaceId ?? space.id,
      name: space.name ?? '',
      ownership: space.ownership ?? 'unknown',
      sessionOwnership: 'unknown',
      cleanupEligible: false,
    })),
  }
}

try {
  switch (command) {
    case 'hook-stop':
    case 'hook-session-start':
      // Safe compatibility for already-installed hooks. No stdin/transcript
      // reads, filesystem writes, browser calls, reminders, or decisions.
      break
    case 'list':
      if (args.length) throw new Error('Usage: ego-spaces.mjs list')
      console.log(JSON.stringify(await list(), null, 2))
      break
    case 'close':
    case 'keep':
    case 'unkeep':
      console.error('EGO_SESSION_OWNERSHIP_UNVERIFIED: legacy mutation disabled. Resume only the TaskSpace recorded by the original task and use the installed ego-browser v2 completion workflow.')
      process.exitCode = 78
      break
    default:
      console.error('Usage: ego-spaces.mjs list (read-only); legacy hook commands are inert')
      process.exitCode = 2
  }
} catch (error) {
  console.error(error?.killed
    ? 'EGO_LIST_TIMEOUT: diagnostic ended; no automatic retry or cleanup'
    : error?.message || String(error))
  process.exitCode = 1
}
