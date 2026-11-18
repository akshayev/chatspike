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

    // 1) Try the "Choose clips" list for a few minutes. If Content Rewards' YouTube
    //    lookup is down (status "unavailable", e.g. reason "quota"), paste the link instead.
    let found = false, unavailable = false;
    for (let i = 0; i < 8 && !found; i++) {
      const res = await page.evaluate(async (cid) => {
        const r = await fetch(`/api/submission/submissions/candidate-videos?campaignId=${cid}`);
        return await r.text();
      }, item.campaign_id);
      found = res.includes(item.video_id);
      unavailable = /"status":"unavailable"/.test(res);
      if (found || unavailable) break;
      await page.waitForTimeout(30000);
    }

    // 2) Open the submit sheet
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    await page.locator('button:visible', { hasText: 'Submit clip' }).first().click();
    await page.waitForTimeout(3000);

    let method;
    if (found) {
      method = 'list';
      const tile = page.locator(`img[src*="${item.video_id}"]`).first();
      if (await tile.count()) await tile.click();
      else await page.getByText(item.title.slice(0, 30), { exact: false }).first().click({ timeout: 15000 });
    } else {
      method = 'link';
      const box = page.getByPlaceholder(/paste a link/i).first();
      await box.waitFor({ timeout: 20000 });
      await box.fill(item.url);
      await page.waitForTimeout(2500);   // lets the form validate the link
      const early = await page.evaluate(() => document.body.innerText);
      if (/already submitted to this campaign/i.test(early)) {
        await shot(page, 1);
        console.log(JSON.stringify({ ok: true, method, already: true, campaign: item.campaign_id, video: item.video_id }));
        return;
      }
    }
    await shot(page, 1);

    // 3) Accept requirements and submit
    await page.getByText("I've read the requirements", { exact: false }).click();
    await page.waitForTimeout(500);
    const submit = page.locator('button:visible', { hasText: /^Submit clip/ }).last();
    await submit.click();
    await page.waitForTimeout(5000);
    await shot(page, 2);
    const bodyText = await page.evaluate(() => document.body.innerText);
    if (/already submitted to this campaign/i.test(bodyText)) {
      console.log(JSON.stringify({ ok: true, method, already: true, campaign: item.campaign_id, video: item.video_id }));
      return;
    }
    if (/error|invalid|already submitted|not allowed/i.test(bodyText.slice(0, 3000)) && /submit clip/i.test(bodyText)) {
      throw new Error('Content Rewards showed an error after submit; see shots/cr-' + item.id + '-2.png');
    }
    console.log(JSON.stringify({ ok: true, method, campaign: item.campaign_id, video: item.video_id }));
  } catch (e) {
    await shot(page, 'error');
    console.log(JSON.stringify({ ok: false, error: e.message }));
    process.exitCode = 1;
  } finally {
    await page.close().catch(() => {});
    await browser.close().catch(() => {});
  }
})();
