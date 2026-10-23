#!/usr/bin/env node
// find-url — 只在 ego lite 的当前或显式指定 Profile 中查书签与历史。
// 用法：node find-url.mjs [关键词...] [--only bookmarks|history]
//        [--profile Default] [--limit N] [--since 1d|7h|YYYY-MM-DD] [--json]
// 多词按字面 AND 匹配；--limit 默认 20，0 表示最多 1000 条（有界全量）。
// 只读 SQLite 查询使用其事务快照并读取 WAL，不再复制整份私人历史库。

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const MAX_ROWS = 1000;
const QUERY_TIMEOUT_MS = 5000;
const QUERY_MAX_BYTES = 5 * 1024 * 1024;
const WEBKIT_EPOCH_DIFF_US = 11644473600000000n;
const historyTime = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});
// Match SQLite's built-in lower(): ASCII case-insensitive, non-ASCII literal.
const asciiLower = value => value.replace(/[A-Z]/g, char => char.toLowerCase());

export class LookupError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

export function parseArgs(argv) {
  const a = { keywords: [], only: null, browser: null, profile: null, limit: 20, since: null, sort: 'recent', json: false };
  const valueOptions = new Set(['--only', '--browser', '--profile', '--limit', '--since', '--sort']);
  for (let i = 0; i < argv.length; i++) {
    const v = argv[i];
    if (v === '--') { a.keywords.push(...argv.slice(i + 1)); break; }
    if (v === '--json') { a.json = true; continue; }
    if (v === '-h' || v === '--help') { a.help = true; continue; }
    if (valueOptions.has(v)) {
      const value = argv[++i];
      if (value === undefined || value.startsWith('--')) throw new LookupError('INVALID_ARGUMENT', v + ' 需要值');
      if (v === '--limit') {
        if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)) || Number(value) > MAX_ROWS) {
          throw new LookupError('INVALID_ARGUMENT', '--limit 需为 0 到 1000 的整数');
        }
        a.limit = Number(value);
      } else if (v === '--since') a.since = parseSince(value);
      else a[v.slice(2)] = value;
    } else if (v.startsWith('--')) throw new LookupError('INVALID_ARGUMENT', '未知参数');
    else a.keywords.push(v);
  }
  if (a.only && !['bookmarks', 'history'].includes(a.only)) throw new LookupError('INVALID_ARGUMENT', '--only 仅支持 bookmarks|history');
  if (!['recent', 'visits'].includes(a.sort)) throw new LookupError('INVALID_ARGUMENT', '--sort 仅支持 recent|visits');
  if (a.browser && a.browser !== 'ego') throw new LookupError('BROWSER_UNSUPPORTED', '本 Skill 固定只读 ego lite，不读取 Chrome 或 Edge 数据');
  if (a.only === 'bookmarks' && !a.keywords.length && !a.help) throw new LookupError('INVALID_ARGUMENT', '查询书签需要至少一个关键词');
  return a;
}

function parseSince(value) {
  const window = value.match(/^(\d+)([dhm])$/);
  const calendarDate = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const date = window
    ? new Date(Date.now() - Number(window[1]) * { d: 86400000, h: 3600000, m: 60000 }[window[2]])
    : new Date(calendarDate ? `${value}T00:00:00+08:00` : value);
  if (!Number.isFinite(date.getTime())
      || (calendarDate && new Date(value).toISOString().slice(0, 10) !== value)) {
    throw new LookupError('INVALID_ARGUMENT', '无效 --since 值');
  }
  return date;
}

function knownBrowserDataDirs() {
  if (os.platform() !== 'darwin') return [];
  return [{ id: 'ego', label: 'ego lite', dir: path.join(os.homedir(), 'Library/Application Support/Citro Labs/ego lite') }];
}

function safeProfileName(name) {
  return typeof name === 'string' && name.length > 0 && name !== '.' && name !== '..'
    && !/[\/\\\x00-\x1f]/.test(name) && !path.isAbsolute(name);
}

