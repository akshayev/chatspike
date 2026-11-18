// Opens a headed Chromium with a persistent profile so logins survive restarts.
// Also exposes CDP on 127.0.0.1:9222 so automation scripts can attach.
const { chromium } = require('playwright');
const os = require('os'), path = require('path');
(async () => {
  const ctx = await chromium.launchPersistentContext(path.join(os.homedir(), '.clipper-browser'), {
    headless: false,
    viewport: null,
    ignoreDefaultArgs: ['--enable-automation'],
    args: ['--remote-debugging-port=9222', '--start-maximized', '--disable-blink-features=AutomationControlled'],
  });
  const page = ctx.pages()[0] || await ctx.newPage();
  await page.goto(process.argv[2] || 'https://contentrewards.com');
  console.log('Browser open. Close the window to exit.');
  ctx.on('close', () => process.exit(0));
})();
