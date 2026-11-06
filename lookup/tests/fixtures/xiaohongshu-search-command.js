// SPDX-License-Identifier: Apache-2.0
// OpenCLI v2.0.2, clis/xiaohongshu/search.js: command.
// https://github.com/jackwener/opencli/blob/v2.0.2/clis/xiaohongshu/search.js
export const command = cli({
    site: 'xiaohongshu',
    name: 'search',
    access: 'read',
    description: '搜索小红书笔记',
    domain: 'www.xiaohongshu.com',
    strategy: Strategy.COOKIE,
    navigateBefore: false,
    args: [
        { name: 'query', required: true, positional: true, help: 'Search keyword' },
        { name: 'limit', type: 'int', default: 20, help: 'Number of results' },
        { name: 'sort', type: 'string', default: 'comprehensive', choices: ['comprehensive', 'latest', 'most-liked', 'most-commented', 'most-collected'], help: 'Sort order' },
        { name: 'note-type', type: 'string', default: 'all', choices: ['all', 'video', 'image'], help: 'Note type' },
        { name: 'publish-time', type: 'string', default: 'anytime', choices: ['anytime', 'day', 'week', 'half-year'], help: 'Publish time range' },
        { name: 'scope', type: 'string', default: 'all', choices: ['all', 'seen', 'unseen', 'following'], help: 'Search scope' },
        { name: 'location', type: 'string', default: 'all', choices: ['all', 'same-city', 'nearby'], help: 'Location distance' },
    ],
    columns: ['rank', 'title', 'author', 'likes', 'published_at', 'url'],
    func: async (page, kwargs) => {
        try {
            const limit = parseLimit(kwargs.limit);
            const requestedFilters = resolveSearchFilters(kwargs);
            await openSearchResults(page, kwargs.query);
            let harvest = await collectSearchHarvest(page, limit, requestedFilters);
            if (isCollapsedRender(harvest.diag)) {
                await replaceCollapsedTab(page, EXPLORE_URL);
                await openSearchResults(page, kwargs.query);
                harvest = await collectSearchHarvest(page, limit, requestedFilters);
                if (isCollapsedRender(harvest.diag)) {
                    throw new CommandExecutionError(
                        'Xiaohongshu search masonry remained collapsed after one fresh-tab recovery.',
                        'Retry later or use a different logged-in browser session.',
                    );
                }
            }
            const rows = harvest.rows
                .filter((item) => item.title)
                .slice(0, limit);
            if (rows.length === 0) {
                throw new EmptyResultError('xiaohongshu search', 'No usable notes were rendered for this query.');
            }
            return rows
                .map((item, i) => ({
                rank: i + 1,
                ...item,
                published_at: noteIdToDate(item.url),
            }));
        }
        catch (err) {
            if (err instanceof CliError)
                throw err;
            throw new CommandExecutionError(`Xiaohongshu search failed: ${err?.message ?? String(err)}`);
        }
    },
});
