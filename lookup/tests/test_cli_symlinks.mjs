import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = fileURLToPath(new URL('..', import.meta.url));

for (const name of ['find-url.mjs', 'match-site.mjs']) {
  test(`${name} runs through a client directory symlink and imports silently`, () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'lookup-cli-link-'));
    try {
      const client = path.join(home, '.codex/skills');
      fs.mkdirSync(client, {recursive: true});
      fs.symlinkSync(root, path.join(client, 'lookup'), 'dir');
      const entry = path.join(client, 'lookup/scripts', name);
      const env = {...process.env, HOME: home, CI: '1'};
      const direct = spawnSync(process.execPath, [path.join(root, 'scripts', name), '--help'],
        {env, encoding: 'utf8', timeout: 5000});
      const linked = spawnSync(process.execPath, [entry, '--help'],
        {env, encoding: 'utf8', timeout: 5000});
      assert.equal(direct.status, 0, direct.stderr);
      assert.ok(direct.stdout.trim());
      assert.equal(linked.status, 0, linked.stderr);
      assert.equal(linked.stdout, direct.stdout);
      assert.equal(linked.stderr, direct.stderr);
      for (const args of [
        ['--input-type=module', '-e', `await import(${JSON.stringify(pathToFileURL(entry).href)});`],
        ['--input-type=module', '-', '--help'],
      ]) {
        const imported = spawnSync(process.execPath, args,
          {env, encoding: 'utf8', timeout: 5000,
            input: `await import(${JSON.stringify(pathToFileURL(entry).href)});`});
        assert.equal(imported.status, 0, imported.stderr);
        assert.equal(imported.stdout, '');
        assert.equal(imported.stderr, '');
      }
    } finally {
      fs.rmSync(home, {recursive: true, force: true});
    }
  });
}
