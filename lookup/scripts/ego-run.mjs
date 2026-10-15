#!/usr/bin/env node
// Bounded launcher for a single goal's owned lease. Never global cleanup.
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const [action, leasePath, label, workFile, profileId, ...extra] = process.argv.slice(2);
try {
  if (!leasePath || extra.length || !['run', 'finish'].includes(action)
      || (action === 'run' && (!label || !workFile))
      || (action === 'finish' && label)) throw new Error('Usage: ego-run.mjs run <lease> <label> <work.mjs> [profileId] | finish <lease>');
  const options = { leasePath: resolve(leasePath), label, profileId };
  const moduleUrl = new URL('./ego-task.mjs', import.meta.url).href;
  const marker = '@@LOOKUP_TASK@@';
  const script = `const { runOwnedTask, finishOwnedTask } = await import(${JSON.stringify(moduleUrl)});
const api = { taskSpace, listTaskSpaces };
const options = ${JSON.stringify(options)};
const result = ${action === 'run'
    ? `await runOwnedTask(api, options, (await import(${JSON.stringify(pathToFileURL(resolve(workFile)).href)})).default)`
    : 'await finishOwnedTask(api, options)'};
console.log(${JSON.stringify(marker)} + JSON.stringify(result));`;
  const localBin = resolve(homedir(), '.local/bin/ego-browser');
  const bin = process.env.EGO_BROWSER_BIN || (existsSync(localBin) ? localBin : 'ego-browser');
  const request = promisify(execFile)(bin, ['nodejs'], {
    timeout: 60000, killSignal: 'SIGKILL', maxBuffer: 1024 * 1024,
  });
  request.child.stdin.end(script);
  const { stdout, stderr } = await request;
  const line = (stdout + '\n' + stderr).split('\n').map(value => value.trim())
    .filter(value => value.startsWith(marker)).at(-1);
  if (!line) throw new Error('EGO_TASK_RECEIPT_MISSING');
  const result = JSON.parse(line.slice(marker.length));
  console.log(JSON.stringify(result));
  if (action === 'run' ? !result.ok : !['closed', 'recovered_closed'].includes(result.status)) process.exitCode = 1;
} catch (error) {
  console.error(error?.killed ? 'EGO_TASK_TIMEOUT: lease retained; late browser effects are unknown. Finish only this lease before another round.' : error.message);
  process.exitCode = 1;
}
