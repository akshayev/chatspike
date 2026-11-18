// Submits an uploaded clip to its Content Rewards campaign using the clipper
// browser's logged-in session. Content Rewards lists your recent YouTube uploads
// under "Submit clip" -> "Choose clips"; we wait for ours to appear, tick it,
// accept the requirements box and submit.
// Usage: node browser/submit_cr.js queue/<id>.json   -> prints {"ok":true,...}
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const item = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const cfg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'config.json'), 'utf8'));
const CAMPAIGN = `https://contentrewards.com/c/campaigns/${item.campaign_id}`;
const shot = (p, n) => p.screenshot({ path: path.join(__dirname, '..', 'shots', `cr-${item.id}-${n}.png`) }).catch(() => {});

(async () => {
  const browser = await chromium.connectOverCDP(cfg.publish.cdp_url);
  const page = await browser.contexts()[0].newPage();
  try {
    await page.goto(CAMPAIGN, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);

    // 1) Wait until Content Rewards has picked up the new upload (up to ~25 min)
    let found = false;
    for (let i = 0; i < 50 && !found; i++) {
      const res = await page.evaluate(async (cid) => {
        const r = await fetch(`/api/submission/submissions/candidate-videos?campaignId=${cid}&refresh=1`);
        return await r.text();
      }, item.campaign_id);
      found = res.includes(item.video_id);
      if (!found) await page.waitForTimeout(30000);
    }
    if (!found) throw new Error('Upload never appeared in Content Rewards candidate list');

    // 2) Open the submit sheet and pick our clip
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    await page.locator('button:visible', { hasText: 'Submit clip' }).first().click();
    await page.getByText('Choose clips').waitFor({ timeout: 30000 });
    await page.waitForTimeout(3000);
    const tile = page.locator(`img[src*="${item.video_id}"]`).first();
    if (await tile.count()) {
      await tile.click();
    } else {
      const byTitle = page.getByText(item.title.slice(0, 30), { exact: false }).first();
      await byTitle.click({ timeout: 15000 });
    }
    await shot(page, 1);

    // 3) Accept requirements and submit
    await page.getByText("I've read the requirements", { exact: false }).click();
    await page.waitForTimeout(500);
    const submit = page.locator('button:visible', { hasText: /^Submit clip/ }).last();
    await submit.click();
    await page.waitForTimeout(5000);
    await shot(page, 2);
    console.log(JSON.stringify({ ok: true, campaign: item.campaign_id, video: item.video_id }));
  } catch (e) {
    await shot(page, 'error');
    console.log(JSON.stringify({ ok: false, error: e.message }));
    process.exitCode = 1;
  } finally {
    await page.close().catch(() => {});
    await browser.close().catch(() => {});
  }
})();
