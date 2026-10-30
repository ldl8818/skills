// Qualified read-only OpenCLI adapters executed by ego's native Page API.
import { readFileSync, readdirSync, realpathSync, existsSync, lstatSync, mkdirSync, writeFileSync, mkdtempSync, rmSync, renameSync } from 'node:fs';
import { join, dirname, resolve, isAbsolute } from 'node:path';
import { homedir } from 'node:os';
import { createHash, randomUUID } from 'node:crypto';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { promisify } from 'node:util';
import { execFile } from 'node:child_process';
import { runOwnedTask } from './ego-task.mjs';

const actions = new Set(['xiaohongshu/note', 'bilibili/subtitle']);
const sha = value => createHash('sha256').update(value).digest('hex');
const self = fileURLToPath(import.meta.url);
export function reject(code, message) { throw Object.assign(new Error(message), {code}); }

export function nativeReceipt(stdout, stderr) {
  const marker = '@@LOOKUP_NATIVE@@';
  const line = (stdout + '\n' + stderr).split('\n').map(x => x.trim()).filter(x => x.startsWith(marker)).at(-1);
  try {
    const result = JSON.parse(line?.slice(marker.length));
    if (typeof result?.ok !== 'boolean' || typeof result.cleanup?.status !== 'string'
        || (result.ok && !Array.isArray(result.data))) throw new Error();
    return result;
  } catch {
    throw Object.assign(new Error('Native receipt missing or invalid; inspect the original lease before retrying'), {code:'LOOKUP_NATIVE_UNKNOWN',outcome_unknown:true});
  }
}

export function lookupOptions(input) {
  const args = [], values = {engine: 'auto', fields: null};
  for (let i = 0; i < input.length; i++) {
    if (input[i] === '--') { args.push(...input.slice(i)); break; }
    const match = /^--lookup-(engine|fields)(?:=(.*))?$/.exec(input[i]);
    if (!match) { args.push(input[i]); continue; }
    const value = match[2] ?? input[++i];
    if (typeof value !== 'string' || !value || value.startsWith('--')) reject('LOOKUP_OPTIONS', 'Missing lookup option value');
    if (match[1] === 'engine') values.engine = value;
    else values.fields = value.split(',');
  }
  if (!['auto', 'bridge', 'ego'].includes(values.engine)) reject('LOOKUP_OPTIONS', 'Engine must be auto, bridge or ego');
  if (values.fields && (new Set(values.fields).size !== values.fields.length || values.fields.some(x => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(x)))) reject('LOOKUP_OPTIONS', 'Fields must be distinct identifiers');
  return {args, ...values};
}

export function project(data, fields) {
  if (!fields) return data;
  if (Array.isArray(data) && data.length && data.every(x => x && typeof x.field === 'string' && Object.hasOwn(x, 'value'))) {
    if (fields.some(f => !data.some(x => x.field === f))) reject('LOOKUP_FIELDS', 'Requested fields are absent');
    return data.filter(x => fields.includes(x.field));
  }
  const rows = Array.isArray(data) ? data : [data];
  if (!rows.length) return data;
  if (rows.some(x => !x || typeof x !== 'object' || fields.some(f => !Object.hasOwn(x, f)))) reject('LOOKUP_FIELDS', 'Requested fields are absent');
  const result = rows.map(x => Object.fromEntries(fields.filter(f => Object.hasOwn(x, f)).map(f => [f, x[f]])));
  return Array.isArray(data) ? result : result[0];
}

