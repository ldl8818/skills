import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import test, { after } from 'node:test';

const lookup = new URL('../', import.meta.url);
const receipt = JSON.parse(await readFile(new URL('upstream/opencli.json', lookup), 'utf8'));
const directory = await mkdtemp(join(tmpdir(), 'lookup-twitter-patch-'));
after(() => rm(directory, { recursive: true, force: true }));
await mkdir(join(directory, 'twitter'));
await mkdir(join(directory, 'baseline'));
await writeFile(join(directory, 'package.json'), JSON.stringify({ type: 'module' }));
for (const name of ['thread.js', 'download.js']) {
  const content = await readFile(new URL(`tests/fixtures/opencli-2.0.2/twitter/${name}`, lookup));
  const expected = receipt.files[`clis/twitter/${name}`];
  assert.equal(content.length, expected.size, name);
  assert.equal(createHash('sha256').update(content).digest('hex'), expected.sha256, name);
  await writeFile(join(directory, 'twitter', name), content);
  if (name === 'thread.js') await writeFile(join(directory, 'baseline', name), content);
}

const patch = await readFile(new URL('patches/opencli-2.0.2-twitter-download.patch', lookup));
for (const dryRun of [true, false]) {
  execFileSync('patch', [...(dryRun ? ['--dry-run'] : []), '-p1', '-F', '0'], {
    cwd: join(directory, 'twitter'), input: patch, stdio: ['pipe', 'pipe', 'pipe'],
  });
}

// Only replace external boundaries. TweetDetail parsing, pagination, selection,
// download orchestration and the published patch remain the actual source.
const stubs = `
export const registry = new Map();
export const downloads = [];
export const rankings = [];
export const Strategy = { COOKIE: 'cookie' };
export function cli(command) { registry.set(command.name, command); }
export class CliError extends Error {}
export class ArgumentError extends CliError {}
export class AuthRequiredError extends CliError {}
export class CommandExecutionError extends CliError {}
export class EmptyResultError extends CliError {}
export const BROWSER_JSON_SNIFF_FN = '';
export const TWITTER_BEARER_TOKEN = 'synthetic-public-token';
export const throwIfLoginWall = value => value;
export const formatCookieHeader = () => 'synthetic=fixture';
export const unwrapBrowserResult = value => value;
export const normalizeTwitterGraphqlPayload = value => value;
export const normalizeTwitterScreenName = value => value;
export function resolveTwitterOperationMetadata() { throw new Error('unexpected profile-media flow'); }
export function parseTweetUrl(raw) {
  const url = new URL(raw);
  return { id: url.pathname.split('/').at(-1), url: url.href };
}
export const extractAuthorAvatar = () => '';
export const extractCard = () => null;
export const extractQuotedTweet = () => null;
export function extractMedia(legacy) {
  const media = legacy.extended_entities?.media || [];
  return { has_media: media.length > 0, media_urls: media.map(item => item.media_url_https),
    media_posters: [], media_durations: [] };
}
export const describeTwitterApiError = (operation, error) => operation + ':' + error;
export function applyTopByEngagement(rows, topN) {
  rankings.push({ ids: rows.map(row => row.id), topN });
  return topN > 0 ? rows.slice().sort((a,b) => b.likes - a.likes).slice(0,topN) : rows;
}
export async function downloadMedia(items, options) {
  downloads.push({ items, options });
  return items.map((item,index) => ({ index, type: item.type, status: 'success', size: 1 }));
}
`;
await writeFile(join(directory, 'stubs.mjs'), stubs);
for (const relative of ['baseline/thread.js', 'twitter/thread.js', 'twitter/download.js']) {
  const file = join(directory, relative);
  let content = await readFile(file, 'utf8');
  content = content.replace(/from '(?:@jackwener\/opencli[^']*|\.\/shared\.js|\.\/utils\.js)'/g, "from '../stubs.mjs'");
  await writeFile(file, content);
}
const mocks = await import(pathToFileURL(join(directory, 'stubs.mjs')));
await import(pathToFileURL(join(directory, 'baseline/thread.js')));
const baselineThread = mocks.registry.get('thread').func;
const { readThread } = await import(pathToFileURL(join(directory, 'twitter/thread.js')));
await import(pathToFileURL(join(directory, 'twitter/download.js')));
const download = mocks.registry.get('download').func;

