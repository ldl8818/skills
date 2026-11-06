import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import vm from 'node:vm';
import { extractTwitterMetrics } from '../patches/opencli-engagement/twitter-engagement.js';
import * as xhs from '../patches/opencli-engagement/xiaohongshu-engagement.js';

const root = path.resolve(import.meta.dirname, '..');
const fixture = JSON.parse(readFileSync(path.join(root, 'tests/fixtures/engagement-readers.json'), 'utf8'));
const baseline = process.env.LOOKUP_METRICS_BASELINE === '1';
const patchFile = path.join(root, 'patches/opencli-2.0.2-engagement.patch');
const patch = baseline ? '' : readFileSync(patchFile, 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

// Replay the actual distributed hunks against exact, small upstream excerpts.
// Ignore hunks outside the excerpt; never invent a separate replacement mapper.
function patchedFragment(source, filename, diff = patch) {
  const lines = diff.split('\n');
  let active = false;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].startsWith('+++ ')) {
      active = lines[i] === `+++ b/${filename}`;
      continue;
    }
    if (!active || !lines[i].startsWith('@@')) continue;
    const hunk = [];
    for (i++; i < lines.length && /^[ +\-]/.test(lines[i]) && !lines[i].startsWith('--- '); i++) {
      hunk.push(lines[i]);
    }
    i--;
    const fullBefore = hunk.filter(line => !line.startsWith('+')).map(line => line.slice(1)).join('\n');
    const fullAfter = hunk.filter(line => !line.startsWith('-')).map(line => line.slice(1)).join('\n');
    if (fullBefore && source.includes(fullBefore)) {
      source = source.replace(fullBefore, fullAfter);
      continue;
    }
    const first = hunk.findIndex(line => /^[+-]/.test(line));
    const last = hunk.findLastIndex(line => /^[+-]/.test(line));
    if (first < 0) continue;
    const changed = hunk.slice(first, last + 1);
    const before = changed.filter(line => !line.startsWith('+')).map(line => line.slice(1)).join('\n');
    const after = changed.filter(line => !line.startsWith('-')).map(line => line.slice(1)).join('\n');
    if (before && source.includes(before)) source = source.replace(before, after);
  }
  return source;
}

function context(extra = {}) {
  return vm.createContext({
    cli: definition => definition,
    Strategy: { COOKIE: 'cookie' },
    extractTwitterMetrics,
    extractAuthorAvatar: () => '',
    extractMedia: () => ({}),
    extractCard: () => null,
    extractQuotedTweet: () => null,
    normalizeTwitterScreenName: name => name,
    extractRelationship: () => ({ kind: 'original', target: null }),
    unwrapTweetResult: result => result?.tweet || result,
    ...extra,
  });
}

const counters = {
  likes: 11, retweets: 22, replies: 33, quotes: 44, bookmarks: 55, shares: null,
};
const tweet = {
  rest_id: '123',
  core: { user_results: { result: { legacy: { screen_name: 'example' } } } },
  legacy: {
    favorite_count: 11, retweet_count: 22, reply_count: 33, quote_count: 44, bookmark_count: 55,
    full_text: 'Synthetic public post',
    retweeted_status_result: { result: { legacy: { favorite_count: 999 } } },
  },
  views: { count: '66' },
  quoted_status_result: { result: { legacy: { favorite_count: 888, bookmark_count: 777 } } },
};
for (const [name, reader] of Object.entries(fixture.twitter)) {
  function extract(input) {
    const ctx = context();
    vm.runInContext(patchedFragment(reader.source, `twitter/${name}.js`).replace(/^export /, ''), ctx);
    return plain(ctx[reader.name](input, new Set()));
  }
  test(`X ${name}: every counter belongs to the outer post, including wrapped results`, () => {
    for (const input of [tweet, { __typename: 'TweetWithVisibilityResults', tweet }]) {
      const row = extract(input);
      assert.equal(row.id, '123');
      for (const [key, value] of Object.entries(counters)) assert.equal(row[key], value, `${name}.${key}`);
      assert.equal(row.views, ['search', 'thread', 'list-tweets'].includes(name) ? '66' : 66);
    }
  });
  test(`X ${name}: absent counters remain unknown and explicit zeros survive`, () => {
    const missing = extract({ ...tweet, legacy: { full_text: 'Synthetic' }, views: {} });
    for (const key of [...Object.keys(counters), 'views']) assert.equal(missing[key], null, `${name}.${key}`);
    const zero = extract({
      ...tweet,
      legacy: { favorite_count: 0, retweet_count: 0, reply_count: 0, quote_count: 0, bookmark_count: 0 },
      views: { count: '0' },
    });
    for (const key of Object.keys(counters).filter(key => key !== 'shares')) assert.equal(zero[key], 0);
    assert.equal(Number(zero.views), 0);
  });
}

