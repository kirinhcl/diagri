'use strict';
// DiAGRI demo recorder (Discover -> Rehearse -> Record; see README.md in this folder).
//   node demo.cjs rehearse   operator steps against a seeded instance; checks every selector
//   node demo.cjs record     the real run: model roles on, fast-forwarded stage, full video
// Writes $DEMO_OUT/<mode>/raw.mp4 and timeline.json (time-lapse segments, chapters) for edit.py.
// Environment: GROWBRIDGE_DEV_SECRET (required), FFMPEG (required, an ffmpeg with libx264),
// DEMO_OUT (default: <system temp>/diagri-demo), PW_PATH (default: the `playwright` package).
const os = require('os');
const path = require('path');
const fs = require('fs');
const { chromium } = require(process.env.PW_PATH || 'playwright');

const MODE = process.argv[2] === 'record' ? 'record' : 'rehearse';
const RECORD = MODE === 'record';
const BASE = 'http://localhost:8770';
const WB = `${BASE}/workbench`;
const OUT = path.join(process.env.DEMO_OUT || path.join(os.tmpdir(), 'diagri-demo'), MODE);
const SECRET = process.env.GROWBRIDGE_DEV_SECRET || '';
if (SECRET.length < 12) throw new Error('GROWBRIDGE_DEV_SECRET must hold the dev operator’s secret');
const VIEWPORT = { width: 1440, height: 810 };
const SCALE = 4 / 3; // 1440x810 CSS px -> 1920x1080 video
const VIDEO = { width: 1920, height: 1080 };
const MINUTE = 60_000;
const POLL_MS = 2000;
const STABLE_MS = 10_000;
const TIMEOUT = { reply: 8 * MINUTE, planner: 25 * MINUTE, stage: 25 * MINUTE, analysis: 35 * MINUTE };
const BUSY = new Set(['in_progress', 'remote_queued', 'computing', 'fetching', 'reconcile']);
const REHEARSAL_STAGE = 'stage-dev';

const PROJECT_NAME = RECORD ? 'Lettuce light response' : `Rehearsal ${Date.now() % 100000}`;
const QUESTION = 'Does raising the grow light from 40 % to 70 % speed up lettuce canopy growth?';
const HYPOTHESIS = 'Canopy area grows at least 15 % faster under 70 % light than under 40 % light.';
const ASK_PLAN = `${QUESTION} Please design the run sheet for round 1.`;
const ASK_REPORT = 'The stage of round 1 has ended and the daily canopy measurements are recorded. '
  + 'Please verify the data, freeze the dataset and write the report for round 1.';

let t0 = 0;
const timeline = { mode: MODE, marks: [], chapters: [] };
const clock = () => (Date.now() - t0) / 1000;
const log = (...args) => console.log(`[${clock().toFixed(1).padStart(7)}s]`, ...args);

