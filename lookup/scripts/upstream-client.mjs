// Best-effort notices never share the business stdout or issue platform requests.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const helper = fileURLToPath(new URL('./upstream.py', import.meta.url));
const python = 'python3';
function inspect(args) {
  const result = spawnSync(python, [helper, ...args], {
    encoding: 'utf8', timeout: 1500, maxBuffer: 65536,
  });
  if (result.error) {
    if (result.error.code === 'ENOENT') return null;
    return { error: 'UPDATE_HELPER_UNAVAILABLE' };
  }
  if (result.status !== 0) {
    try { return { error: JSON.parse(result.stderr).error ?? 'UPDATE_HELPER_FAILED' }; }
    catch { return { error: 'UPDATE_HELPER_FAILED' }; }
  }
  try { return JSON.parse(result.stdout); } catch { return null; }
}
export function opencliExecutable() {
  const result = inspect(['resolve']);
  if (result?.error) throw new Error(result.error);
  return result?.binary ? { binary: result.binary, supervised: result.supervised !== false } : { binary: 'opencli', supervised: false };
}
export function supervisedCommand(selected, args) {
  return selected.supervised
    ? [python, [helper, 'use', '--expected', selected.binary, '--', ...args]]
    : [selected.binary, args];
}
export function checkUpdates(dependency, current) {
  if (process.env.CI) return;
  inspect(['check', dependency, '--background', ...(current ? ['--current', current] : [])]);
  reportUpdates(dependency);
}
export function reportUpdates(dependency) {
  if (process.env.CI) return;
  const result = inspect(['notices', dependency]);
  for (const notice of result?.notices ?? []) {
    console.error('LOOKUP_UPSTREAM_NOTICE ' + JSON.stringify(notice));
  }
}
