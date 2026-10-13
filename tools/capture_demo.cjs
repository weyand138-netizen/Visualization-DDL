// Optional screenshot generation: install Playwright separately and start
// tests/visual_qa_server.py with a private control file first. No production URL.
const { chromium } = require('playwright');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.DDL_BROWSER_CHANNEL ? { channel: process.env.DDL_BROWSER_CHANNEL } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:18763');
    await page.waitForFunction(() => document.querySelector('#month-label').textContent.trim().length > 0);
    if (await page.locator('[data-action="ai"]').isVisible()) throw new Error('AI must be hidden without a bridge');
    async function theme(value) {
      if (await page.locator('html').getAttribute('data-theme') !== value) {
        await page.locator('[data-action="theme-toggle"]').click();
        await page.locator('#toast.visible').waitFor({ state: 'visible' });
        await page.locator('#toast.visible').waitFor({ state: 'hidden' });
      }
      await page.waitForFunction(expected => document.documentElement.dataset.theme === expected, value);
    }
    await theme('light');
    await page.screenshot({ path: path.join(__dirname, '../docs/images/dashboard-light.png'), fullPage: true, animations: 'disabled' });
    await theme('dark');
    await page.screenshot({ path: path.join(__dirname, '../docs/images/dashboard-dark.png'), fullPage: true, animations: 'disabled' });
    if (errors.length) throw new Error(errors.join('\n'));
    console.log('Synthetic screenshots captured; no page errors; AI entry hidden.');
  } finally {
    await browser.close();
  }
})();
