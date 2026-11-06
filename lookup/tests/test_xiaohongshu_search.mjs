import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, copyFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import vm from 'node:vm';
import { test } from 'node:test';

const root = path.resolve(import.meta.dirname, '..');
const original = readFileSync(path.join(root, 'tests/fixtures/xiaohongshu-search-builder.js'), 'utf8');
const temporary = mkdtempSync(path.join(tmpdir(), 'lookup-xhs-search-'));
let patched;
try {
  copyFileSync(path.join(root, 'tests/fixtures/xiaohongshu-search-builder.js'), path.join(temporary, 'search.js'));
  const result = spawnSync('patch', ['-p1', '-F', '0'], {
    cwd: temporary,
    input: readFileSync(path.join(root, 'patches/opencli-2.0.2-xiaohongshu-search.patch'), 'utf8'),
    encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  patched = readFileSync(path.join(temporary, 'search.js'), 'utf8');
} finally {
  rmSync(temporary, { recursive: true });
}

// Synthetic DOM exercises the actual upstream builder and the distributed patch.
async function search(options = {}, source = patched) {
  const query = 'Claude Code 新手入门';
  let clicks = 0;
  let clock = 0;
  const location = { pathname: '/explore', search: '' };
  class Element {
    constructor(id = '', hidden = false) {
      this.id = id;
      this.hidden = hidden;
      this.disabled = false;
      this.readOnly = false;
      this.ownerDocument = { defaultView: { getComputedStyle: e => e.style } };
      this.style = { display: 'block', visibility: 'visible', opacity: hidden ? '0.00001' : '1' };
    }
    closest(selector) {
      if (selector.includes('aria-hidden')) return this.hidden ? this : null;
      if (selector === '.textarea-container') return { querySelectorAll: () => buttons };
      return null;
    }
    getBoundingClientRect() { return { width: 400, height: 40 }; }
    focus() {}
    dispatchEvent() { return true; }
    getAttribute() { return null; }
    click() {
      clicks++;
      location.pathname = options.path ?? (options.legacy ? '/search_result' : '/search_result_ai');
      let keyword = options.keyword ?? query;
      if (options.doubleEncoded ?? !options.legacy) keyword = encodeURIComponent(keyword);
      location.search = '?' + new URLSearchParams({ keyword });
    }
  }
  class Input extends Element {
    get value() { return this._value ?? ''; }
    set value(value) { this._value = options.rejectValue ? '' : value; }
  }
  class TextArea extends Element {
    get value() { return this._value ?? ''; }
    set value(value) { this._value = options.rejectValue ? '' : value; }
  }
  const active = options.legacy ? new Input('search-input') : new TextArea(options.header ? 'search-input-ai' : 'search-input-in-feeds');
  active.disabled = options.disabled ?? false;
  active.readOnly = options.readOnly ?? false;
  const controls = [new Input('search-input', !options.legacy), new TextArea('', true), active];
  if (options.legacy) controls.shift();
  if (options.ambiguous) controls.push(new TextArea('search-input-ai'));
  const buttons = [new Element(), ...(options.duplicateButton ? [new Element()] : [])];
  const document = {
    body: { innerText: options.body ?? '' },
    querySelectorAll(selector) {
      if (selector === '#login-btn') return options.login ? [new Element()] : [];
      if (selector === '.search-icon') return options.legacy ? buttons : [];
      return controls.filter(control => selector.split(',').some(s => s.trim() === '#' + control.id));
    },
    querySelector() { return options.emptyShell ? null : {}; },
  };
  const context = vm.createContext({
    document, location, HTMLInputElement: Input, HTMLTextAreaElement: TextArea,
    URLSearchParams, Event, setTimeout: fn => { fn(); }, Date: { now: () => clock += 1000 },
    SEARCH_NAVIGATION_SECONDS: 10,
  });
  vm.runInContext(source, context);
  const script = vm.runInContext(`buildInSiteSearchJs(${JSON.stringify(query)})`, context);
  const result = await vm.runInContext(script, context);
  return { ...JSON.parse(JSON.stringify(result)), clicks, value: active.value };
}

test('baseline reproduces the live textarea failure', async () => {
  assert.equal((await search({}, original)).detail, 'search_input_not_available');
});
test('new feed textarea, hidden legacy input and hidden clone', async () => {
  assert.deepEqual(await search(), { status: 'ok', detail: '/search_result_ai', clicks: 1, value: 'Claude Code 新手入门' });
});
test('new header textarea and ordinary query encoding', async () => {
  assert.equal((await search({ header: true, doubleEncoded: false })).status, 'ok');
});
test('legacy input and route remain supported', async () => {
  assert.equal((await search({ legacy: true })).status, 'ok');
});
test('ambiguous controls or submit buttons are rejected', async () => {
  for (const options of [{ ambiguous: true }, { duplicateButton: true }]) {
    const result = await search(options);
    assert.equal(result.status, 'layout');
    assert.equal(result.clicks, 0);
  }
});
test('disabled, read-only and failed value updates are rejected', async () => {
  for (const options of [{ disabled: true }, { readOnly: true }, { rejectValue: true }]) {
    const result = await search(options);
    assert.equal(result.status, 'layout');
    assert.equal(result.clicks, 0);
  }
});
test('login and security walls stop before filling or submitting', async () => {
  for (const [options, status] of [[{ login: true }, 'auth'], [{ body: '请求太频繁' }, 'security_block']]) {
    const result = await search(options);
    assert.equal(result.status, status);
    assert.equal(result.clicks, 0);
    assert.equal(result.value, '');
  }
});
test('wrong query, unrelated route and empty shell are not accepted', async () => {
  for (const options of [{ keyword: 'unrelated' }, { path: '/ai_chat' }, { emptyShell: true }, { keyword: '%ZZ', doubleEncoded: false }]) {
    assert.equal((await search(options)).status, 'timeout');
  }
});