function tweet(id, likes = 1) {
  return { rest_id: id, core: { user_results: { result: { legacy: { screen_name: 'fixture' } } } },
    legacy: { full_text: `Synthetic tweet ${id}`, favorite_count: likes,
      extended_entities: { media: [{ media_url_https: `https://pbs.twimg.com/media/${id}.jpg?name=small` }] } } };
}
function detail(tweets, cursor) {
  const entries = tweets.map(value => ({ entryId: `tweet-${value.rest_id}`,
    content: { itemContent: { tweet_results: { result: value } } } }));
  if (cursor) entries.push({ entryId: `cursor-bottom-${cursor}`,
    content: { entryType: 'TimelineTimelineCursor', cursorType: 'Bottom', value: cursor } });
  return { data: { threaded_conversation_with_injections_v2: { instructions: [{ entries }] } } };
}
function page(responses) {
  const calls = [];
  return { calls,
    getCookies: async () => [{ name: 'ct0', value: 'synthetic-csrf' }],
    evaluate: async source => {
      calls.push(source);
      assert.ok(calls.length <= responses.length, 'must not fetch beyond the supplied target page');
      return structuredClone(responses[calls.length - 1]);
    },
  };
}
async function downloadTarget(responses) {
  mocks.downloads.length = 0;
  const browser = page(responses);
  const rows = await download(browser, { 'tweet-url': 'https://x.com/fixture/status/200', output: 'synthetic-output' });
  assert.deepEqual(rows.map(row => row.tweet_id), ['200']);
  assert.equal(mocks.downloads.length, 1);
  assert.deepEqual(mocks.downloads[0].items.map(item => item.tweet_id), ['200']);
  assert.match(mocks.downloads[0].items[0].url, /\/media\/200\.jpg\?name=orig$/);
  return browser;
}

test('download stops on the first target page even when a parent precedes it', async () => {
  const browser = await downloadTarget([detail([tweet('100'), tweet('200'), tweet('201')], 'next')]);
  assert.equal(browser.calls.length, 1);
});

test('download finds the exact target on page two and skips all later replies', async () => {
  const browser = await downloadTarget([
    detail([tweet('100')], 'page-two'), detail([tweet('101'), tweet('200')], 'page-three'),
  ]);
  assert.equal(browser.calls.length, 2);
  assert.match(browser.calls[1], /page-two/);
});

test('ordinary thread keeps its pagination, structural ordering, limit and ranking calls', async () => {
  const responses = Array.from({ length: 5 }, (_, index) =>
    detail([tweet(String(100 + index), index + 1)], `page-${index + 2}`));
  for (const kwargs of [{ 'tweet-id': '200', limit: 4, 'top-by-engagement': 0 },
    { 'tweet-id': '200', limit: 4, 'top-by-engagement': 2 }]) {
    const before = page(responses);
    const after = page(responses);
    assert.deepEqual(await readThread(after, kwargs), await baselineThread(before, kwargs));
    assert.equal(before.calls.length, 5);
    assert.equal(after.calls.length, 5);
  }
});

test('five pages without the target reject the download and write no media', async () => {
  mocks.downloads.length = 0;
  const browser = page(Array.from({ length: 5 }, (_, index) => detail([tweet(String(100 + index))], `page-${index + 2}`)));
  await assert.rejects(download(browser, { 'tweet-url': 'https://x.com/fixture/status/200' }), /requested tweet/);
  assert.equal(browser.calls.length, 5);
  assert.equal(mocks.downloads.length, 0);
});

test('an API error before any content preserves failure and does not download', async () => {
  mocks.downloads.length = 0;
  const browser = page([{ error: 429 }]);
  await assert.rejects(download(browser, { 'tweet-url': 'https://x.com/fixture/status/200' }), /TweetDetail:429/);
  assert.equal(browser.calls.length, 1);
  assert.equal(mocks.downloads.length, 0);
});

test('mid-pagination API errors retain ordinary partial-thread behavior and never download another tweet', async () => {
  const responses = [detail([tweet('100')], 'page-two'), { error: 429 }];
  const kwargs = { 'tweet-id': '200', limit: 50, 'top-by-engagement': 0 };
  assert.deepEqual(await readThread(page(responses), kwargs), await baselineThread(page(responses), kwargs));
  mocks.downloads.length = 0;
  const browser = page(responses);
  await assert.rejects(download(browser, { 'tweet-url': 'https://x.com/fixture/status/200' }), /requested tweet/);
  assert.equal(browser.calls.length, 2);
  assert.equal(mocks.downloads.length, 0);
});
