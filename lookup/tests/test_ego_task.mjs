import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { openOwnedTask, finishOwnedTask, runOwnedTask } from '../scripts/ego-task.mjs';

let checks = 0;
async function scenario(name, test) {
  const directory = await mkdtemp(join(tmpdir(), 'lookup-owned-test-'));
  const spaces = [{ id: 11, name: 'other agent goal', createdBy: 'agent', ownership: 'agent' },
    { id: 12, name: 'user goal', createdBy: 'user', ownership: 'user' }];
  const untouched = JSON.stringify(spaces);
  const options = { leasePath: join(directory, 'lease.json'), label: 'synthetic goal' };
  const f = { spaces, options, finished: [], resumed: [], created: 0 };
  f.lease = async () => JSON.parse(await readFile(options.leasePath, 'utf8'));
  f.save = async lease => writeFile(options.leasePath, JSON.stringify(lease));
  f.api = {
    listTaskSpaces: async () => {
      if (f.delayed && f.finished.length && ++f.readbacks > 2) spaces.splice(2);
      return spaces.map(space => ({ ...space }));
    },
    taskSpace: async target => {
      let space;
      if (typeof target === 'string') {
        f.created++;
        space = { id: 20 + f.created, name: target, createdBy: 'agent', ownership: 'agent' };
        spaces.push(space);
        if (f.creationLost) throw new Error('creation receipt lost');
      } else {
        f.resumed.push(target);
        assert.ok(target > 20, 'must never resume another task');
        space = spaces.find(item => item.id === target);
      }
      return {
        spaceId: space.id, name: space.name,
        get ownership() { return space.ownership; },
        finish: async ({ keep }) => {
          assert.deepEqual(keep, []);
          assert.ok(!f.finished.includes(space.id), 'finish dispatched at most once');
          f.finished.push(space.id);
          if (f.finishLost === 'before') throw new Error('receipt lost');
          if (f.delayed) { space.ownership = 'user'; f.readbacks = 0; }
          else if (f.protected) space.ownership = 'user';
          else spaces.splice(spaces.indexOf(space), 1);
          if (f.finishLost === 'after') throw new Error('receipt lost');
          return { spaceId: f.wrongReceipt ? 11 : space.id, closedSpace: !f.protected };
        }
      };
    }
  };
  try {
    await test(f);
    assert.equal(JSON.stringify(spaces.filter(space => space.id <= 12)), untouched, name);
    checks++;
  } finally { await rm(directory, { recursive: true, force: true }); }
}