// --- overlay, injected into every document ----------------------------------------------------
// Arrow cursor with click ripples, subtitle bar, time-lapse badge and full-screen chapter cards.
// Cursor and subtitle are manual popovers, so raise() can lift them above a modal <dialog>.
function overlayInit() {
  const CSS = `
    #demo-cursor, #demo-sub { position: fixed; margin: 0; border: 0; overflow: visible; inset: auto; }
    #demo-cursor { left: 0; top: 0; width: 26px; height: 26px; padding: 0; background: transparent;
      pointer-events: none; transition: transform 50ms linear; filter: drop-shadow(0 2px 3px rgba(0,0,0,.35)); }
    .demo-ripple { position: fixed; width: 34px; height: 34px; margin: -17px 0 0 -17px; border-radius: 50%;
      border: 3px solid #23684d; pointer-events: none; z-index: 2147483646; animation: demo-ripple .6s ease-out forwards; }
    @keyframes demo-ripple { from { transform: scale(.3); opacity: .95 } to { transform: scale(1.6); opacity: 0 } }
    #demo-sub { left: 50%; bottom: 24px; transform: translateX(-50%); max-width: 80vw; padding: 11px 24px;
      border-radius: 14px; background: rgba(23, 46, 40, .93); color: #fff; text-align: center;
      font: 600 17px/1.45 Inter, -apple-system, "Segoe UI", sans-serif; letter-spacing: .1px;
      pointer-events: none; opacity: 0; transition: opacity .35s; box-shadow: 0 10px 30px rgba(0,0,0,.25); }
    #demo-sub.on { opacity: 1; }
    #demo-badge { position: fixed; top: 16px; left: 50%; transform: translateX(-50%); z-index: 2147483645;
      padding: 8px 16px; border-radius: 999px; background: #9a6a00; color: #fff; pointer-events: none;
      font: 700 13px/1.2 Inter, -apple-system, sans-serif; letter-spacing: .4px; opacity: 0; transition: opacity .3s;
      box-shadow: 0 6px 18px rgba(0,0,0,.2); }
    #demo-badge.on { opacity: 1; }
    #demo-card { position: fixed; inset: 0; z-index: 2147483640; display: flex; flex-direction: column;
      justify-content: center; padding: 0 11vw; color: #f4f1e8; opacity: 0; pointer-events: none; transition: opacity .6s;
      background: radial-gradient(120% 140% at 12% 18%, #2a7657 0%, #174d38 52%, #0e3024 100%);
      font-family: Inter, -apple-system, "Segoe UI", sans-serif; }
    #demo-card.on { opacity: 1; }
    #demo-card .k { font-size: 15px; font-weight: 700; letter-spacing: 2.6px; text-transform: uppercase; color: #a9d8c0; }
    #demo-card h1 { margin: 14px 0 14px; font-size: 62px; line-height: 1.05; font-weight: 800; letter-spacing: -1.4px; }
    #demo-card p { margin: 0; max-width: 860px; font-size: 22px; line-height: 1.5; color: #dfe9e2; }
    #demo-card ul { margin: 26px 0 0; padding: 0; list-style: none; font-size: 21px; line-height: 1.95; color: #e8efe9; }
    #demo-card li::before { content: "→  "; color: #a9d8c0; }
  `;
  const ARROW = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2.5 19.5 12l-7 1.4L9.3 20.5Z" '
    + 'fill="#fff" stroke="#172e28" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  const el = {};
  function raise() {
    for (const node of [el.sub, el.cursor]) {
      if (!node || !node.showPopover) continue;
      if (node.matches(':popover-open')) node.hidePopover();
      node.showPopover();
    }
  }
  function install() {
    if (document.getElementById('demo-cursor')) return;
    const style = document.createElement('style');
    style.textContent = CSS;
    document.head.append(style);
    el.cursor = Object.assign(document.createElement('div'), { id: 'demo-cursor', innerHTML: ARROW });
    el.sub = Object.assign(document.createElement('div'), { id: 'demo-sub' });
    el.badge = Object.assign(document.createElement('div'), { id: 'demo-badge' });
    el.card = Object.assign(document.createElement('div'), { id: 'demo-card' });
    el.cursor.setAttribute('popover', 'manual');
    el.sub.setAttribute('popover', 'manual');
    document.body.append(el.card, el.badge, el.sub, el.cursor);
    raise();
    document.addEventListener('mousemove', (e) => {
      el.cursor.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
    }, true);
    document.addEventListener('mousedown', (e) => {
      const ring = Object.assign(document.createElement('div'), { className: 'demo-ripple' });
      ring.style.left = `${e.clientX}px`;
      ring.style.top = `${e.clientY}px`;
      (document.querySelector('dialog[open]') || document.body).append(ring);
      setTimeout(() => ring.remove(), 700);
    }, true);
  }
  window.__demo = {
    raise,
    sub(text) { el.sub.textContent = text || ''; el.sub.classList.toggle('on', Boolean(text)); },
    badge(text) { el.badge.textContent = text || ''; el.badge.classList.toggle('on', Boolean(text)); },
    card(kicker, title, text, items) {
      el.card.replaceChildren();
      const add = (tag, cls, value) => {
        const node = document.createElement(tag);
        if (cls) node.className = cls;
        node.textContent = value;
        el.card.append(node);
      };
      add('div', 'k', kicker);
      add('h1', '', title);
      if (text) add('p', '', text);
      if (items && items.length) {
        const list = document.createElement('ul');
        for (const item of items) list.append(Object.assign(document.createElement('li'), { textContent: item }));
        el.card.append(list);
      }
      el.card.classList.add('on');
    },
    hideCard() { el.card.classList.remove('on'); },
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
}

// --- small helpers ------------------------------------------------------------------------------
const pause = (page, ms) => page.waitForTimeout(ms);
const overlay = (page, method, ...args) =>
  page.evaluate(([m, a]) => window.__demo && window.__demo[m](...a), [method, args]);

async function sub(page, text, holdMs = 1800) {
  await overlay(page, 'sub', text);
  if (text) await pause(page, holdMs);
}

async function chapter(page, kicker, title, text, items = null, holdMs = 3800) {
  timeline.chapters.push({ t: clock(), title: `${kicker}: ${title}` });
  log('chapter', title);
  await overlay(page, 'sub', '');
  await overlay(page, 'card', kicker, title, text, items);
  await pause(page, holdMs);
  await overlay(page, 'hideCard');
  await pause(page, 800);
}

async function lapseStart(page, label, targetSeconds) {
  await overlay(page, 'badge', `⏩  TIME-LAPSE · ${label}`);
  const mark = { type: 'speed', label, start: clock(), target: targetSeconds };
  timeline.marks.push(mark);
  log('time-lapse start:', label);
  return mark;
}

async function lapseEnd(page, mark) {
  mark.end = clock();
  await overlay(page, 'badge', '');
  log(`time-lapse end: ${mark.label} (${(mark.end - mark.start).toFixed(0)} s real)`);
}

const section = (page, title) => page.locator('h2')
  .filter({ hasText: new RegExp(`^\\s*${title}\\s*$`) }).first()
  .locator('xpath=ancestor::section[1]');

async function find(page, target, label, timeout = 15_000) {
  const el = typeof target === 'string' ? page.locator(target).first() : target.first();
  try {
    await el.waitFor({ state: 'visible', timeout });
  } catch {
    throw new Error(`not visible: ${label}`);
  }
  return el;
}

// Scrolls only when the element is not comfortably inside the viewport, then glides the cursor.
async function point(page, el) {
  await el.evaluate((node) => {
    const r = node.getBoundingClientRect();
    if (r.top < 80 || r.bottom > window.innerHeight - 110) node.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  await pause(page, 700);
  const box = await el.boundingBox();
  if (!box) throw new Error('element has no box');
  await page.mouse.move(box.x + Math.min(box.width / 2, 160), box.y + Math.min(box.height / 2, 18), { steps: 24 });
  await pause(page, 300);
}

async function click(page, target, label, afterMs = 1000) {
  const el = await find(page, target, label);
  await point(page, el);
  await el.click();
  log('click', label);
  await pause(page, afterMs);
  return el;
}

async function typeInto(page, target, text, label, delay = 30) {
  const el = await click(page, target, label, 250);
  await el.fill('');
  await el.pressSequentially(text, { delay });
  await pause(page, 500);
  return el;
}

async function choose(page, target, value, label) {
  const el = await find(page, target, label);
  await point(page, el);
  await el.selectOption(value);
  log('select', label, value);
  await pause(page, 700);
}

// One step of reading: scroll the element's nearest scroll box (the window, or the chat log)
// so the element's top shows first, then down until its bottom clears the subtitle bar.
function readStep(node, { step, first }) {
  let box = null;
  for (let p = node.parentElement; p; p = p.parentElement) {
    const style = getComputedStyle(p);
    if (/(auto|scroll)/.test(style.overflowY) && p.scrollHeight > p.clientHeight + 4) { box = p; break; }
  }
  const view = box ? box.getBoundingClientRect() : { top: 70, bottom: window.innerHeight };
  const limit = Math.min(view.bottom, window.innerHeight - 110);
  const r = node.getBoundingClientRect();
  const scroller = box || window;
  if (first) {
    if (box) {
      const outer = box.getBoundingClientRect();
      if (outer.top < 70 || outer.bottom > window.innerHeight - 40) window.scrollBy({ top: outer.top - 90, behavior: 'smooth' });
    }
    scroller.scrollBy({ top: r.top - view.top - 14, behavior: 'smooth' });
    return true;
  }
  const remaining = r.bottom - limit;
  if (remaining <= 4) return false;
  scroller.scrollBy({ top: Math.min(step, remaining + 16), behavior: 'smooth' });
  return true;
}

async function readThrough(page, target, { step = 220, ms = 1500, maxSteps = 14 } = {}) {
  const el = typeof target === 'string' ? page.locator(target).first() : target;
  await el.evaluate(readStep, { step, first: true });
  await pause(page, 1400);
  for (let i = 0; i < maxSteps; i += 1) {
    const moved = await el.evaluate(readStep, { step, first: false });
    if (!moved) break;
    await pause(page, ms);
  }
}

async function followChat(page) {
  await page.evaluate(() => {
    const chatLog = document.querySelector('.chat-log');
    if (!chatLog) return;
    chatLog.scrollTo({ top: chatLog.scrollHeight, behavior: 'smooth' });
    const r = chatLog.getBoundingClientRect();
    if (r.top < 70) window.scrollBy({ top: r.top - 90, behavior: 'smooth' });
    else if (r.bottom > window.innerHeight - 100) window.scrollBy({ top: r.bottom - window.innerHeight + 110, behavior: 'smooth' });
  });
}

async function readLatestReply(page, opts = {}) {
  const replies = page.locator('li.chat-entry.chat-agent');
  if (!(await replies.count())) return;
  await readThrough(page, replies.last(), { step: 200, ms: 1700, maxSteps: 20, ...opts });
}

// A yes/no confirmation and/or the re-authentication prompt may follow a stage action.
async function handleDialogs(page) {
  for (let i = 0; i < 3; i += 1) {
    const dialog = page.locator('dialog[open]');
    try {
      await dialog.waitFor({ state: 'visible', timeout: 2500 });
    } catch {
      return;
    }
    await overlay(page, 'raise');
    const secret = dialog.locator('input[name="secret"]');
    if (await secret.count()) {
      await sub(page, 'Re-authentication: approving needs the operator’s secret again', 900);
      await typeInto(page, secret, SECRET, 'reauth secret', 45);
    } else {
      await pause(page, 2000); // let the viewer read the question
    }
    await click(page, dialog.locator('button[type="submit"]'), 'dialog confirm', 1500);
  }
}

async function api(page, route) {
  const res = await page.request.get(`${BASE}/wb${route}`);
  if (!res.ok()) throw new Error(`GET /wb${route}: ${res.status()} ${(await res.text()).slice(0, 200)}`);
  return res.json();
}

async function waitFor(page, label, check, timeoutMs, tick = null) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    let done = false;
    try {
      done = await check();
    } catch (error) {
      log(`check "${label}" failed: ${error.message}`);
    }
    if (done) {
      log(`ready: ${label}`);
      return;
    }
    if (tick) await tick().catch((error) => log(`tick failed: ${error.message}`));
    await pause(page, POLL_MS);
  }
  throw new Error(`timed out after ${Math.round(timeoutMs / 1000)} s: ${label}`);
}

function stable(predicate) {
  let since = null;
  return async () => {
    if (!(await predicate())) {
      since = null;
      return false;
    }
    since = since ?? Date.now();
    return Date.now() - since >= STABLE_MS;
  };
}

async function agentsIdle(page, projectId) {
  const project = await api(page, `/projects/${projectId}`);
  return !(project.tasks || []).some((task) => BUSY.has(task.state));
}

async function conversationLength(page, projectId) {
  return ((await api(page, `/projects/${projectId}/conversation`)).entries || []).length;
}

async function agentReplied(page, projectId, after) {
  const entries = ((await api(page, `/projects/${projectId}/conversation`)).entries || []).slice(after);
  return entries.some((entry) => entry.role !== 'user' && (entry.kind === 'reply' || entry.kind === 'message'));
}

// Types a message into the project conversation, sends it and checks the server took it.
async function sendChat(page, projectId, roundId, text, label) {
  const chat = section(page, 'Conversation');
  await choose(page, chat.locator('select'), roundId, 'chat round');
  await typeInto(page, chat.locator('textarea'), text, label, 26);
  const before = await conversationLength(page, projectId);
  await click(page, chat.locator('button[type="submit"]'), 'Send', 600);
  await waitFor(page, `${label} accepted`, async () => (await conversationLength(page, projectId)) > before, 15_000);
  return before;
}

async function goHash(page, hash, settleMs = 2000) {
  await page.evaluate((h) => { window.location.hash = h; }, hash);
  await pause(page, settleMs);
}

module.exports = {
  RECORD, WB, SECRET, PROJECT_NAME, QUESTION, HYPOTHESIS, ASK_PLAN, ASK_REPORT, TIMEOUT, REHEARSAL_STAGE,
  log, pause, overlay, sub, chapter, lapseStart, lapseEnd, section, find, point, click, typeInto, choose,
  readThrough, followChat, readLatestReply, handleDialogs, api, waitFor, stable, agentsIdle,
  conversationLength, agentReplied, sendChat, goHash,
};

// --- run ----------------------------------------------------------------------------------------
if (require.main === module) {
  const scenes = require('./scenes.cjs');
  const { startScreencast } = require('./screencast.cjs');
  (async () => {
    if (!process.env.FFMPEG) throw new Error('FFMPEG must point to an ffmpeg build with libx264');
    fs.mkdirSync(OUT, { recursive: true });
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: VIEWPORT, deviceScaleFactor: SCALE, locale: 'en-US', timezoneId: 'UTC',
      bypassCSP: true, // the workbench's style-src 'self' would block the injected overlay styles
    });
    await context.addInitScript(overlayInit);
    const page = await context.newPage();
    const videoFile = path.join(OUT, 'raw.mp4');
    const cast = await startScreencast(page, videoFile, process.env.FFMPEG, VIDEO);
    t0 = cast.start;
    page.on('console', (m) => { if (m.type() === 'error') log('console error:', m.text()); });
    page.on('pageerror', (e) => log('page error:', e.message));
    const state = { stageId: RECORD ? null : REHEARSAL_STAGE };
    let failed = null;
    try {
      await page.goto(`${WB}#/login`);
      await page.waitForSelector('#login-name');
      timeline.marks.push({ type: 'cut', label: 'blank start', start: 0, end: clock() });
      for (const scene of scenes.ORDER) {
        log(`--- scene ${scene.name}`);
        await scene(page, state);
      }
    } catch (error) {
      failed = error;
      log('DEMO ERROR:', error.stack || error.message);
      await page.screenshot({ path: path.join(OUT, 'failure.png') }).catch(() => {});
    } finally {
      timeline.duration = clock();
      timeline.state = state;
      timeline.failed = failed ? failed.message : null;
      fs.writeFileSync(path.join(OUT, 'timeline.json'), JSON.stringify(timeline, null, 2));
      try {
        const { seconds } = await cast.stop();
        log(`video saved: ${videoFile} (${seconds.toFixed(1)} s)`);
      } catch (error) {
        log('VIDEO ERROR:', error.message);
        failed = failed || error;
      }
      await context.close();
      await browser.close();
      process.exitCode = failed ? 1 : 0;
    }
  })();
}