function privateRoot() {
  const base = process.env.XDG_STATE_HOME || join(homedir(), '.local/state');
  if (!isAbsolute(base)) reject('LOOKUP_NATIVE_STATE', 'State root must be absolute');
  mkdirSync(base, {recursive:true, mode:0o700});
  // Canonicalize the caller's state base (macOS /var is an OS alias), then
  // reject links inside our namespace before writing any job or receipt.
  const canonicalBase = realpathSync(base);
  const root = join(canonicalBase, 'lookup/ego-opencli');
  let part = canonicalBase;
  for (const component of ['lookup','ego-opencli']) {
    part = join(part, component);
    if (existsSync(part) && lstatSync(part).isSymbolicLink()) reject('LOOKUP_NATIVE_STATE', 'State symlink rejected');
  }
  mkdirSync(root, {recursive: true, mode: 0o700});
  const stat = lstatSync(root);
  if (!stat.isDirectory() || (stat.mode & 0o077) || stat.uid !== process.getuid?.()) reject('LOOKUP_NATIVE_STATE', 'State root must be private and owned');
  return root;
}

export function checkOutstanding() {
  const root = privateRoot();
  for (const name of readdirSync(root).filter(x => x.startsWith('job-'))) {
    const area = join(root, name);
    let lease;
    try { lease = JSON.parse(readFileSync(join(area, 'lease.json'))); } catch {}
    if (!['closed', 'recovered_closed'].includes(lease?.state)) reject('LOOKUP_NATIVE_OUTSTANDING', `Inspect the original native lease before another dispatch: ${area}`);
  }
}

export function describeSource(binary, key) {
  if (!actions.has(key)) return null;
  let root = dirname(realpathSync(binary));
  while (!existsSync(join(root, 'package.json')) && dirname(root) !== root) root = dirname(root);
  const pkg = JSON.parse(readFileSync(join(root, 'package.json')));
  if (pkg.name !== '@jackwener/opencli' || pkg.version !== '2.0.2') return null;
  // OpenCLI 2.0.2 discovery uses homedir, independently of profile config.
  const config = join(homedir(), '.opencli');
  if (existsSync(join(config, 'plugins')) && readdirSync(join(config, 'plugins')).length) return null;
  const override = join(config, 'clis', key + '.js');
  const module = existsSync(override) ? override : join(root, 'clis', key + '.js');
  const files = new Map();
  const add = path => {
    if (lstatSync(path).isSymbolicLink()) reject('LOOKUP_NATIVE_SOURCE', 'Adapter symlink rejected');
    const text = readFileSync(path, 'utf8'); files.set(path, sha(text)); return text;
  };
  const walk = dir => {
    if (realpathSync(dir) !== resolve(dir)) reject('LOOKUP_NATIVE_SOURCE', 'Source directory symlink rejected');
    for (const entry of readdirSync(dir, {withFileTypes: true})) {
      const path = join(dir, entry.name);
      if (entry.isSymbolicLink()) reject('LOOKUP_NATIVE_SOURCE', 'Source symlink rejected');
      if (entry.isDirectory()) walk(path);
      else if (/\.(?:[cm]?js|json|ya?ml)$/.test(entry.name)) add(path);
    }
  };
  add(join(root, 'package.json')); walk(join(root, 'dist/src')); walk(join(root, 'clis'));
  if (existsSync(join(config, 'clis'))) walk(join(config, 'clis'));
  for (const manifest of [join(root, 'cli-manifest.json'), join(config, 'cli-manifest.json')]) if (existsSync(manifest)) add(manifest);
  const require = createRequire(module);
  for (const [name, file] of [['registry', 'registry-api.js'], ['errors', 'errors.js']]) {
    if (realpathSync(require.resolve('@jackwener/opencli/' + name)) !== realpathSync(join(root, 'dist/src', file))) return null;
  }
  const sorted = [...files].sort(([a], [b]) => a.localeCompare(b));
  return {root, module, config, key, version: pkg.version, fingerprint: sha(JSON.stringify(sorted)), executor: sha(Buffer.concat([readFileSync(self), ...['ego-task.mjs','opencli-dispatch.mjs','opencli-run.mjs'].map(name => readFileSync(new URL('./' + name, import.meta.url)))]))};
}

function qualified(evidence) {
  return evidence?.equivalent === true && evidence.closed === true && Number.isInteger(evidence.samples) && evidence.samples >= 3
    && Number.isFinite(evidence.nativeMedian) && evidence.nativeMedian > 0 && Number.isFinite(evidence.bridgeMedian)
    && evidence.nativeMedian <= evidence.bridgeMedian * 0.9;
}

