import assert from 'node:assert/strict';
import { execFileSync, spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { cleanField, parseArgs, searchBookmarks, searchHistory, selectProfile } from '../scripts/find-url.mjs';

const hasSqlite = spawnSync('sqlite3', ['--version'], { stdio: 'ignore' }).status === 0;
const hasPython = spawnSync('python3', ['--version'], { stdio: 'ignore' }).status === 0;
const now = Date.now();
const visitTime = daysAgo => (BigInt(now - daysAgo * 86400000) * 1000n + 11644473600000000n).toString();
const quote = value => "'" + String(value).replaceAll("'", "''") + "'";
const moduleUrl = new URL('../scripts/find-url.mjs', import.meta.url).href;

function fixture(t, lastUsed = 'Default') {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'lookup-history-test-'));
  fs.mkdirSync(path.join(directory, 'Default'));
  fs.mkdirSync(path.join(directory, 'Profile 1'));
  fs.writeFileSync(path.join(directory, 'Local State'), JSON.stringify({
    profile: { last_used: lastUsed, info_cache: { Default: { name: 'Fixture Default' }, 'Profile 1': { name: 'Fixture One' } } },
  }));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return directory;
}

function createHistory(profileDir, rows = []) {
  const schema = 'CREATE TABLE urls (title TEXT, url TEXT NOT NULL, last_visit_time INTEGER, visit_count INTEGER);';
  const inserts = rows.map(row => 'INSERT INTO urls VALUES (' + [
    quote(row.title), quote(row.url), visitTime(row.daysAgo || 0), row.visits || 1,
  ].join(',') + ');').join('\n');
  execFileSync('sqlite3', [path.join(profileDir, 'History')], { input: schema + '\n' + inserts, encoding: 'utf8' });
}

function writeBookmarks(profileDir, entries) {
  fs.writeFileSync(path.join(profileDir, 'Bookmarks'), JSON.stringify({
    roots: { bookmark_bar: { type: 'folder', name: 'Fixture Folder', children: entries.map(row => ({ type: 'url', ...row })) } },
  }));
}

function cli(directory, args) {
  return spawnSync(process.execPath, ['--input-type=module', '-e',
    'import { main } from ' + JSON.stringify(moduleUrl) + '; process.exitCode = main(JSON.parse(process.argv[1]), JSON.parse(process.argv[2]));',
    JSON.stringify(args), JSON.stringify([{ id: 'ego', label: 'fixture ego', dir: directory }])],
  { encoding: 'utf8', timeout: 10000 });
}

test('arguments bound queries and reject unsupported browsers or ambiguous values', () => {
  assert.equal(parseArgs(['--limit', '0']).limit, 0);
  assert.deepEqual(parseArgs(['--', '--literal', '%']).keywords, ['--literal', '%']);
  for (const args of [['--limit', '-1'], ['--limit', '1001'], ['--limit', '1.5'], ['--limit'],
    ['--sort', 'unexpected'], ['--since', 'invalid-date'], ['--only', 'bookmarks']]) {
    assert.throws(() => parseArgs(args), { code: 'INVALID_ARGUMENT' });
  }
  assert.throws(() => parseArgs(['--browser', 'chrome']), { code: 'BROWSER_UNSUPPORTED' });
});

test('selects one current or explicitly registered profile without probing others', t => {
  const directory = fixture(t, 'Profile 1');
  assert.deepEqual(selectProfile(directory), { dir: 'Profile 1', name: 'Fixture One' });
  assert.deepEqual(selectProfile(directory, 'Default'), { dir: 'Default', name: 'Fixture Default' });
  assert.throws(() => selectProfile(directory, '../outside'), { code: 'PROFILE_INVALID' });
  assert.throws(() => selectProfile(directory, 'Unknown'), { code: 'PROFILE_NOT_FOUND' });
  fs.rmSync(path.join(directory, 'Default'), { recursive: true });
  fs.symlinkSync(path.join(directory, 'Profile 1'), path.join(directory, 'Default'));
  assert.throws(() => selectProfile(directory, 'Default'), { code: 'PROFILE_NOT_FOUND' });
});

