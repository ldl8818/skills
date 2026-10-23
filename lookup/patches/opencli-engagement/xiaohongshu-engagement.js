// Local OpenCLI 2.0.2 adapter support. Counts absent from the source stay unknown.
export function normalizeXhsCount(value, zeroLabels = []) {
    if (value?.__v_isRef === true) value = value.value;
    if (typeof value !== 'string' && typeof value !== 'number') return null;
    if (typeof value === 'number' && (!Number.isSafeInteger(value) || value < 0)) return null;
    const text = String(value).replace(/\s+/g, '').trim();
    if (zeroLabels.includes(text)) return '0';
    if (/^(?:\d+|\d{1,3}(?:[,，]\d{3})+)(?:(?:\.\d+)?[wWkKmM万千亿])?\+?$/.test(text)) {
        return text;
    }
    return null;
}

export function extractXhsMetrics(info = {}) {
    return {
        likes: normalizeXhsCount(info.likedCount ?? info.liked_count),
        collects: normalizeXhsCount(info.collectedCount ?? info.collected_count),
        comments: normalizeXhsCount(info.commentCount ?? info.comment_count),
        shares: normalizeXhsCount(info.shareCount ?? info.share_count),
    };
}

export function readXhsCardCount(card) {
    // The same card control displays saves/replies under those active sorts.
    // Its type is assigned by the verified search filter, never by ".count".
    const specific = card.querySelector('.like-wrapper .count, .like-count');
    const generic = specific ? [] : [...card.querySelectorAll('.count')];
    return normalizeXhsCount((specific || (generic.length === 1 ? generic[0] : null))?.textContent, ['赞', '点赞', '收藏', '评论']);
}

export function mapXhsSearchMetrics(count, sort) {
    const metrics = { likes: null, collects: null, comments: null, shares: null };
    const field = sort === 'most-collected' ? 'collects' : sort === 'most-commented' ? 'comments' : 'likes';
    metrics[field] = normalizeXhsCount(count);
    return metrics;
}

export function readXhsNoteMetrics(noteId, scope, states) {
    const values = { likes: null, collects: null, comments: null, shares: null };
    const sources = {};
    for (const state of states) {
        const entry = state?.noteDetailMap?.[noteId];
        const note = entry?.note;
        // Do not use the first map entry or a recommendation's interaction data.
        if (!noteId || String(note?.noteId ?? note?.note_id ?? '') !== noteId) continue;
        const metrics = extractXhsMetrics(note.interactInfo ?? note.interact_info ?? {});
        for (const key of Object.keys(values)) {
            if (values[key] === null && metrics[key] !== null) {
                values[key] = metrics[key];
                sources[key] = 'note_state';
            }
        }
    }
    const selectors = {
        likes: ['.like-wrapper .count', ['赞', '点赞']],
        collects: ['.collect-wrapper .count', ['收藏']],
        comments: ['.chat-wrapper .count', ['评论']],
        shares: ['.share-wrapper .count', []],
    };
    const bar = scope?.querySelector('.interact-container');
    for (const [key, [selector, labels]] of Object.entries(selectors)) {
        const text = bar?.querySelector(selector)?.textContent;
        const count = normalizeXhsCount(text, labels);
        if (values[key] === null && count !== null) {
            values[key] = count;
            sources[key] = 'note_dom';
        }
    }
    return { ...values, metric_sources: sources };
}

export const XHS_ENGAGEMENT_SOURCE = [
    normalizeXhsCount, extractXhsMetrics, readXhsCardCount, readXhsNoteMetrics,
].map(fn => fn.toString()).join('\n');
