#!/usr/bin/env node
// 根据目标主机名或自然语言别名读取本地站点经验，不执行文件中的内容。
// 用法：node match-site.mjs "<用户输入或目标域名>"
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

function aliasValue(value) {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (trimmed.startsWith('"')) {
    try { return JSON.parse(trimmed); } catch { return ''; }
  }
  if (trimmed.startsWith("'")) {
    return trimmed.endsWith("'") ? trimmed.slice(1, -1).replace(/''/g, "'") : '';
  }
  return trimmed.replace(/\s+#.*$/, '').trim();
}

function inlineAliases(value) {
  if (!value.startsWith('[') || !value.endsWith(']')) return [];
  const parts = [];
  let start = 1;
  let quote = '';
  for (let index = 1; index < value.length - 1; index += 1) {
    const char = value[index];
    if (quote) {
      if (quote === '"' && char === '\\') { index += 1; continue; }
      if (quote === "'" && char === "'" && value[index + 1] === "'") { index += 1; continue; }
      if (char === quote) quote = '';
    } else if (char === '"' || char === "'") {
      quote = char;
    } else if (char === ',') {
      parts.push(value.slice(start, index));
      start = index + 1;
    }
  }
  if (quote) return [];
  parts.push(value.slice(start, -1));
  return parts.map(aliasValue).filter(value => typeof value === 'string' && value);
}

export function parseSitePattern(raw) {
  const lines = raw.replace(/^\uFEFF/, '').split(/\r?\n/);
  // Markdown horizontal rules inside ordinary content are not frontmatter.
  if (!/^---\s*$/.test(lines[0])) return { aliases: [], body: raw };
  const end = lines.findIndex((line, index) => index > 0 && /^---\s*$/.test(line));
  if (end < 0) return { aliases: [], body: raw };
  const metadata = lines.slice(1, end);
  const aliasIndex = metadata.findIndex(line => /^aliases:\s*/.test(line));
  let aliases = [];
  if (aliasIndex >= 0) {
    const value = metadata[aliasIndex].replace(/^aliases:\s*/, '').trim();
    if (value) {
      aliases = inlineAliases(value);
    } else {
      for (const line of metadata.slice(aliasIndex + 1)) {
        const item = line.match(/^\s+-\s+(.+?)\s*$/);
        if (!item) break;
        const alias = aliasValue(item[1]);
        if (typeof alias === 'string' && alias) aliases.push(alias);
      }
    }
  }
  return { aliases, body: lines.slice(end + 1).join('\n') };
}

function hostname(value) {
  try {
    const url = new URL(/^[a-z][a-z\d+.-]*:\/\//i.test(value) ? value : 'https://' + value);
    return url.hostname.toLowerCase().replace(/\.$/, '');
  } catch { return ''; }
}

function queryHosts(query) {
  const explicit = query.match(/https?:\/\/[^\s<>"'，。！？；）]+/gi);
  if (explicit) return explicit.map(hostname).filter(Boolean);
  // Consume a whole host and its optional path, so x.com.evil.invalid and
  // evil.invalid/?next=x.com cannot become an x.com match.
  const bare = query.match(/(?<![\p{L}\p{N}_@.-])(?:[a-z\d](?:[a-z\d-]*[a-z\d])?\.)+[a-z]{2,63}(?::\d+)?(?:[/?#][^\s<>"'，。！？；）]*)?(?![\p{L}\p{N}_@.-])/giu);
  return bare ? bare.map(hostname).filter(Boolean) : [];
}

export function matchesSite(query, domain, aliases = []) {
  const expected = hostname(domain);
  if (!expected) return false;
  const hosts = queryHosts(query);
  if (hosts.length) return hosts.some(host => host === expected || host.endsWith('.' + expected));
  return aliases.some(alias => {
    if (typeof alias !== 'string' || !alias.trim()) return false;
    const escaped = alias.replace(/[.*+?^$(){}|[\]\\]/g, '\\$&');
    // Word boundaries protect ASCII aliases; CJK names may occur in a sentence.
    const pattern = /^[\x00-\x7F]+$/.test(alias)
      ? '(?<![\\p{L}\\p{N}_])' + escaped + '(?![\\p{L}\\p{N}_])'
      : escaped;
    return new RegExp(pattern, 'iu').test(query);
  });
}

export function findSitePatterns(query, patternsDir) {
  if (!fs.existsSync(patternsDir)) return [];
  const matches = [];
  for (const entry of fs.readdirSync(patternsDir, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith('.md') || entry.name.toLowerCase() === 'readme.md') continue;
    const domain = entry.name.slice(0, -3);
    if (!/^(?:[a-z\d](?:[a-z\d-]*[a-z\d])?\.)+[a-z]{2,63}$/i.test(domain)) continue;
    const record = parseSitePattern(fs.readFileSync(path.join(patternsDir, entry.name), 'utf8'));
    if (matchesSite(query, domain, record.aliases)) matches.push({ domain, body: record.body });
  }
  return matches;
}

export function main(argv = process.argv.slice(2), patternsDir = path.join(os.homedir(), '.agents', 'data', 'site-patterns')) {
  const query = (argv[0] || '').trim();
  if (!query) {
    console.log('用法：node match-site.mjs "<用户输入或目标域名>"');
    return 0;
  }
  if (!fs.existsSync(patternsDir)) {
    console.log('站点经验目录不存在（先创建 ~/.agents/data/site-patterns）');
    return 0;
  }
  const matches = findSitePatterns(query, patternsDir);
  for (const { domain, body } of matches) {
    process.stdout.write('--- 站点经验: ' + domain + ' ---\n' + body.trimEnd() + '\n\n');
  }
  if (!matches.length) console.log('没有匹配的站点经验——按常规通道选路，验证过的模式记得写回。');
  return 0;
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try { process.exitCode = main(); }
  catch { console.error('站点经验读取失败；请检查本地文件后重试。'); process.exitCode = 1; }
}
