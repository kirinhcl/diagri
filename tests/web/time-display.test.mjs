import assert from "node:assert/strict";
import test from "node:test";

import { sidebar } from "../../src/growbridge/web/workbench/ui/layout.js";
import { timeCell, timeText } from "../../src/growbridge/web/workbench/ui/section.js";
import { visibleText } from "./support/leaks.mjs";
import { testCtx } from "./support/render-page.mjs";

const NOW = 1_800_000_000;

test("timeText shows no zone; the sidebar names it once", () => {
  const ctx = testCtx({ lang: "zh", timezone: "Europe/Helsinki", now: NOW });
  assert.doesNotMatch(timeText(ctx, NOW - 90000), /Helsinki|UTC/);
  const side = sidebar(ctx, []);
  assert.equal((visibleText(side).match(/Europe\/Helsinki/g) || []).length, 1);
});

test("timeCell is relative within a day, absolute otherwise and for the future", () => {
  const ctx = testCtx({ lang: "zh", now: NOW });
  assert.equal(timeCell(ctx, NOW - 30).textContent, "刚刚");
  assert.equal(timeCell(ctx, NOW - 12000).textContent, "3 小时 20 分钟前");
  assert.equal(timeCell(ctx, NOW - 90000).textContent, timeText(ctx, NOW - 90000));
  assert.equal(timeCell(ctx, NOW + 300).textContent, timeText(ctx, NOW + 300));
  assert.equal(timeCell(ctx, NOW - 12000).getAttribute("title"), timeText(ctx, NOW - 12000));
  assert.equal(timeCell(ctx, NOW - 12000).localName, "time");
});

test("timeCell of a non-finite time is a dash without a title", () => {
  const cell = timeCell(testCtx({ now: NOW }), NaN);
  assert.equal(cell.textContent, "—");
  assert.equal(cell.getAttribute("title"), null);
});

test("a missing zone falls back to UTC and says so", () => {
  const ctx = testCtx({ lang: "en", timezone: undefined, now: NOW });
  assert.match(visibleText(sidebar(ctx, [])), /UTC/);
});

test("the sidebar says why entry matters", () => {
  const ctx = testCtx({ lang: "en", now: NOW });
  assert.match(visibleText(sidebar(ctx, [])), /work only on site/);
});
