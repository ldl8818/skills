#!/usr/bin/env node

import { access, readFile, realpath } from 'node:fs/promises'
import { constants } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

async function findExecutable(name) {
  for (const directory of (process.env.PATH || '').split(path.delimiter)) {
    if (!directory) continue
    const candidate = path.join(directory, name)
    try {
      await access(candidate, constants.X_OK)
      return realpath(candidate)
    } catch {
      // Continue to the next PATH entry.
    }
  }
  throw new Error(`${name} is not executable on PATH`)
}

async function findOwningPackage(entry) {
  let directory = path.dirname(entry)
  while (true) {
    const packageJson = path.join(directory, 'package.json')
    try {
      const manifest = JSON.parse(await readFile(packageJson, 'utf8'))
      const declaredBin = typeof manifest.bin === 'string' ? manifest.bin : manifest.bin?.opencli
      if (declaredBin) {
        const declaredEntry = await realpath(path.resolve(directory, declaredBin))
        if (declaredEntry === entry) return { packageJson }
      }
    } catch {
      // This directory is not the package which owns the resolved executable.
    }
    const parent = path.dirname(directory)
    if (parent === directory) break
    directory = parent
  }
  throw new Error('Cannot locate the package.json which declares the resolved opencli executable')
}

const upstreamSeconds = Number(process.env.OPENCLI_BROWSER_COMMAND_TIMEOUT || 30)
const configuredMs = Number(process.env.OPENCLI_RUN_HARD_TIMEOUT_MS)
const timeoutMs = Number.isFinite(configuredMs) && configuredMs > 0
  ? configuredMs
  : (Number.isFinite(upstreamSeconds) && upstreamSeconds > 0 ? upstreamSeconds + 2 : 32) * 1000
const timer = setTimeout(() => {
  console.error(`OPENCLI_RUN_TIMEOUT: operation exceeded ${timeoutMs}ms`)
  process.exit(75)
}, timeoutMs)

try {
  const entry = await findExecutable('opencli')
  const { packageJson } = await findOwningPackage(entry)
  const requireFromOpenCli = createRequire(packageJson)
  const commanderUrl = pathToFileURL(requireFromOpenCli.resolve('commander')).href
  const commanderModule = await import(commanderUrl)
  const Command = commanderModule.Command ?? commanderModule.default?.Command
  if (!Command?.prototype?.parseAsync) {
    throw new Error('OpenCLI resolved a Commander build without Command.parseAsync')
  }
  const parseAsync = Command.prototype.parseAsync
  let pendingParse

  // OpenCLI 1.8.6-1.8.8 starts async browser actions with parse(), so Node can
  // exit 0 before stdout is rendered. Keep the installed package untouched and
  // await the same Commander action from this process. Remove after upstream
  // switches runCli() to parseAsync() and the regression below stays green.
  Command.prototype.parse = function parseAndRetain(argv, options) {
    pendingParse = parseAsync.call(this, argv, options)
    return this
  }

  process.argv = [process.execPath, entry, ...process.argv.slice(2)]
  await import(pathToFileURL(entry).href)
  if (pendingParse) {
    await pendingParse
  }
} finally {
  clearTimeout(timer)
}