test('bookmarks and history share ASCII folding while non-ASCII stays literal', { skip: !hasSqlite }, t => {
  const profile = path.join(fixture(t), 'Default');
  const rows = [
    { title: 'ÜBER SDK', url: 'https://unicode.example/uppercase' },
    { title: 'über sdk', url: 'https://unicode.example/lowercase' },
  ];
  writeBookmarks(profile, rows.map(row => ({ name: row.title, url: row.url })));
  createHistory(profile, rows);
  for (const [keyword, expectedUrl] of [
    ['ÜBER', 'https://unicode.example/uppercase'],
    ['Über', 'https://unicode.example/uppercase'],
    ['üBER', 'https://unicode.example/lowercase'],
    ['über', 'https://unicode.example/lowercase'],
  ]) {
    const bookmarks = searchBookmarks(profile, 'Fixture', 'ego', [keyword, 'sDk']);
    const history = searchHistory(profile, 'Fixture', 'ego', [keyword, 'sDk'], null, 20, 'recent');
    assert.deepEqual(bookmarks.map(row => row.url), [expectedUrl]);
    assert.deepEqual(history.map(row => row.url), [expectedUrl]);
  }
});

test('bookmarks use literal AND matching and report corrupted or missing files', t => {
  const directory = fixture(t);
  const profile = path.join(directory, 'Default');
  writeBookmarks(profile, [{ name: '100% literal_marker', url: 'https://one.example/' }, { name: '100 ordinary marker', url: 'https://two.example/' }]);
  assert.deepEqual(searchBookmarks(profile, 'Fixture', 'ego', ['%', '_']).map(row => row.url), ['https://one.example/']);
  assert.deepEqual(searchBookmarks(profile, 'Fixture', 'ego', ['not-present']), []);
  fs.writeFileSync(path.join(profile, 'Bookmarks'), '{invalid');
  assert.throws(() => searchBookmarks(profile, 'Fixture', 'ego', ['x']), { code: 'BOOKMARKS_UNREADABLE' });
  fs.rmSync(path.join(profile, 'Bookmarks'));
  assert.throws(() => searchBookmarks(profile, 'Fixture', 'ego', ['x']), { code: 'BOOKMARKS_UNAVAILABLE' });
});

test('missing history and malformed profile state are errors, not confirmed empty', t => {
  const directory = fixture(t);
  assert.throws(() => searchHistory(path.join(directory, 'Default'), 'Fixture', 'ego', [], null, 20, 'recent'), { code: 'HISTORY_UNAVAILABLE' });
  fs.writeFileSync(path.join(directory, 'Local State'), '{invalid');
  assert.throws(() => selectProfile(directory), { code: 'PROFILE_STATE_INVALID' });
});

test('history JSON preserves tab/newline titles and literal percent, underscore and quotes', { skip: !hasSqlite }, t => {
  const profile = path.join(fixture(t), 'Default');
  const title = "100% literal_marker\tcell\nforged | https://fake.invalid/ '";
  createHistory(profile, [
    { title, url: 'https://actual.example/page' },
    { title: '100 ordinary marker', url: 'https://other.example/page', daysAgo: 1 },
  ]);
  const rows = searchHistory(profile, 'Fixture', 'ego', ['%', '_', "'"], null, 20, 'recent');
  assert.equal(rows.length, 1);
  assert.equal(rows[0].url, 'https://actual.example/page');
  assert.equal(rows[0].title, title);
  assert.equal(cleanField(rows[0].title).includes('\n'), false);
  assert.equal(cleanField(rows[0].title).includes('\t'), false);
  assert.equal(cleanField(rows[0].title).includes('|'), false);
  assert.deepEqual(searchHistory(profile, 'Fixture', 'ego', ["' OR 1=1 --"], null, 20, 'recent'), []);
  const count = execFileSync('sqlite3', ['-readonly', path.join(profile, 'History'), 'SELECT count(*) FROM urls;'], { encoding: 'utf8' }).trim();
  assert.equal(count, '2');
});

