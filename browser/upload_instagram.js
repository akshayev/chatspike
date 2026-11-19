// Posts one clip as an Instagram Reel through instagram.com in the clipper browser
// (logged in to the clips account). Saves a screenshot after every step.
// Usage: node browser/upload_instagram.js queue/<id>.json [--dry]
//   --dry  goes through every step but stops before "Share" (nothing is posted)
// Prints one JSON line: {"videoId": "<shortcode>", "url": "https://www.instagram.com/reel/<shortcode>/"}
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const item = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const DRY = process.argv.includes('--dry');
const cfg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'config.json'), 'utf8'));
let step = 0;
const shot = (p, n) => p.screenshot({ path: path.join(__dirname, '..', 'shots', `ig-${item.id}-${++step}-${n}.png`) }).catch(() => {});

async function clickText(page, re, timeout = 15000) {
  const loc = page.getByRole('button', { name: re }).or(page.getByText(re)).first();
  await loc.waitFor({ state: 'visible', timeout });
  await loc.click();
}

(async () => {
  const browser = await chromium.connectOverCDP(cfg.publish.cdp_url);
  const page = await browser.contexts()[0].newPage();
  try {
    await page.goto('https://www.instagram.com/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(4000);
    if (/accounts\/login/.test(page.url()) || await page.locator('input[name="username"]').count()) {
      throw new Error('Not logged in to Instagram in the clipper browser');
    }
    // dismiss "Turn on notifications" / "Save login info" prompts
    for (const re of [/^Not now$/i, /^Not Now$/]) {
      await page.getByRole('button', { name: re }).first().click({ timeout: 2500 }).catch(() => {});
    }
    const me = await page.evaluate(() => {
      const a = [...document.querySelectorAll('a[href^="/"]')].find(x => /profile/i.test(x.innerText) || x.querySelector('img[alt*="profile picture"]'));
      return a ? a.getAttribute('href').replace(/\//g, '') : '';
    });
    await shot(page, 'home');

    // 1) Create -> Post
    await page.locator('svg[aria-label="New post"], svg[aria-label="Create"]').first().click({ timeout: 15000 });
    await page.waitForTimeout(1500);
    await page.getByText(/^Post$/).first().click({ timeout: 4000 }).catch(() => {});
    await page.waitForTimeout(1500);

    // 2) Select the video file
    const input = page.locator('input[type="file"][accept*="video"], form[enctype] input[type="file"], input[type="file"]').first();
    await input.waitFor({ state: 'attached', timeout: 20000 });
    await input.setInputFiles(item.file);
    await page.waitForTimeout(4000);
    await page.getByRole('button', { name: /^OK$/ }).click({ timeout: 4000 }).catch(() => {});   // "Video posts are now shared as reels"
    await shot(page, 'selected');

    // 3) Crop: keep the original 9:16
    const crop = page.locator('svg[aria-label="Select crop"], svg[aria-label="Select Crop"]').first();
    if (await crop.count()) {
      await crop.click().catch(() => {});
      await page.waitForTimeout(800);
      await page.getByText(/^Original$/).first().click({ timeout: 3000 }).catch(() => {});
    }
    await shot(page, 'crop');
    await clickText(page, /^Next$/);
    await page.waitForTimeout(2500);

    // 4) Edit: optional custom cover from the clip's peak frame
    if (item.cover && fs.existsSync(item.cover)) {
      const coverInput = page.locator('input[type="file"][accept*="image"]').first();
      if (await coverInput.count()) {
        await coverInput.setInputFiles(item.cover).catch(() => {});
        await page.waitForTimeout(2500);
      }
    }
    await shot(page, 'edit');
    await clickText(page, /^Next$/);
    await page.waitForTimeout(2500);

    // 5) Caption
    const caption = `${item.title}\n\n${item.description}`.slice(0, 2150);
    const box = page.locator('div[aria-label="Write a caption..."], div[contenteditable="true"][role="textbox"]').first();
    await box.waitFor({ timeout: 20000 });
    await box.click();
    await page.keyboard.insertText(caption);
    await page.waitForTimeout(1000);
    await shot(page, 'caption');

    if (DRY) {
      console.log(JSON.stringify({ dry: true, ok: true, account: me, note: 'stopped before Share' }));
      await page.keyboard.press('Escape').catch(() => {});
      await page.getByRole('button', { name: /^Discard$/ }).click({ timeout: 3000 }).catch(() => {});
      return;
    }

    // 6) Share and wait for confirmation
    await page.getByRole('button', { name: /^Share$/ }).or(page.getByText(/^Share$/)).first().click({ timeout: 15000 });
    await page.getByText(/(reel|post) has been shared|Your reel has been shared/i).first().waitFor({ timeout: 300000 });
    await shot(page, 'shared');
    await page.keyboard.press('Escape').catch(() => {});

    // 7) Find the new reel's link on the profile (newest first)
    let code = '';
    if (me) {
      for (let i = 0; i < 6 && !code; i++) {
        await page.goto(`https://www.instagram.com/${me}/reels/`, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(4000);
        code = await page.evaluate(() => {
          const a = document.querySelector('a[href*="/reel/"]');
          return a ? (a.getAttribute('href').match(/\/reel\/([\w-]+)/) || [])[1] || '' : '';
        });
        if (!code) await page.waitForTimeout(10000);
      }
    }
    await shot(page, 'profile');
    if (!code) throw new Error('Shared, but could not read the reel link from the profile');
    console.log(JSON.stringify({ videoId: code, url: `https://www.instagram.com/reel/${code}/`, account: me }));
  } catch (e) {
    await shot(page, 'error');
    console.log(JSON.stringify({ ok: false, error: e.message }));
    process.exitCode = 1;
  } finally {
    await page.close().catch(() => {});
    await browser.close().catch(() => {});
  }
})();
