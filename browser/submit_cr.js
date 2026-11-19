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
    const sheet = page.locator('.clip-picker-root').first();
    await sheet.waitFor({ timeout: 20000 });
    if (found) {
      method = 'list';
      // Tiles are toggle buttons and the newest one is often PRE-selected: only click if not selected.
      let tile = sheet.locator('button', { has: page.locator(`img[src*="${item.video_id}"]`) }).first();
      if (!(await tile.count())) tile = sheet.locator('button', { hasText: item.title.slice(0, 25) }).first();
      const sel = async () => ['true'].includes(await tile.getAttribute('aria-pressed')) ||
                              ['true'].includes(await tile.getAttribute('aria-checked')) ||
                              ['true'].includes(await tile.getAttribute('aria-selected'));
      if (!(await sel())) await tile.click();
      await page.waitForTimeout(500);
      if (!(await sel())) throw new Error('could not select the clip tile');
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

    // 3) Accept requirements: a hidden checkbox inside a label - set it and verify
    const req = sheet.locator('label', { hasText: "I've read the requirements" }).locator('input[type=checkbox]');
    await req.check({ force: true });
    if (!(await req.isChecked())) throw new Error('requirements checkbox did not tick');
    await shot(page, 1);

    // 4) Submit and confirm the sheet closes (or CR says it is already in)
    await sheet.locator('button', { hasText: /^Submit clip/ }).last().click();
    let done = false, already = false;
    for (let i = 0; i < 20 && !done; i++) {
      await page.waitForTimeout(500);
      const txt = await page.evaluate(() => document.body.innerText);
      already = /already submitted to this campaign/i.test(txt);
      done = already || !(await page.locator('.clip-picker-root').count());
    }
    await shot(page, 2);
    if (!done) throw new Error('submit sheet stayed open; see shots/cr-' + item.id + '-2.png');
    console.log(JSON.stringify({ ok: true, method, already, campaign: item.campaign_id, video: item.video_id }));
  } catch (e) {
    await shot(page, 'error');
    console.log(JSON.stringify({ ok: false, error: e.message }));
    process.exitCode = 1;
  } finally {
    await page.close().catch(() => {});
    await browser.close().catch(() => {});
  }
})();