test('history filters date, sorts visits, limits results and distinguishes unreadable databases', { skip: !hasSqlite }, t => {
  const profile = path.join(fixture(t), 'Default');
  createHistory(profile, [
    { title: 'fresh', url: 'https://fresh.example/', visits: 2 },
    { title: 'old', url: 'https://old.example/', daysAgo: 10, visits: 50 },
  ]);
  assert.equal(searchHistory(profile, 'Fixture', 'ego', [], null, 1, 'visits')[0].title, 'old');
  assert.deepEqual(searchHistory(profile, 'Fixture', 'ego', [], new Date(now - 86400000), 20, 'recent').map(row => row.title), ['fresh']);
  assert.deepEqual(searchHistory(profile, 'Fixture', 'ego', ['unmatched'], null, 20, 'recent'), []);
  fs.writeFileSync(path.join(profile, 'History'), 'invalid database fixture');
  assert.throws(() => searchHistory(profile, 'Fixture', 'ego', [], null, 20, 'recent'), { code: 'HISTORY_UNREADABLE' });
});

test('CLI queries only the chosen profile and returns explicit empty or error status', { skip: !hasSqlite }, t => {
  const directory = fixture(t, 'Profile 1');
  fs.writeFileSync(path.join(directory, 'Default', 'History'), 'unreadable unselected fixture');
  createHistory(path.join(directory, 'Profile 1'), [{ title: 'selected', url: 'https://selected.example/' }]);
  let result = cli(directory, ['--only', 'history', '--json']);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).profile, 'Profile 1');
  assert.equal(JSON.parse(result.stdout).history[0].url, 'https://selected.example/');
  assert.equal(JSON.parse(result.stderr).status, 'ok');
  result = cli(directory, ['unmatched', '--only', 'history', '--json']);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stderr).status, 'empty');
  assert.equal(JSON.parse(result.stderr).empty_confirmed, true);
  result = cli(directory, ['--only', 'history', '--profile', 'Default', '--json']);
  assert.equal(result.status, 1);
  assert.equal(result.stdout, '');
  assert.equal(JSON.parse(result.stderr).error.code, 'HISTORY_UNREADABLE');
});

test('--limit 0 is bounded and explicitly partial, ordinary top N reports more_available', { skip: !hasSqlite }, t => {
  const directory = fixture(t);
  createHistory(path.join(directory, 'Default'), Array.from({ length: 1001 }, (_, index) => ({
    title: 'fixture ' + index, url: 'https://example.invalid/' + index,
  })));
  let result = cli(directory, ['--only', 'history', '--limit', '0', '--json']);
  assert.equal(result.status, 3, result.stderr);
  assert.equal(JSON.parse(result.stdout).history.length, 1000);
  assert.equal(JSON.parse(result.stderr).status, 'partial');
  assert.equal(JSON.parse(result.stderr).truncated, true);
  result = cli(directory, ['--only', 'history', '--limit', '2', '--json']);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).history.length, 2);
  assert.equal(JSON.parse(result.stderr).more_available, true);
});

test('bookmarks and history share top N with bookmarks taking the first slots', { skip: !hasSqlite }, t => {
  const directory = fixture(t);
  const profile = path.join(directory, 'Default');
  writeBookmarks(profile, Array.from({ length: 3 }, (_, index) => ({
    name: 'fixture bookmark ' + index, url: 'https://bookmarks.example/' + index,
  })));
  createHistory(profile, Array.from({ length: 4 }, (_, index) => ({
    title: 'fixture history ' + index, url: 'https://history.example/' + index,
  })));
  for (const [limit, expectedBookmarks, expectedHistory, moreAvailable] of [[2, 2, 0, true], [4, 3, 1, true], [7, 3, 4, false]]) {
    const result = cli(directory, ['fixture', '--limit', String(limit), '--json']);
    assert.equal(result.status, 0, result.stderr);
    const output = JSON.parse(result.stdout);
    const metadata = JSON.parse(result.stderr);
    assert.equal(output.bookmarks.length, expectedBookmarks);
    assert.equal(output.history.length, expectedHistory);
    assert.equal(output.bookmarks.length + output.history.length, limit);
    assert.equal(output.more_available, moreAvailable);
    assert.equal(metadata.status, 'ok');
    assert.equal(metadata.truncated, false);
    assert.equal(metadata.more_available, moreAvailable);
    assert.equal(output.bookmarks[0].url, 'https://bookmarks.example/0');
  }
});

