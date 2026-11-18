// Uploads one queued clip to YouTube via YouTube Studio in the clipper browser
// (started by open-browser.js, logged in to the @strange-cutx channel).
// Usage: node browser/upload_youtube.js queue/<id>.json
// Prints one JSON line: {"videoId": "...", "url": "https://youtube.com/shorts/..."}
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const item = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const cfg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'config.json'), 'utf8'));
const shot = (p, n) => p.screenshot({ path: path.join(__dirname, '..', 'shots', `yt-${item.id}-${n}.png`) }).catch(() => {});

async function setText(page, sel, text) {
  const box = page.locator(sel).first();
  await box.waitFor({ timeout: 60000 });
  await box.click();
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Backspace');
  await box.fill(text).catch(async () => { await page.keyboard.insertText(text); });
}

(async () => {
  const browser = await chromium.connectOverCDP(cfg.publish.cdp_url);
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  try {
    await page.goto('https://www.youtube.com/upload', { waitUntil: 'domcontentloaded' });
    if (page.url().includes('accounts.google.com')) throw new Error('Not logged in to YouTube in the clipper browser');
    const input = page.locator('input[type="file"]').first();
    await input.waitFor({ state: 'attached', timeout: 60000 });
    await input.setInputFiles(item.file);

    // Details
    await setText(page, '#title-textarea #textbox', item.title.slice(0, 100));
    await setText(page, '#description-textarea #textbox', item.description.slice(0, 4900));
    await page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]').click({ timeout: 30000 });
    await shot(page, 1);

    // Details -> Video elements -> Checks -> Visibility
    for (let i = 0; i < 3; i++) {
      await page.locator('#next-button').click({ timeout: 30000 });
      await page.waitForTimeout(1500);
    }
    await page.locator(`tp-yt-paper-radio-button[name="${cfg.publish.visibility || 'PUBLIC'}"]`).click({ timeout: 30000 });

    // Grab the link Studio shows for the new video
    let url = '';
    for (let i = 0; i < 60 && !url; i++) {
      url = await page.evaluate(() => {
        const a = document.querySelector('ytcp-video-info a[href*="youtu"], .video-url-fadeable a');
        return a ? a.href : '';
      });
      if (!url) await page.waitForTimeout(1000);
    }
    if (!url) throw new Error('Could not read video link from Studio');
    const videoId = (url.match(/(?:shorts\/|youtu\.be\/|v=)([\w-]{11})/) || [])[1];
    await shot(page, 2);

    // Wait for upload to finish before Done (Done is enabled while uploading, but safer to wait)
    for (let i = 0; i < 600; i++) {
      const txt = await page.locator('ytcp-video-upload-progress, .progress-label').first().innerText().catch(() => '');
      if (!/uploading|uploaded \d+%|\d+%/i.test(txt)) break;
      await page.waitForTimeout(1000);
    }
    await page.locator('#done-button').click({ timeout: 60000 });
    await page.waitForTimeout(4000);
    const close = page.locator('ytcp-uploads-still-processing-dialog #close-button, #close-button:visible').first();
    await close.click({ timeout: 8000 }).catch(() => {});
    await shot(page, 3);
    console.log(JSON.stringify({ videoId, url: `https://youtube.com/shorts/${videoId}` }));
  } catch (e) {
    await shot(page, 'error');
    console.error('UPLOAD ERROR', e.message);
    process.exitCode = 1;
  } finally {
    await page.close().catch(() => {});
    await browser.close().catch(() => {}); // disconnects only; the browser keeps running
  }
})();