export function planNative(binary, args, profile, engine, egoVersion, transport = 'bridge') {
  const key = args.slice(0, 2).join('/');
  if (engine === 'bridge' || !actions.has(key)) return null;
  if (transport !== 'bridge') return null;
  const allowedEnv = new Set(['OPENCLI_PROFILE', 'OPENCLI_CLOSE_OWNED_TAB']);
  if (Object.keys(process.env).some(k => k.startsWith('OPENCLI_') && process.env[k] && !allowedEnv.has(k)) || process.env.NODE_OPTIONS || process.env.NODE_PATH) return null;
  let descriptor;
  try { descriptor = describeSource(binary, key); } catch { return null; }
  if (!descriptor) return null;
  // Only the narrow JSON, one-shot read contract is qualified.
  const allowed = new Set(['--lang', '--page', '--format', '-f', '--site-session', '--keep-tab']);
  const positionals = [];
  for (let i = 2; i < args.length; i++) {
    if (!args[i].startsWith('-')) { positionals.push(args[i]); continue; }
    const [name, inline] = args[i].split('=', 2);
    if (!allowed.has(name)) return null;
    const value = inline ?? args[++i];
    if (!value || value.startsWith('-') || (['--format', '-f'].includes(name) && value !== 'json') || (name === '--keep-tab' && value !== 'false') || (name === '--site-session' && value !== 'ephemeral')) return null;
  }
  if (key === 'bilibili/subtitle' && !/^(?:BV[A-Za-z0-9]{10}$|https?:\/\/(?:www\.)?bilibili\.com\/video\/BV[A-Za-z0-9]{10}(?:[/?#]|$))/.test(positionals[0] ?? '')) return null;
  if (engine === 'auto') {
    let receipt;
    try { const file = join(privateRoot(), key.replace('/', '-') + '.json'); if (lstatSync(file).isSymbolicLink()) return null; receipt = JSON.parse(readFileSync(file)); }
    catch { return null; }
    if (receipt.fingerprint !== descriptor.fingerprint || receipt.executor !== descriptor.executor || receipt.profile !== profile || receipt.egoVersion !== egoVersion || !qualified(receipt.evidence)) return null;
  }
  return {descriptor, args, profile, egoVersion};
}

export function recordQualification(plan, evidence) {
  if (!qualified(evidence)) reject('LOOKUP_NATIVE_QUALIFICATION', 'Matched behavior and measured benefit required');
  const {descriptor, profile, egoVersion} = plan;
  const file = join(privateRoot(), descriptor.key.replace('/', '-') + '.json');
  const temporary = file + '.' + randomUUID();
  writeFileSync(temporary, JSON.stringify({fingerprint: descriptor.fingerprint, executor: descriptor.executor, profile, egoVersion, evidence}) + '\n', {mode: 0o600, flag: 'wx'});
  renameSync(temporary, file);
}

export function createJob(plan, binary, egoBinary) {
  const root = mkdtempSync(join(privateRoot(), 'job-'));
  const request = {...plan, binary, egoBinary, home: homedir(), leasePath: join(root, 'lease.json'), jobRoot: root};
  const path = join(root, 'request.json'); writeFileSync(path, JSON.stringify(request), {mode: 0o600});
  return {root, path};
}

export function finishJob(job, result) {
  if (result?.cleanup?.status === 'no_space' && !existsSync(join(job.root, 'lease.json'))) { rmSync(job.root, {recursive:true}); return; }
  try {
    const lease = JSON.parse(readFileSync(join(job.root, 'lease.json')));
    if (['closed', 'recovered_closed'].includes(lease.state)) rmSync(job.root, {recursive: true});
  } catch { /* Keep uncertain work and its exact recovery lease. */ }
}

export function adapterArgs(command, args) {
  const kwargs = Object.fromEntries(command.args.filter(a => Object.hasOwn(a, 'default')).map(a => [a.name, a.default]));
  const positionals = command.args.filter(a => a.positional); let index = 0;
  const common = new Set(['format', 'f', 'window', 'site-session', 'keep-tab', 'profile']);
  for (let i = 2; i < args.length; i++) {
    const token = args[i];
    if (!token.startsWith('-')) {
      if (!positionals[index]) reject('LOOKUP_NATIVE_ARGS', 'Unexpected positional');
      kwargs[positionals[index++].name] = token; continue;
    }
    const [raw, inline] = token.split('=', 2); const name = raw.replace(/^-+/, ''); const value = inline ?? args[++i];
    if (common.has(name)) continue;
    const def = command.args.find(a => a.name === name && !a.positional);
    if (!def || value === undefined) reject('LOOKUP_NATIVE_ARGS', 'Unsupported argument');
    kwargs[name] = value;
  }
  for (const def of command.args) if (def.required && !Object.hasOwn(kwargs, def.name)) reject('LOOKUP_NATIVE_ARGS', 'Missing required argument');
  return kwargs;
}

export async function executeAdapter(task, command, kwargs, {settle, stealth, classify, expression, markDispatched}) {
  const raw = task.page('p1');
  const page = {
    async goto(url, options) {
      markDispatched();
      await raw.goto(url, {waitUntil: 'load', timeout: 25000});
      const code = stealth() + ';\n' + (options?.waitUntil === 'none' ? '' : settle(options?.settleMs ?? 1000, Math.min(500, options?.settleMs ?? 1000)));
      try { await raw.evaluate(code); }
      catch (error) {
        if (classify(error).kind !== 'target-navigation') throw error;
        await new Promise(r => setTimeout(r, classify(error).delayMs));
        try { await raw.evaluate(code); } catch (retry) { if (classify(retry).kind !== 'target-navigation') throw retry; }
      }
    },
    async evaluate(code, ...args) {
      markDispatched();
      const js = expression(code, args);
      try { return await raw.evaluate(js); }
      catch (error) {
        if (classify(error).kind !== 'target-navigation') throw error;
        await new Promise(r => setTimeout(r, classify(error).delayMs));
        return raw.evaluate(js);
      }
    },
    async wait({time, selector, text, timeout}) {
      if (time !== undefined) { await new Promise(r => setTimeout(r, time * 1000)); return; }
      if (selector) return raw.waitForSelector(selector, {timeout: (timeout ?? 10) * 1000});
      if (text) return raw.waitForFunction(t => document.body?.innerText.includes(t), text, {timeout: (timeout ?? 10) * 1000});
      reject('LOOKUP_NATIVE_METHOD', 'Unsupported wait');
    },
  };
  if (typeof command.navigateBefore === 'string') await page.goto(command.navigateBefore);
  return command.func(page, kwargs);
}

// Called only by ego's documented Node runtime, in one owned TaskSpace.
export async function runInEgo(requestPath, api) {
  const request = JSON.parse(readFileSync(requestPath)); const {descriptor} = request;
  if (homedir() !== request.home) reject('LOOKUP_NATIVE_HOME', 'Native runtime home differs');
  const fresh = describeSource(request.binary, descriptor.key);
  if (!fresh || fresh.fingerprint !== descriptor.fingerprint || fresh.executor !== descriptor.executor) reject('LOOKUP_NATIVE_SOURCE_CHANGED', 'Source changed before native import');
  const require = createRequire(descriptor.module);
  const {getRegistry} = await import(pathToFileURL(require.resolve('@jackwener/opencli/registry')));
  const {discoverClis} = await import(pathToFileURL(join(descriptor.root, 'dist/src/discovery.js')));
  await discoverClis(join(descriptor.root, 'clis'));
  await discoverClis(join(descriptor.config, 'clis'));
  let command = getRegistry().get(descriptor.key);
  if (command?._lazy) { await import(pathToFileURL(command._modulePath)); command = getRegistry().get(descriptor.key); }
  if (command?.access !== 'read' || typeof command.func !== 'function') reject('LOOKUP_NATIVE_CONTRACT', 'Qualified read adapter missing');
  if (command.siteSession === 'persistent' || command.defaultWindowMode || [...(globalThis.__opencli_hooks__?.values() ?? [])].some(x => x.length)) reject('LOOKUP_NATIVE_CONTRACT', 'Custom lifecycle requires the CLI');
  const {prepareCommandArgs} = await import(pathToFileURL(join(descriptor.root, 'dist/src/execution.js')));
  const kwargs = prepareCommandArgs(command, adapterArgs(command, request.args));
  const {generateStealthJs} = await import(pathToFileURL(join(descriptor.root, 'dist/src/browser/stealth.js')));
  const {waitForDomStableJs} = await import(pathToFileURL(join(descriptor.root, 'dist/src/browser/dom-helpers.js')));
  const {classifyBrowserError} = await import(pathToFileURL(join(descriptor.root, 'dist/src/browser/errors.js')));
  const {buildEvaluateExpression} = await import(pathToFileURL(join(descriptor.root, 'dist/src/browser/utils.js')));
  let dispatched = false, failure, data;
  let result;
  try { result = await runOwnedTask(api, {leasePath: request.leasePath, label: 'lookup OpenCLI native read'}, async task => {
    const marker = 'lookup-ego-' + randomUUID();
    try {
      const url = 'data:text/html,' + encodeURIComponent('<title>' + marker + '</title>');
      await task.page('p1').goto(url);
      const probe = await promisify(execFile)(request.binary, ['--profile', request.profile, 'browser', 'chrome', 'call', 'tabs.query', JSON.stringify([{title: marker}])], {timeout: 12000, maxBuffer: 100000, env: {...process.env, OPENCLI_PROFILE: request.profile}});
      const payload = JSON.parse(probe.stdout);
      if (!payload.ok || !Array.isArray(payload.data) || payload.data.length !== 1 || payload.data[0].title !== marker || payload.data[0].url !== url) reject('LOOKUP_NATIVE_BINDING', 'Native task is not visible in the pinned browser connection');
      data = await executeAdapter(task, command, kwargs, {settle: waitForDomStableJs, stealth: generateStealthJs, classify: classifyBrowserError, expression: buildEvaluateExpression, markDispatched() { dispatched = true; }});
    } catch (error) {
      failure = {code: error.code || 'LOOKUP_NATIVE_ACTION', message: error.message, ...(error.help ? {hint: error.help} : {}),
        ...Object.fromEntries(['mayHaveLateEffects','executionStopped','outcome_unknown'].filter(k => typeof error[k] === 'boolean').map(k => [k,error[k]]))};
      writeFileSync(join(request.jobRoot, 'action-error.json'), JSON.stringify(failure), {mode: 0o600});
      throw error;
    }
  }); } catch (error) {
    return {ok:false,error:{code:error.code || 'LOOKUP_NATIVE_UNKNOWN',message:error.message},
      ...(data === undefined ? {} : {data}),dispatched,outcome_unknown:true,
      cleanup:{status:'uncertain'},recovery:request.jobRoot};
  }
  if (!result.ok) return {ok: false, error: failure || {code: ['user_control','denied','protected_tabs'].includes(result.cleanup.status) ? 'LOOKUP_NATIVE_CONTROL_STOP' : 'LOOKUP_NATIVE_PREFLIGHT', message: 'Native preparation or cleanup did not complete'}, ...(data === undefined ? {} : {data}), outcome_unknown: result.cleanup.status === 'uncertain' || !!failure?.mayHaveLateEffects || !!failure?.outcome_unknown || failure?.executionStopped === false || (dispatched && !failure), dispatched, cleanup: result.cleanup, recovery: request.jobRoot};
  return {ok: true, data, engine: 'ego', cleanup: result.cleanup};
}