test('--limit 0 marks partial when the combined source count exceeds 1000', { skip: !hasSqlite }, t => {
  const directory = fixture(t);
  const profile = path.join(directory, 'Default');
  const bookmarks = Array.from({ length: 500 }, (_, index) => ({
    name: 'fixture bookmark ' + index, url: 'https://bookmarks.example/' + index,
  }));
  writeBookmarks(profile, bookmarks);
  createHistory(profile, Array.from({ length: 501 }, (_, index) => ({
    title: 'fixture history ' + index, url: 'https://history.example/' + index,
  })));
  let result = cli(directory, ['fixture', '--limit', '0', '--json']);
  assert.equal(result.status, 3, result.stderr);
  let output = JSON.parse(result.stdout);
  assert.equal(output.bookmarks.length, 500);
  assert.equal(output.history.length, 500);
  assert.equal(output.bookmarks.length + output.history.length, 1000);
  assert.equal(output.more_available, true);
  assert.equal(JSON.parse(result.stderr).status, 'partial');
  assert.equal(JSON.parse(result.stderr).truncated, true);
  writeBookmarks(profile, bookmarks.slice(0, 499));
  result = cli(directory, ['fixture', '--limit', '0', '--json']);
  assert.equal(result.status, 0, result.stderr);
  output = JSON.parse(result.stdout);
  assert.equal(output.bookmarks.length, 499);
  assert.equal(output.history.length, 501);
  assert.equal(output.more_available, false);
  assert.equal(JSON.parse(result.stderr).status, 'ok');
  assert.equal(JSON.parse(result.stderr).truncated, false);
});

test('read-only SQLite query includes committed WAL rows without copying the history database', { skip: !hasSqlite || !hasPython }, async t => {
  const directory = fixture(t);
  const profile = path.join(directory, 'Default');
  const writerCode = [
    'import sqlite3, sys',
    'connection = sqlite3.connect(sys.argv[1])',
    'connection.execute("PRAGMA journal_mode=WAL")',
    'connection.execute("PRAGMA wal_autocheckpoint=0")',
    'connection.execute("CREATE TABLE urls (title TEXT, url TEXT, last_visit_time INTEGER, visit_count INTEGER)")',
    'connection.commit()',
    'connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")',
    'connection.execute("INSERT INTO urls VALUES (?, ?, ?, ?)", ("fresh WAL fixture", "https://wal.example/", int(sys.argv[2]), 1))',
    'connection.commit()',
    'print("ready", flush=True)',
    'sys.stdin.read()',
    'connection.close()',
  ].join('\n');
  const writer = spawn('python3', ['-c', writerCode, path.join(profile, 'History'), visitTime(0)], { stdio: ['pipe', 'pipe', 'pipe'] });
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('WAL fixture did not become ready')), 5000);
      writer.once('error', error => { clearTimeout(timer); reject(error); });
      writer.once('exit', code => { clearTimeout(timer); reject(new Error('WAL fixture exited early: ' + code)); });
      writer.stdout.once('data', () => { clearTimeout(timer); resolve(); });
    });
    assert.ok(fs.statSync(path.join(profile, 'History-wal')).size > 0);
    const rows = searchHistory(profile, 'Fixture', 'ego', ['WAL'], null, 20, 'recent');
    assert.equal(rows.length, 1);
    assert.equal(rows[0].url, 'https://wal.example/');
    assert.deepEqual(fs.readdirSync(directory).sort(), ['Default', 'Local State', 'Profile 1']);
  } finally {
    await new Promise(resolve => {
      if (writer.exitCode !== null) { resolve(); return; }
      const timer = setTimeout(() => writer.kill('SIGKILL'), 2000);
      writer.once('exit', () => { clearTimeout(timer); resolve(); });
      writer.stdin.end();
    });
  }
});
