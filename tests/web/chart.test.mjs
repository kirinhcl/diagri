import assert from "node:assert/strict";
import test from "node:test";

import { LEVELS } from "../../src/growbridge/web/workbench/chart-math.js";
import { readingsChart } from "../../src/growbridge/web/workbench/ui/chart.js";
import { FIXTURES, installFakeDom, testCtx } from "./support/render-page.mjs";
import { visibleText } from "./support/leaks.mjs";

installFakeDom();

const sample = (t, temp, level) => ({
  timestamp: t,
  data: { sensor: { temp }, fan: { level } },
  quality: "ok",
  clock_synced: true,
  flagged: 0,
});
const readings = {
  window: { start: 1796590000, end: 1796593600, bucket_seconds: 60 },
  samples: [sample(1796590000, 18.3, 1), sample(1796591800, 20.1, 1), sample(1796593600, 22.9, 2)],
  downsampled: false,
  total_samples: 3,
  flagged_total: 0,
};
const walk = (node, out = []) => {
  out.push(node);
  for (const child of node.children) walk(child, out);
  return out;
};
const classes = (node) => (node.getAttribute("class") || "").split(/\s+/);

test("the chart has tick labels, one status line and a data table", () => {
  const { t } = testCtx({ lang: "en" });
  const chart = readingsChart(t, readings, { timeZone: "Europe/Helsinki", lang: "en" });
  const text = visibleText(chart);
  for (const tick of ["18.1", "20.6", "23.1"]) assert.ok(text.includes(tick), tick);
  assert.ok(text.includes("3 readings"));
  assert.ok(text.includes("Legend") && text.includes("Data table"));
  const tables = walk(chart).filter((n) => n.localName === "table" && classes(n).includes("data-table"));
  assert.equal(tables.length, 1);
  const folds = walk(chart).filter((n) => n.localName === "details");
  assert.ok(folds.length >= 2);
});

test("a level chart is drawn against the channel's full scale", () => {
  const { t } = testCtx({ lang: "en" });
  const chart = readingsChart(t, readings, { timeZone: "UTC", lang: "en", metrics: LEVELS.filter((m) => m.key === "fan") });
  const text = visibleText(chart);
  for (const tick of ["0", "5", "10"]) assert.ok(text.split(/\s+/).includes(tick), tick);
});

test("fixture readings still draw", () => {
  const { t } = testCtx({ lang: "zh" });
  const chart = readingsChart(t, FIXTURES["readings.json"], { timeZone: "Europe/Helsinki", lang: "zh" });
  assert.ok(visibleText(chart).includes("个读数"));
});