test('X rejects negative, fractional, malformed and unsafe counters without creating zero', () => {
  for (const value of [undefined, null, '', '1.2K', '12junk', -1, 1.5, NaN, Infinity, 2 ** 54, {}, true]) {
    const row = extractTwitterMetrics({ legacy: { favorite_count: value }, views: { count: value } });
    assert.equal(row.likes, null);
    assert.equal(row.views, null);
  }
});

const id = '000000000000000000000001';
async function readNote(data, globals = {}) {
  const ctx = context({
    ...xhs,
    parseNoteId: () => id,
    buildNoteUrl: raw => raw,
    readXhsDetailPage: async (_page, options) =>
      data ?? vm.runInContext(options.extractJs, ctx),
    ...globals,
  });
  let source = patchedFragment(fixture.xiaohongshu.note, 'xiaohongshu/note.js');
  source = source.replace(/^import .*;$/gm, '').replace(/export const /g, 'const ');
  vm.runInContext(`${source}\nglobalThis.read = command.func;`, ctx);
  return Object.fromEntries(plain(await ctx.read({}, { 'note-id': `https://example.test/explore/${id}` }))
    .map(row => [row.field, row.value]));
}

test('XHS note exposes all four exact counters, including the state-only share count', async () => {
  const row = await readNote({ title: 'Synthetic', author: 'Example', likes: '11', collects: '22', comments: '33', shares: '44' });
  assert.equal(row.likes, '11');
  assert.equal(row.collects, '22');
  assert.equal(row.comments, '33');
  assert.equal(row.shares, '44');
});

test('XHS note preserves unknown values instead of inventing zero', async () => {
  const row = await readNote({ title: 'Synthetic', author: 'Example', likes: '', collects: '0', comments: 'unavailable' });
  assert.equal(row.likes, null);
  assert.equal(row.collects, '0');
  assert.equal(row.comments, null);
  assert.equal(row.shares, null);
});

test('XHS browser extraction scopes counters to the target note and its exact state ID', async () => {
  const ownBar = { querySelector: selector => ({ textContent: {
    '.like-wrapper .count': '11', '.collect-wrapper .count': '22', '.chat-wrapper .count': '33',
  }[selector] }) };
  const scope = { querySelector: selector => selector === '.interact-container'
    ? ownBar : { textContent: selector === '.username, .author-wrapper .name' ? 'Example' : 'Synthetic' } };
  const row = await readNote(null, {
    location: { href: `https://example.test/explore/${id}`, pathname: `/explore/${id}` },
    document: {
      body: { innerText: 'Synthetic note' },
      querySelector: selector => selector === '#noteContainer' ? scope : { textContent: '999' },
      querySelectorAll: () => [],
    },
    window: { __INITIAL_STATE__: { note: { noteDetailMap: {
      wrong: { note: { noteId: 'wrong', interactInfo: { shareCount: '999' } } },
      [id]: { note: { noteId: id, interactInfo: { shareCount: '44' } } },
    } } } },
  });
  assert.deepEqual([row.likes, row.collects, row.comments, row.shares], ['11', '22', '33', '44']);
});

