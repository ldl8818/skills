// Imported inside ego-browser nodejs. One lease per goal, one writer per lease.
// A random recorded name is creation evidence; agent ownership alone is not.
import { readFile, mkdir, open, rename } from 'node:fs/promises';
import { dirname, isAbsolute } from 'node:path';
import { randomUUID } from 'node:crypto';

const stopped = new Set(['user_control', 'denied', 'protected_tabs', 'uncertain']);
const ended = new Set(['closed', 'recovered_closed']);
const validStates = new Set(['creating', 'open', 'finishing', ...stopped, ...ended]);

async function readLease(file) {
  if (!isAbsolute(file)) throw new Error('EGO_LEASE_PATH_INVALID');
  let lease;
  try { lease = JSON.parse(await readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
  if (lease.version !== 1 || !/^[0-9a-f-]{36}$/.test(lease.runId)
      || !lease.name?.endsWith(`[${lease.runId}]`) || !validStates.has(lease.state)
      || (lease.spaceId !== null && !Number.isInteger(lease.spaceId))) {
    throw new Error('EGO_LEASE_INVALID');
  }
  return lease;
}

async function writeLease(file, lease) {
  await mkdir(dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${randomUUID()}.tmp`;
  const handle = await open(temporary, 'wx', 0o600);
  try { await handle.writeFile(JSON.stringify(lease) + '\n'); await handle.sync(); }
  finally { await handle.close(); }
  await rename(temporary, file);
}

function controlStop(error) {
  return /permission|denied|user.?control|user.?owned|inactive|unassigned|control.*(lost|transfer)|hand.?off/i
    .test(`${error?.code || ''} ${error?.message || error}`);
}

async function ownedSpace(api, lease) {
  const spaces = await api.listTaskSpaces();
  const named = spaces.filter(space => space.name === lease.name);
  if (!named.length) {
    // Never follow a recycled id into another task.
    if (spaces.some(space => space.id === lease.spaceId)) throw new Error('EGO_SPACE_ID_REUSED');
    return null;
  }
  if (named.length !== 1 || named[0].createdBy !== 'agent'
      || (lease.spaceId !== null && named[0].id !== lease.spaceId)) {
    throw new Error('EGO_SPACE_OWNERSHIP_UNVERIFIED');
  }
  return named[0];
}

export async function finishOwnedTask(api, { leasePath, keep = [] }) {
  const lease = await readLease(leasePath);
  if (!lease) return { status: 'no_lease' };
  if (ended.has(lease.state) || stopped.has(lease.state)) return { status: lease.state, spaceId: lease.spaceId };
  const save = async state => {
    lease.state = state; await writeLease(leasePath, lease);
    return { status: state, spaceId: lease.spaceId };
  };
  try {
    const space = await ownedSpace(api, lease);
    if (!space) {
      // Creation may still arrive after a killed CLI. No new space until resolved.
      return await save(lease.state === 'creating' ? 'uncertain' : 'recovered_closed');
    }
    lease.spaceId = space.id;
    if (space.ownership !== 'agent') return await save('user_control');
    // A finish already dispatched with a lost receipt must never be dispatched twice.
    if (lease.state === 'finishing') return await save('uncertain');
    const task = await api.taskSpace(space.id);
    if (task.ownership !== 'agent') return await save('user_control');
    lease.state = 'finishing'; await writeLease(leasePath, lease);
    const receipt = await task.finish({ keep });
    let remaining = await ownedSpace(api, lease);
    if (receipt?.spaceId !== space.id) return await save('uncertain');
    // Native close receipts precede the Space registry update. Observe only;
    // never dispatch finish again to compensate for this short UI delay.
    for (let attempt = 0; receipt.closedSpace === true && remaining && attempt < 6; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 250));
      remaining = await ownedSpace(api, lease);
    }
    if (receipt.closedSpace === true && !remaining) return await save('closed');
    if (receipt.closedSpace === false && remaining?.ownership === 'user') return await save('protected_tabs');
    return await save('uncertain');
  } catch (error) {
    return await save(controlStop(error) ? 'denied' : 'uncertain');
  }
}

export async function openOwnedTask(api, { leasePath, label, profileId }) {
  let lease = await readLease(leasePath);
  if (lease && !ended.has(lease.state)) {
    throw new Error(`EGO_OUTSTANDING_LEASE:${lease.state}`);
  }
  if (typeof label !== 'string' || !label.trim()) throw new Error('EGO_LABEL_INVALID');
  const runId = randomUUID();
  lease = { version: 1, runId, name: `${label} [${runId}]`, spaceId: null, state: 'creating' };
  // Persist before creating, so a lost creation receipt cannot orphan an unrecorded space.
  await writeLease(leasePath, lease);
  try {
    const task = await api.taskSpace(lease.name, profileId ? { profileId } : {});
    if (!Number.isInteger(task.spaceId) || task.name !== lease.name) throw new Error('EGO_CREATION_INVALID');
    lease.spaceId = task.spaceId; lease.state = 'open'; await writeLease(leasePath, lease);
    const space = await ownedSpace(api, lease);
    if (!space || space.ownership !== 'agent' || task.ownership !== 'agent') {
      lease.state = 'user_control'; await writeLease(leasePath, lease);
      throw new Error('EGO_USER_CONTROL');
    }
    return task;
  } catch (error) {
    if (controlStop(error)) { lease.state = 'denied'; await writeLease(leasePath, lease); }
    throw error;
  }
}

export async function runOwnedTask(api, options, work) {
  // Recover only this caller's durable lease, never scan all Agent-owned spaces.
  const previous = await readLease(options.leasePath);
  if (previous && !ended.has(previous.state)) {
    const cleanup = await finishOwnedTask(api, options);
    // Recovery is a separate round. Do not start new work after an interrupted round.
    return { ok: false, error: 'previous_round_interrupted', cleanup };
  }
  let value, error, cleanup;
  try {
    const task = await openOwnedTask(api, options);
    value = await work(task);
  } catch (cause) {
    error = 'work_failed';
    if (controlStop(cause)) {
      const lease = await readLease(options.leasePath);
      if (lease) { lease.state = 'denied'; await writeLease(options.leasePath, lease); }
    }
  } finally {
    cleanup = await finishOwnedTask(api, options);
  }
  return { ok: !error && cleanup.status === 'closed', value, error, cleanup };
}
