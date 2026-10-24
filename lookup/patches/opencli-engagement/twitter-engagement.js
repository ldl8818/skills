// Local OpenCLI 2.0.2 adapter support. Read only the supplied post's counters.
export function extractTwitterMetrics(tweet, { stringViews = false } = {}) {
    const count = value => {
        if (typeof value !== 'number' && typeof value !== 'string') return null;
        if (typeof value === 'string' && !/^\d+$/.test(value)) return null;
        const number = Number(value);
        return Number.isSafeInteger(number) && number >= 0 ? number : null;
    };
    const legacy = tweet?.legacy ?? {};
    const views = count(tweet?.views?.count);
    return {
        likes: count(legacy.favorite_count),
        retweets: count(legacy.retweet_count),
        replies: count(legacy.reply_count),
        quotes: count(legacy.quote_count),
        bookmarks: count(legacy.bookmark_count),
        views: views === null ? null : stringViews ? String(views) : views,
        // X does not expose a separate total for the share-menu action.
        shares: null,
    };
}
