'use strict';
// Phase 1 (Discover): sign in to the local dev workbench and dump each page's controls.
//   node discover.cjs ['#/route,#/other']   writes $DEMO_OUT/discover/<page>.json and .png
const os = require('os');
const path = require('path');
const fs = require('fs');
const { chromium } = require(process.env.PW_PATH || 'playwright');

const BASE = 'http://localhost:8770/workbench';
const OUT = path.join(process.env.DEMO_OUT || path.join(os.tmpdir(), 'diagri-demo'), 'discover');
const SECRET = process.env.GROWBRIDGE_DEV_SECRET || '';
if (!SECRET) throw new Error('GROWBRIDGE_DEV_SECRET must hold the dev operator’s secret');
const routes = (process.argv[2] || '#/,#/projects,#/environment,#/safety,#/alerts,#/evidence,#/compute').split(',');

async function dump(page, name) {
  await page.waitForTimeout(1200);
  const fields = await page.evaluate(() => Array.from(
    document.querySelectorAll('input, select, textarea, button, a, [contenteditable="true"], h1, h2, h3')
  ).filter((el) => el.offsetParent !== null).map((el) => ({
    tag: el.tagName, type: el.type || '', name: el.name || '', id: el.id || '',
    placeholder: el.placeholder || '', href: el.getAttribute('href') || '',
    text: (el.textContent || '').trim().replace(/\s+/g, ' ').substring(0, 60),
    options: el.tagName === 'SELECT' ? Array.from(el.options).map((o) => `${o.value}=${o.text}`) : undefined,
  })));
  fs.writeFileSync(path.join(OUT, `${name}.json`), JSON.stringify(fields, null, 1));
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  console.log(`${name}: ${fields.length} elements`);
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-US' });
  const page = await context.newPage();
  page.on('console', (m) => { if (m.type() === 'error') console.error('console error:', m.text()); });
  try {
    await page.goto(`${BASE}#/login`);
    await dump(page, 'login');
    await page.fill('#login-name', 'dev');
    await page.fill('#login-secret', SECRET);
    await page.click('button[type="submit"]');
    await page.waitForTimeout(1500);
    for (const r of routes) {
      await page.goto(`${BASE}${r}`);
      await dump(page, r.replace(/[#/]+/g, '_').replace(/^_|_$/g, '') || 'inbox');
    }
  } catch (err) {
    console.error('DISCOVER ERROR:', err.message);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