export function selectProfile(dataDir, requested) {
  let state = {};
  const statePath = path.join(dataDir, 'Local State');
  if (fs.existsSync(statePath)) {
    try { state = JSON.parse(fs.readFileSync(statePath, 'utf8')); }
    catch { throw new LookupError('PROFILE_STATE_INVALID', 'ego lite 的 Profile 索引无法读取'); }
  }
  const info = state?.profile?.info_cache || {};
  const chosen = requested || state?.profile?.last_used || 'Default';
  if (!safeProfileName(chosen)) throw new LookupError('PROFILE_INVALID', 'Profile 必须是登记的单个目录名');
  const registered = Object.prototype.hasOwnProperty.call(info, chosen);
  if (!registered && chosen !== 'Default') throw new LookupError('PROFILE_NOT_FOUND', '指定的 ego lite Profile 未登记');
  const directory = path.join(dataDir, chosen);
  if (!fs.existsSync(directory) || !fs.statSync(directory).isDirectory() || fs.lstatSync(directory).isSymbolicLink()) {
    throw new LookupError('PROFILE_NOT_FOUND', '指定的 ego lite Profile 目录不可用');
  }
  return { dir: chosen, name: registered ? info[chosen]?.name || chosen : chosen };
}

export function searchBookmarks(profileDir, profileName, browserLabel, keywords) {
  const file = path.join(profileDir, 'Bookmarks');
  if (!keywords.length) return [];
  if (!fs.existsSync(file)) throw new LookupError('BOOKMARKS_UNAVAILABLE', '所选 Profile 没有可读取的书签文件');
  let data;
  try { data = JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch { throw new LookupError('BOOKMARKS_UNREADABLE', '书签数据无法读取或格式无效'); }
  if (!data || !data.roots || typeof data.roots !== 'object' || Array.isArray(data.roots)) {
    throw new LookupError('BOOKMARKS_UNREADABLE', '书签数据缺少 roots 字段');
  }
  const needles = keywords.map(asciiLower);
  const out = [];
  function walk(node, trail) {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'url' && typeof node.url === 'string') {
      const name = typeof node.name === 'string' ? node.name : '';
      const hay = asciiLower(name + ' ' + node.url);
      if (needles.every(n => hay.includes(n))) out.push({ browser: browserLabel, profile: profileName, name, url: node.url, folder: trail.join(' / ') });
    }
    if (Array.isArray(node.children)) {
      const sub = typeof node.name === 'string' && node.name ? [...trail, node.name] : trail;
      for (const child of node.children) walk(child, sub);
    }
  }
  for (const root of Object.values(data.roots || {})) walk(root, []);
  return out;
}

