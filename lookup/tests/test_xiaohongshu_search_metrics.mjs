import assert from 'node:assert/strict';
import { copyFileSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..');
const fixture = path.join(root, 'tests/fixtures/xiaohongshu-search-command.js');
const original = readFileSync(fixture, 'utf8');
const temporary = mkdtempSync(path.join(tmpdir(), 'lookup-xhs-metrics-'));
let patched;
try {
  copyFileSync(fixture, path.join(temporary, 'search.js'));
  const result = spawnSync('patch', ['-p1', '-F', '0'], {
    cwd: temporary,
    input: readFileSync(path.join(root, 'patches/opencli-2.0.2-xiaohongshu-search-metrics.patch'), 'utf8'),
    encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  patched = readFileSync(path.join(temporary, 'search.js'), 'utf8');
} finally {
  rmSync(temporary, { recursive: true });
}

const candidate = {
  title: 'Synthetic account guide',
  author: 'Example author',
  likes: '142',
  url: 'https://www.xiaohongshu.com/search_result/000000000000000000000001',
};

async function search(sort, source = patched, count = '142') {
  const context = vm.createContext({
    cli: definition => definition,
    Strategy: { COOKIE: 'cookie' },
    parseLimit: value => value,
    resolveSearchFilters: () => [],
    openSearchResults: async () => {},
    collectSearchHarvest: async () => ({ rows: [{ ...candidate, likes: count }], diag: {} }),
    isCollapsedRender: () => false,
    noteIdToDate: () => '',
  });
  vm.runInContext(source.replace('export const command =', 'globalThis.command ='), context);
  const result = await context.command.func({}, { query: 'synthetic', limit: 1, sort });
  return JSON.parse(JSON.stringify(result[0]));
}

test('baseline reproduces saved counts mislabeled as likes', async () => {
  const row = await search('most-collected', original);
  assert.equal(row.likes, '142');
  assert.equal(row.collects, undefined);
});

test('most-collected reports saves and leaves likes unknown', async () => {
  const row = await search('most-collected');
  assert.equal(row.likes, '');
  assert.equal(row.collects, '142');
  assert.equal(row.comments, undefined);
  assert.equal(row.title, candidate.title);
  assert.equal(row.author, candidate.author);
  assert.equal(row.url, candidate.url);
});

test('most-commented reports replies and leaves likes unknown', async () => {
  const row = await search('most-commented');
  assert.equal(row.likes, '');
  assert.equal(row.comments, '142');
  assert.equal(row.collects, undefined);
});

test('default, comprehensive, latest and most-liked preserve observed likes', async () => {
  for (const sort of [undefined, 'comprehensive', 'latest', 'most-liked']) {
    const row = await search(sort);
    assert.equal(row.likes, '142');
    assert.equal(row.collects, undefined);
    assert.equal(row.comments, undefined);
  }
});

test('zero, abbreviated and missing counts are not invented or reinterpreted', async () => {
  for (const count of ['0', '1.2万', '']) {
    const row = await search('most-collected', patched, count);
    assert.equal(row.collects, count);
    assert.equal(row.likes, '');
  }
});
