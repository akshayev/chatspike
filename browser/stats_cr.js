// Reads your Content Rewards submissions (views, likes, review status) and, for
// pool campaigns, your pool standing - using the clipper browser's logged-in session.
// Usage: node browser/stats_cr.js '["<campaignId>", ...]'   -> prints one JSON line
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const cfg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'config.json'), 'utf8'));
const poolIds = JSON.parse(process.argv[2] || '[]');

(async () => {
  const browser = await chromium.connectOverCDP(cfg.publish.cdp_url);
  const page = await browser.contexts()[0].newPage();
  try {
    await page.goto('https://contentrewards.com/c/discover', { waitUntil: 'domcontentloaded' });
    const out = await page.evaluate(async (poolIds) => {
      const subs = [];
      let cursor = null;
      for (let i = 0; i < 20; i++) {
        const u = '/api/submission/submissions?limit=100' + (cursor ? '&cursor=' + encodeURIComponent(cursor) : '');
        const j = await (await fetch(u)).json();
        if (!j.success) return { error: 'submissions: ' + JSON.stringify(j).slice(0, 300) };
        subs.push(...j.data);
        cursor = j.pagination && j.pagination.nextCursor;
        if (!cursor) break;
      }
      const pools = {};
      for (const id of poolIds) {
        try { pools[id] = (await (await fetch(`/api/submission/pools/${id}/me`)).json()).data; } catch (e) { pools[id] = null; }
      }
      return {
        submissions: subs.map(s => ({
          id: s.id, campaign_id: s.campaignId, campaign: s.campaignName, created: s.createdAt,
          status: s.status, review: s.reviewStatus, flagged: s.flagged, deleted: s.isDeleted,
          platform: s.socialMediaPost && s.socialMediaPost.platform,
          post_id: s.socialMediaPost && s.socialMediaPost.postId,
          url: s.socialMediaPost && s.socialMediaPost.postUrl,
          title: s.socialMediaPost && s.socialMediaPost.title,
          views: Number((s.socialMediaPost && s.socialMediaPost.views) || 0),
          likes: Number((s.socialMediaPost && s.socialMediaPost.likes) || 0),
          comments: Number((s.socialMediaPost && s.socialMediaPost.comments) || 0),
          shares: Number((s.socialMediaPost && s.socialMediaPost.shares) || 0),
        })),
        pools,
      };
    }, poolIds);
    console.log(JSON.stringify(out));
  } catch (e) {
    console.log(JSON.stringify({ error: e.message }));
    process.exitCode = 1;
  } finally {
    await page.close().catch(() => {});
    await browser.close().catch(() => {});
  }
})();