export function searchHistory(profileDir, profileName, browserLabel, keywords, since, limit, sort) {
  const source = path.join(profileDir, 'History');
  if (!fs.existsSync(source)) throw new LookupError('HISTORY_UNAVAILABLE', '所选 Profile 没有可读取的历史文件');
  const quote = value => "'" + String(value).replaceAll("'", "''") + "'";
  const conds = ['last_visit_time > 0'];
  for (const keyword of keywords) {
    // instr makes % and _ literal; quotes are escaped as SQL string data.
    conds.push("instr(lower(coalesce(title, '') || ' ' || coalesce(url, '')), " + quote(asciiLower(keyword)) + ') > 0');
  }
  if (since) conds.push('last_visit_time >= ' + (BigInt(since.getTime()) * 1000n + WEBKIT_EPOCH_DIFF_US));
  const boundedLimit = Math.max(1, Math.min(Number(limit) || MAX_ROWS, MAX_ROWS + 1));
  const orderBy = sort === 'visits' ? 'visit_count DESC, last_visit_time DESC' : 'last_visit_time DESC';
  const sql = "SELECT coalesce(title, '') AS title, url, "
    + "datetime((last_visit_time - 11644473600000000)/1000000, 'unixepoch') AS visit, "
    + 'visit_count FROM urls WHERE ' + conds.join(' AND ')
    + ' ORDER BY ' + orderBy + ' LIMIT ' + boundedLimit + ';';
  let raw;
  try {
    raw = execFileSync('sqlite3', ['-init', os.devNull, '-batch', '-readonly', '-json', '-cmd', '.timeout 2000', source, sql], {
      encoding: 'utf8', timeout: QUERY_TIMEOUT_MS, killSignal: 'SIGKILL', maxBuffer: QUERY_MAX_BYTES,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (error) {
    // Chromium may hold an exclusive rollback-journal lock while it is open.
    // Do not ignore locks or copy a live database: either can lose committed data.
    if (/database (?:table )?is locked|database is busy|database locked/i.test(String(error.stderr || ''))) {
      throw new LookupError('HISTORY_LOCKED', '历史库正被浏览器锁定；在同一 Ego Lite Profile 的 chrome://history/ 搜索原关键词并核对日期。不要关闭用户浏览器、复制数据库或忽略锁；这不是无匹配');
    }
    const code = error.code === 'ENOENT' ? 'DEPENDENCY_UNAVAILABLE'
      : error.code === 'ETIMEDOUT' ? 'HISTORY_TIMEOUT'
      : error.code === 'ENOBUFS' ? 'OUTPUT_LIMIT' : 'HISTORY_UNREADABLE';
    throw new LookupError(code, '历史查询失败；不是没有匹配记录。请检查 sqlite3、数据库状态或缩小查询范围');
  }
  let rows;
  try { rows = JSON.parse(raw.trim() || '[]'); }
  catch { throw new LookupError('HISTORY_INVALID_RESULT', '历史查询返回了无效 JSON'); }
  if (!Array.isArray(rows) || rows.some(row => !row || typeof row.title !== 'string'
      || typeof row.url !== 'string' || typeof row.visit !== 'string'
      || !Number.isInteger(row.visit_count) || row.visit_count < 0)) {
    throw new LookupError('HISTORY_INVALID_RESULT', '历史查询缺少必要字段');
  }
  return rows.map(row => ({ browser: browserLabel, profile: profileName, ...row,
    visit: historyTime.format(new Date(row.visit.replace(' ', 'T') + 'Z')) }));
}

// Human-readable output cannot let a page title create another result line.
export const cleanField = value => String(value ?? '').replaceAll('|', '│').replace(/[\x00-\x1f\x7f]/g, ' ').trim();

export function main(argv = process.argv.slice(2), browserDirs = knownBrowserDataDirs()) {
  try {
    const args = parseArgs(argv);
    if (args.help) {
      console.log('用法：node find-url.mjs [关键词...] [--only bookmarks|history] [--profile Default] [--limit 0..1000] [--since 7d] [--sort recent|visits] [--json]');
      return 0;
    }
    const browser = browserDirs.find(item => item.id === 'ego' && fs.existsSync(item.dir));
    if (!browser) throw new LookupError('BROWSER_DATA_UNAVAILABLE', '未找到 ego lite 用户数据目录');
    const profile = selectProfile(browser.dir, args.profile);
    const profileDir = path.join(browser.dir, profile.dir);
    const cap = args.limit || MAX_ROWS;
    const bookmarks = args.only === 'history' ? [] : searchBookmarks(profileDir, profile.name, browser.label, args.keywords);
    const history = args.only === 'bookmarks' ? [] : searchHistory(profileDir, profile.name, browser.label, args.keywords, args.since, cap + 1, args.sort);
    const bookmarksOut = bookmarks.slice(0, cap);
    const historyOut = history.slice(0, cap - bookmarksOut.length);
    const moreAvailable = bookmarks.length > bookmarksOut.length || history.length > historyOut.length;
    const result = { profile: profile.dir, bookmarks: bookmarksOut, history: historyOut, more_available: moreAvailable };
    const truncated = args.limit === 0 && moreAvailable;
    if (args.json) console.log(JSON.stringify(result));
    else {
      if (args.only !== 'history') {
        console.log('[书签] ' + result.bookmarks.length + ' 条');
        for (const row of result.bookmarks) console.log('  ' + [row.name || '(无标题)', row.url, row.folder].filter(Boolean).map(cleanField).join(' | '));
      }
      if (args.only !== 'bookmarks') {
        console.log('[历史] ' + result.history.length + ' 条');
        for (const row of result.history) console.log('  ' + [row.title || '(无标题)', row.url, row.visit, 'visits=' + row.visit_count].map(cleanField).join(' | '));
      }
      if (truncated) console.log('[TRUNCATED: 最多返回 1000 条；请使用关键词或 --since 缩小范围。]');
    }
    const empty = !result.bookmarks.length && !result.history.length;
    console.error(JSON.stringify({ provider: 'lookup/find-url', status: truncated ? 'partial' : empty ? 'empty' : 'ok',
      truncated, empty_confirmed: empty, more_available: moreAvailable }));
    return truncated ? 3 : 0;
  } catch (error) {
    console.error(JSON.stringify({ provider: 'lookup/find-url', status: 'error',
      error: { code: error instanceof LookupError ? error.code : 'LOCAL_READ_FAILED',
        message: error instanceof LookupError ? error.message : '本机检索失败；没有返回历史或书签内容' } }));
    return 1;
  }
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  process.exitCode = main();
}
