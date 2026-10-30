// Fixed worker launched under upstream.py's shared usage lock.
import {spawn, execFile, spawnSync} from 'node:child_process';
import {existsSync, writeFileSync} from 'node:fs';
import {homedir} from 'node:os';
import {join} from 'node:path';
import {lookupOptions, project, planNative, createJob, finishJob, checkOutstanding, nativeReceipt} from './opencli-native.mjs';
import {resolveBinding} from './opencli-profile.mjs';

const [binary, ...input] = process.argv.slice(2);
const nativePlatform = typeof process.getuid === 'function' && process.platform !== 'win32';
let job;
function output(result, fields) {
  if (result.ok && fields) {
    try { result = {...result, data: project(result.data, fields)}; }
    catch (error) { result = {...result, ok:false, error:{code:error.code,message:error.message}, projection_failed:true}; }
  }
  console.log(JSON.stringify(result));
  process.exitCode = result.ok ? 0 : 1;
}
try {
  const {args, engine, fields} = lookupOptions(input);
  const binding = resolveBinding();
  // The entry already pins all explicit profile selectors. The concrete ID
  // is an environment input; it is not an adapter argument.
  const actionArgs = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--profile') { i++; continue; }
    if (args[i].startsWith('--profile=')) continue;
    actionArgs.push(args[i]);
  }
  let format = 'json';
  for (let i=0; i<actionArgs.length && actionArgs[i] !== '--'; i++) {
    if (['-f','--format'].includes(actionArgs[i])) format = actionArgs[++i];
    else if (/^(?:-f|--format)=/.test(actionArgs[i])) format = actionArgs[i].slice(actionArgs[i].indexOf('=')+1);
  }
  if (fields && format !== 'json') throw Object.assign(new Error('Field selection requires JSON output'), {code:'LOOKUP_FIELDS'});
  if (nativePlatform && ['xiaohongshu/note', 'bilibili/subtitle'].includes(actionArgs.slice(0, 2).join('/'))) checkOutstanding();
  const localEgo = join(homedir(), '.local/bin/ego-browser');
  const ego = process.env.EGO_BROWSER_BIN || (existsSync(localEgo) ? localEgo : 'ego-browser');
  let plan;
  if (nativePlatform && engine !== 'bridge' && ['xiaohongshu/note', 'bilibili/subtitle'].includes(actionArgs.slice(0, 2).join('/'))) {
    const probe = spawnSync(ego, ['--version'], {encoding: 'utf8', timeout: 5000, maxBuffer: 65536});
    const version = !probe.error && probe.status === 0 ? (probe.stdout + probe.stderr).trim() : null;
    if (version) plan = planNative(binary, actionArgs, binding.profile, engine, version, binding.transport);
  }
  if (engine === 'ego' && !plan) throw Object.assign(new Error('This action, environment or argument contract is not qualified for native execution'), {code: 'LOOKUP_NATIVE_UNSUPPORTED'});
  if (plan) {
    job = createJob(plan, binary, ego);
    const moduleUrl = new URL('./opencli-native.mjs', import.meta.url).href;
    const marker = '@@LOOKUP_NATIVE@@';
    const script = `const {runInEgo} = await import(${JSON.stringify(moduleUrl)});
let result;
try { result = await runInEgo(${JSON.stringify(job.path)}, {taskSpace,listTaskSpaces}); }
catch(error) { result={ok:false,error:{code:error.code||'LOOKUP_NATIVE_PREPARE',message:error.message},dispatched:false,cleanup:{status:'no_space'}}; }
console.log(${JSON.stringify(marker)} + JSON.stringify(result));`;
    const result = await new Promise((resolve, reject) => {
      const child = execFile(ego, ['nodejs'], {maxBuffer: 8 * 1024 * 1024}, (error, stdout, stderr) => {
        try { resolve(nativeReceipt(stdout,stderr)); } catch (cause) { reject(cause); }
      });
      child.stdin.on('error', () => {});
      child.stdin.end(script);
    });
    writeFileSync(join(job.root, 'result.json'), JSON.stringify(result), {mode: 0o600});
    try { output(result, fields); } finally { finishJob(job, result); }
  } else {
    const child = spawn(binary, args, {stdio: fields ? ['inherit','pipe','inherit'] : 'inherit', shell:false});
    let stdout = '';
    if (fields) child.stdout.setEncoding('utf8').on('data', chunk => { stdout += chunk; });
    const code = await new Promise((resolve,reject) => { child.on('error',reject); child.on('close',(code,signal) => resolve(code ?? 128)); });
    if (fields) {
      const result = JSON.parse(stdout);
      if (code === 0 && result.ok) output(result,fields); else process.stdout.write(stdout);
    }
    process.exitCode = code || process.exitCode || 0;
  }
} catch (error) {
  console.error(JSON.stringify({ok:false,error:{code:error.code||'LOOKUP_DISPATCH_FAILED',message:error.message},outcome_unknown:!!error.outcome_unknown,retryable:false,...(job ? {recovery:job.root} : {})}));
  process.exitCode = 1;
}