for (const failure of [null, 'HTTP failure', 'navigation ERR_TIMED_OUT']) {
  await scenario(failure || 'success', async f => {
    const result = await runOwnedTask(f.api, f.options, async () => {
      if (failure) throw new Error(failure);
      return 42;
    });
    assert.equal(result.ok, !failure);
    assert.equal(result.cleanup.status, 'closed');
    assert.equal(f.finished.length, 1);
    assert.equal(f.spaces.length, 2);
    assert.equal((await finishOwnedTask(f.api, f.options)).status, 'closed');
    assert.equal(f.finished.length, 1);
  });
}
await scenario('takeover', async f => {
  const result = await runOwnedTask(f.api, f.options, async task => {
    f.spaces.find(space => space.id === task.spaceId).ownership = 'user';
    throw new Error('HTTP failure');
  });
  assert.equal(result.cleanup.status, 'user_control');
  assert.equal(f.finished.length, 0);
  await runOwnedTask(f.api, f.options, async () => assert.fail('must stay paused'));
  assert.equal(f.created, 1);
});
await scenario('permission denied', async f => {
  const result = await runOwnedTask(f.api, f.options, async () => { throw new Error('Permission denied'); });
  assert.equal(result.cleanup.status, 'denied');
  assert.equal(f.finished.length, 0);
});
await scenario('protected user or unknown tab', async f => {
  f.protected = true;
  const result = await runOwnedTask(f.api, f.options, async () => 42);
  assert.equal(result.cleanup.status, 'protected_tabs');
  assert.equal(result.ok, false);
  await runOwnedTask(f.api, f.options, async () => assert.fail());
  assert.equal(f.created, 1);
});
await scenario('multi round same goal', async f => {
  const task = await openOwnedTask(f.api, f.options);
  const record = await f.lease();
  assert.equal(record.spaceId, task.spaceId);
  assert.equal(record.state, 'open');
  await assert.rejects(openOwnedTask(f.api, f.options), /OUTSTANDING/);
  assert.equal((await finishOwnedTask(f.api, f.options)).status, 'closed');
});
await scenario('native registry is eventually consistent', async f => {
  f.delayed = true;
  const result = await runOwnedTask(f.api, f.options, async () => 42);
  assert.equal(result.ok, true);
  assert.equal(result.cleanup.status, 'closed');
  assert.equal(f.finished.length, 1);
});
await scenario('lost creation receipt', async f => {
  f.creationLost = true;
  const result = await runOwnedTask(f.api, f.options, async () => assert.fail());
  assert.equal(result.cleanup.status, 'closed');
  assert.equal(f.finished.length, 1);
});
await scenario('killed outer process', async f => {
  await openOwnedTask(f.api, f.options); // No finally ran before the next round.
  const result = await runOwnedTask(f.api, f.options, async () => assert.fail());
  assert.equal(result.error, 'previous_round_interrupted');
  assert.equal(result.cleanup.status, 'closed');
  assert.equal(f.created, 1);
});
await scenario('creation still uncertain', async f => {
  await openOwnedTask(f.api, f.options);
  const lease = await f.lease(); lease.state = 'creating'; lease.spaceId = null;
  await f.save(lease); f.spaces.splice(2);
  const result = await runOwnedTask(f.api, f.options, async () => assert.fail());
  assert.equal(result.cleanup.status, 'uncertain');
  assert.equal(f.created, 1);
});
for (const fault of ['changed-name', 'changed-id', 'duplicate-name', 'wrong-creator', 'wrong-receipt']) {
  await scenario(fault, async f => {
    await openOwnedTask(f.api, f.options);
    if (fault === 'changed-name') f.spaces[2].name = 'another goal';
    if (fault === 'changed-id') f.spaces[2].id++;
    if (fault === 'duplicate-name') f.spaces.push({ ...f.spaces[2], id: 30 });
    if (fault === 'wrong-creator') f.spaces[2].createdBy = 'user';
    if (fault === 'wrong-receipt') f.wrongReceipt = true;
    assert.equal((await finishOwnedTask(f.api, f.options)).status, 'uncertain');
    assert.equal(f.finished.length, fault === 'wrong-receipt' ? 1 : 0);
  });
}
for (const fault of ['before', 'after']) {
  await scenario('finish receipt lost ' + fault, async f => {
    f.finishLost = fault;
    const result = await runOwnedTask(f.api, f.options, async () => 42);
    assert.equal(result.cleanup.status, 'uncertain');
    await finishOwnedTask(f.api, f.options);
    assert.equal(f.finished.length, 1);
  });
}
await scenario('corrupt record', async f => {
  await writeFile(f.options.leasePath, '{bad');
  await assert.rejects(runOwnedTask(f.api, f.options, async () => assert.fail()));
  assert.equal(f.created, 0); assert.equal(f.finished.length, 0);
});
await scenario('finish dispatched before hard kill', async f => {
  await openOwnedTask(f.api, f.options);
  const lease = await f.lease(); lease.state = 'finishing'; await f.save(lease);
  assert.equal((await finishOwnedTask(f.api, f.options)).status, 'uncertain');
  assert.equal(f.finished.length, 0);
});
console.log(`${checks} owned-space lifecycle scenarios passed; other goals untouched`);