test('XHS missing share counter stays unknown even when a share button exists', () => {
  const bar = { querySelector: () => null };
  const scope = { querySelector: () => bar };
  const row = xhs.readXhsNoteMetrics(id, scope, [{ noteDetailMap: {
    [id]: { note: { noteId: 'wrong', interactInfo: { shareCount: '999' } } },
  } }]);
  assert.equal(row.shares, null);
  assert.equal(row.likes, null);
  assert.equal(xhs.normalizeXhsCount('赞', ['赞']), '0');
  assert.equal(xhs.normalizeXhsCount(''), null);
  assert.equal(xhs.normalizeXhsCount('1.2万'), '1.2万');
});

test('XHS card uses the dedicated count and rejects ambiguous generic counters', () => {
  const specific = { textContent: '22' };
  const card = { querySelector: () => specific, querySelectorAll: () => [{ textContent: '999' }] };
  assert.equal(xhs.readXhsCardCount(card), '22');
  card.querySelector = () => null;
  card.querySelectorAll = () => [{ textContent: '999' }, { textContent: '888' }];
  assert.equal(xhs.readXhsCardCount(card), null);
});

test('X legacy notification-feed rows preserve the same metrics without inventing views', () => {
  const ctx = context();
  vm.runInContext(patchedFragment(fixture.twitter_device_follow, 'twitter/device-follow.js'), ctx);
  const row = plain(ctx.shapeRow({ tweetId: '123', tweet: tweet.legacy, user: { screen_name: 'example' } }));
  for (const [key, value] of Object.entries(counters)) assert.equal(row[key], value);
  assert.equal(row.views, null);
  const missing = plain(ctx.shapeRow({ tweetId: '123', tweet: {}, user: { screen_name: 'example' } }));
  assert.equal(missing.likes, null);
  assert.equal(missing.replies, null);
});

test('quoted post counters stay inside the quoted object and use its own legacy data', () => {
  const quoted = { ...tweet, rest_id: '456', legacy: { ...tweet.legacy, favorite_count: 888 } };
  const ctx = context({
    SCREEN_NAME_PATTERN: /^[A-Za-z0-9_]{1,15}$/,
    extractMedia: () => ({ has_media: false }),
  });
  vm.runInContext(patchedFragment(fixture.twitter_quoted, 'twitter/shared.js').replace(/^export /, ''), ctx);
  const row = plain(ctx.extractQuotedTweet({
    legacy: { is_quote_status: true }, quoted_status_result: { result: quoted },
  }));
  assert.equal(row.id, '456');
  assert.equal(row.likes, 888);
  assert.equal(row.bookmarks, 55);
});

test('XHS search output maps the displayed counter to the verified sort and preserves all unknowns', async () => {
  const oldPatch = readFileSync(path.join(root, 'patches/opencli-2.0.2-xiaohongshu-search-metrics.patch'), 'utf8');
  let source = readFileSync(path.join(root, 'tests/fixtures/xiaohongshu-search-command.js'), 'utf8');
  source = patchedFragment(source, 'search.js', oldPatch);
  if (!baseline) source = patchedFragment(source, 'xiaohongshu/search.js');
  for (const [sort, field] of [
    ['comprehensive', 'likes'], ['latest', 'likes'], ['most-liked', 'likes'],
    ['most-collected', 'collects'], ['most-commented', 'comments'],
  ]) {
    for (const count of ['123', '0', '1.2万', '']) {
      const ctx = context({
        ...xhs,
        parseLimit: value => value,
        resolveSearchFilters: () => [],
        openSearchResults: async () => {},
        collectSearchHarvest: async () => ({ rows: [{ title: 'Synthetic', likes: count, url: 'synthetic' }], diag: {} }),
        isCollapsedRender: () => false,
        noteIdToDate: () => '',
      });
      vm.runInContext(source.replace('export const command =', 'globalThis.command ='), ctx);
      const [row] = plain(await ctx.command.func({}, { query: 'synthetic', limit: 1, sort }));
      for (const key of ['likes', 'collects', 'comments', 'shares']) {
        assert.equal(row[key], key === field && count !== '' ? count : null, `${sort}.${key}`);
      }
    }
  }
});

