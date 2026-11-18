// Usage: node look.js [url] -> navigates first tab (optional), saves screenshot, prints text + buttons/links
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const ctx = b.contexts()[0];
  for (const p of ctx.pages()) console.log('TAB', p.url());
  const page = ctx.pages().find(p => p.url().includes('contentrewards')) || ctx.pages()[0];
  if (process.argv[2]) { await page.goto(process.argv[2]); await page.waitForTimeout(4000); }
  await page.screenshot({ path: 'shots/last.png' });
  console.log('URL', page.url());
  const t = await page.evaluate(() => document.body.innerText);
  console.log(t.slice(0, 3000));
  const ctrls = await page.$$eval('button, a', els => els.map(e => (e.tagName + ':' + e.innerText.trim().replace(/\s+/g,' ').slice(0,60) + (e.href ? ' -> ' + e.href : ''))).filter(s => s.length > 3));
  console.log('CONTROLS', [...new Set(ctrls)].join('\n'));
  await b.close();
})();
