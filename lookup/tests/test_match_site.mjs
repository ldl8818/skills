import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { findSitePatterns, matchesSite, parseSitePattern } from '../scripts/match-site.mjs';

test('a domain matches only itself and actual subdomains', () => {
  for (const query of ['example.com', 'https://example.com/article', 'https://www.example.com/article', 'EXAMPLE.COM', '查一下 example.com 的文章']) {
    assert.equal(matchesSite(query, 'example.com', ['例子']), true, query);
  }
  for (const query of ['notexample.com', 'example.com.attacker.invalid', 'https://example.com.attacker.invalid/path',
    'https://attacker.invalid/?next=example.com', 'attacker.invalid/?next=example.com',
    'https://example.com@attacker.invalid/', 'https://attacker.invalid/例子']) {
    assert.equal(matchesSite(query, 'example.com', ['例子']), false, query);
  }
});

test('natural-language aliases work with literal characters and ASCII boundaries', () => {
  assert.equal(matchesSite('帮我搜索例子里的文章', 'example.com', ['例子']), true);
  assert.equal(matchesSite('查 Stack Overflow 的答案', 'stackoverflow.com', ['Stack Overflow']), true);
  assert.equal(matchesSite('查 C++ 的例子', 'example.com', ['C++']), true);
  assert.equal(matchesSite('aSuperExampleb', 'example.com', ['SuperExample']), false);
  assert.equal(matchesSite('anything', 'example.com', ['.*']), false);
});

test('inline frontmatter parses quoted, unquoted, comma-containing and escaped aliases', () => {
  const raw = '---\naliases: [例子, "Example Site", \'示例\', "comma, name", \'someone\'\'s site\']\n---\nKeep this body.\n';
  const record = parseSitePattern(raw);
  assert.deepEqual(record.aliases, ['例子', 'Example Site', '示例', 'comma, name', "someone's site"]);
  assert.equal(record.body, 'Keep this body.\n');
});

test('multiline YAML alias lists are supported', () => {
  const record = parseSitePattern('---\naliases:\n  - "中文站点"\n  - example\nverified: true\n---\nBody');
  assert.deepEqual(record.aliases, ['中文站点', 'example']);
  assert.equal(record.body, 'Body');
});

test('horizontal rules in a normal document preserve the entire body', () => {
  const raw = '# Intro\nKeep before rules.\n---\nMiddle\n---\nEnd';
  assert.deepEqual(parseSitePattern(raw), { aliases: [], body: raw });
});

test('unterminated frontmatter is not removed and body aliases are not metadata', () => {
  const raw = '---\naliases: [example]\nNo closing fence';
  assert.deepEqual(parseSitePattern(raw), { aliases: [], body: raw });
  const bodyOnly = '# Guide\naliases: [example]\n---\nOther text\n---\n';
  assert.deepEqual(parseSitePattern(bodyOnly), { aliases: [], body: bodyOnly });
});

test('fixture directory is explicit, README and symlinks are not site records', t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'lookup-pattern-test-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  fs.writeFileSync(path.join(directory, 'example.com.md'), '---\naliases: ["例子"]\n---\nVerified body.\n');
  fs.writeFileSync(path.join(directory, 'README.md'), '---\naliases: [readme]\n---\nTemplate');
  fs.writeFileSync(path.join(directory, 'malformed?.com.md'), 'Wrong filename');
  fs.symlinkSync(path.join(directory, 'example.com.md'), path.join(directory, 'linked.example.md'));
  assert.deepEqual(findSitePatterns('https://www.example.com/page', directory), [{ domain: 'example.com', body: 'Verified body.\n' }]);
  assert.deepEqual(findSitePatterns('readme', directory), []);
  assert.deepEqual(findSitePatterns('例子', path.join(directory, 'missing')), []);
});
