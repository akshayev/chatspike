// Usage: node attach.js  -> prints open tabs of the running clipper browser
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:9222');
  for (const p of b.contexts()[0].pages()) console.log(p.url(), '|', await p.title());
  await b.close();
})();