test('XHS saved/liked and user-list rows retain every supplied metric without defaulting missing likes', () => {
  for (const [name, file] of [
    ['mapCollectionNote', 'collection-helpers'], ['extractXhsUserNotes', 'user-helpers'],
  ]) {
    const ctx = context({
      ...xhs, toCleanString: v => v == null ? '' : String(v),
      isObject: v => v && typeof v === 'object',
      buildXhsNoteUrl: () => 'https://example.test/note',
      flattenXhsNoteGroups: groups => groups,
    });
    vm.runInContext(patchedFragment(fixture.xiaohongshu[name], `xiaohongshu/${file}.js`).replace(/^export /, ''), ctx);
    for (const info of [
      { likedCount: '11', collectedCount: '22', commentCount: '33', shareCount: '44' },
      { liked_count: '11', collected_count: '22', comment_count: '33', share_count: '44' },
      {},
    ]) {
      const card = { noteId: id, user: { userId: 'example' }, xsecToken: 'synthetic', interactInfo: info };
      const rows = name === 'mapCollectionNote'
        ? [ctx[name](card)]
        : ctx[name]({ noteGroups: [card] }, 'example');
      assert.equal(rows.length, 1);
      const row = plain(rows[0]);
      assert.deepEqual([row.likes, row.collects, row.comments, row.shares],
        Object.keys(info).length ? ['11', '22', '33', '44'] : [null, null, null, null]);
    }
  }
});

test('XHS comment-like parser distinguishes labels and real zero from a missing or unreadable count', () => {
  const ctx = context();
  vm.runInContext(patchedFragment(fixture.xiaohongshu.parseXhsLikeCountText, 'xiaohongshu/comments.js').replace(/^export /, ''), ctx);
  for (const [input, expected] of [
    ['', null], [undefined, null], ['unavailable', null], ['赞', 0], ['0', 0], ['12', 12], ['1.2万', 12000],
  ]) assert.equal(ctx.parseXhsLikeCountText(input), expected);
});

test('XHS creator API and summary use named fields and preserve unknown values', () => {
  const ctx = context({
    ...xhs, formatPostTime: () => '', buildNoteDetailUrl: () => '',
    findDetailValue: (rows, metric) => rows.find(row => row.metric === metric)?.value ?? '',
    findTopBySectionPrefix: () => ({ label: '', value: '' }),
  });
  vm.runInContext(patchedFragment(fixture.xiaohongshu.mapAnalyzeItems, 'xiaohongshu/creator-notes.js'), ctx);
  const [row] = plain(ctx.mapAnalyzeItems([{ like_count: 11, comment_count: 22, fav_count: 33 }]));
  assert.deepEqual([String(row.likes), String(row.comments), String(row.collects)], ['11', '22', '33']);
  const [missing] = plain(ctx.mapAnalyzeItems([{}]));
  assert.deepEqual([missing.likes, missing.comments, missing.collects], [null, null, null]);
  vm.runInContext(patchedFragment(fixture.xiaohongshu.summarizeCreatorNote, 'xiaohongshu/creator-notes-summary.js').replace(/^export /, ''), ctx);
  const summary = plain(ctx.summarizeCreatorNote({ id: 'synthetic', likes: 0 }, [], 1));
  assert.equal(summary.likes, '0');
  assert.equal(summary.comments, null);
  assert.equal(summary.collects, null);
});
