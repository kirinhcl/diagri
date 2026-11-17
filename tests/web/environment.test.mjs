import assert from "node:assert/strict";
import test from "node:test";

import { LEVELS, metricValue } from "../../src/growbridge/web/workbench/chart-math.js";
import {
  WINDOWS,
  ageText,
  channelRows,
  freshness,
  sensorValues,
  staleAfter,
} from "../../src/growbridge/web/workbench/pages/environment.js";
import en from "../../src/growbridge/web/workbench/i18n/en.js";
import { formatDuration } from "../../src/growbridge/web/workbench/format.js";
import { makeT } from "../../src/growbridge/web/workbench/i18n.js";
import { hrefFor, parseHash } from "../../src/growbridge/web/workbench/router.js";

const t = (key, vars) => (vars ? `${key}${JSON.stringify(vars)}` : key);

const reading = (overrides = {}) => ({
  age_seconds: 4,
  sensors: { temp: 22.5, humi: 55, co2: 500 },
  channels: {
    light: { level: 20, on: true },
    exhaust: { level: 25, on: true },
    fan: { level: 1, on: true },
    pump: { level: 0, on: false },
  },
  ...overrides,
});

test("a channel the stage controls is flagged when the device reports another level", () => {
  // what qwen3.6's round would have shown: the sheet wants 70, the device stays at 20
  const env = {
    latest: reading(),
    stage: { sampling_seconds: 300, channels: { light: { ownership: "host", expected: 70 }, fan: { ownership: "device", expected: null } } },
  };

  const rows = Object.fromEntries(channelRows(env).map((row) => [row.key, row]));

  assert.deepEqual(rows.light, { key: "light", level: 20, on: true, ownership: "host", expected: 70, mismatch: true });
  assert.equal(rows.fan.mismatch, false);
  assert.equal(rows.exhaust.ownership, null);
  assert.equal(rows.pump.on, false);
});

test("without a running stage nothing is a mismatch", () => {
  const rows = channelRows({ latest: reading(), stage: null });
  assert.ok(rows.every((row) => !row.mismatch && row.expected === null));
});

test("a reading is stale after three sampling intervals, or three minutes between stages", () => {
  assert.equal(staleAfter({ stage: { sampling_seconds: 300 } }), 900);
  assert.equal(staleAfter({ stage: { sampling_seconds: 5 } }), 60);
  assert.equal(staleAfter({ stage: null }), 180);
  assert.equal(freshness({ latest: null }), "none");
  assert.equal(freshness({ latest: reading({ age_seconds: 10 }), stage: null }), "fresh");
  assert.equal(freshness({ latest: reading({ age_seconds: 600 }), stage: null }), "stale");
});

test("sensors follow the chart order and units; ages read as every other duration does", () => {
  assert.deepEqual(
    sensorValues({ latest: reading() }).map(({ metric, value }) => [metric.key, value]),
    [["temp", 22.5], ["humi", 55], ["co2", 500]],
  );
  const zh = makeT("zh");
  for (const seconds of [42, 90, 600, 7200, 3 * 86400]) assert.equal(ageText(zh, seconds), formatDuration(zh, seconds), String(seconds));
  assert.equal(ageText(zh, 90), "90 秒");
  assert.equal(ageText(zh, 3 * 86400), "3 天");
  assert.equal(ageText(makeT("en"), 3 * 86400), "3 days");
  assert.equal(ageText(zh, 42.4), "42 秒", "a clock age has no tenths");
  assert.equal(ageText(zh, -3), "0 秒", "a clock a little ahead of the device reads as now");
});

test("channel levels are read where the device reports them", () => {
  const sample = { data: { light: { level: 70 }, blower: { level: 25 }, fan: { level: 1 }, sensor: { temp: 21 } } };
  assert.deepEqual(LEVELS.map((m) => metricValue(sample, m.key)), [70, 25, 1]);
  assert.equal(metricValue(sample, "temp"), 21);
  assert.equal(metricValue({ data: { light: {} } }, "light"), null);
});

test("the page has a route, a nav label and a label for every time range", () => {
  assert.deepEqual(parseHash(hrefFor("environment")), { page: "environment", params: {} });
  assert.ok(en["nav.environment"]);
  for (const seconds of WINDOWS) assert.ok(en[`env.window.${seconds}`], seconds);
  for (const key of ["light", "exhaust", "fan"]) assert.ok(en[`metric.${key}`], key);
});

const RUNNING = {
  stage_id: "stage-round_9d38ffa4ca3049948194e0b60315c650-1",
  state: "running",
  sampling_seconds: 300,
  project_name: "dev light stage",
  round_number: 2,
  stage_index: 1,
  phase: "vegetative",
  channels: { fan: { ownership: "host", expected: 1 }, pump: { ownership: "host", expected: null } },
};

async function envText(lang, stage = RUNNING) {
  const { renderPage } = await import("./support/render-page.mjs");
  const { FIXTURES } = await import("./support/render-page.mjs");
  const { visibleText } = await import("./support/leaks.mjs");
  const { element } = await renderPage("environment", {}, { lang, fixtures: { "environment.json": { ...FIXTURES["environment.json"], stage } } });
  return visibleText(element);
}

test("the fan shows its full scale and the pump its plan", async () => {
  const zh = await envText("zh");
  assert.ok(zh.includes("1 / 10"));
  assert.ok(zh.includes("运行单没有安排水泵"));
  const en = await envText("en");
  assert.ok(en.includes("The run sheet does not schedule the pump"));
});

test("the status line names the running stage, not its id", async () => {
  const zh = await envText("zh");
  assert.ok(zh.includes("正在运行：第 1 阶段 · vegetative"), zh.slice(0, 400));
  assert.ok(!zh.includes("stage-round_"));
});

test("a live refresh keeps open folds open and closed ones closed", async () => {
  const { renderPage } = await import("./support/render-page.mjs");
  const { element, refresh } = await renderPage("environment", {}, { lang: "en" });
  const folds = (node, out = []) => {
    if (node.localName === "details" && node.getAttribute("data-fold")) out.push(node);
    [...node.children].forEach((child) => folds(child, out));
    return out;
  };
  const byKey = () => Object.fromEntries(folds(element).map((d) => [d.getAttribute("data-fold"), d]));
  const before = byKey();
  assert.ok(before["temp:table"] && before["sensors:legend"] && before["co2:table"]);
  before["temp:table"].setAttribute("open", "");
  before["sensors:legend"].setAttribute("open", "");
  await refresh();
  const after = byKey();
  assert.notEqual(after["temp:table"], before["temp:table"]);
  assert.ok(after["temp:table"].hasAttribute("open"));
  assert.ok(after["sensors:legend"].hasAttribute("open"));
  assert.ok(!after["co2:table"].hasAttribute("open"));
});

// --- a refresh keeps an open unknown-state fold open (batch 2a, task 1) ----------------------------
import { renderPage, FIXTURES, installFakeDom } from "./support/render-page.mjs";

const foldsIn = (node) => [...(node.localName === "details" ? [node] : []), ...[...(node.children || [])].flatMap(foldsIn)];

test("a refresh with the same state keeps an open unknown-state fold open", async () => {
  installFakeDom();
  const env = (state) => ({ ...FIXTURES["environment.json"], stage: { stage_id: "s1", project_name: "P", state } });
  const { element, ctx, refresh } = await renderPage("environment", {}, { fixtures: { "environment.json": env("mystery") } });
  const [fold] = foldsIn(element);
  fold.setAttribute("open", "");
  await refresh();
  const [same] = foldsIn(element);
  assert.equal(same, fold, "the same state keeps the same fold");
  assert.ok(same.hasAttribute("open"));
  const get = ctx.api.get;
  ctx.api.get = async (...args) => ({ ...(await get(...args)), ...env("enigma") });
  await refresh();
  const [rebuilt] = foldsIn(element);
  assert.notEqual(rebuilt, fold, "another state rebuilds the row");
  assert.ok(!rebuilt.hasAttribute("open"));
});

// --- the run sheet's planned levels are drawn on the level charts (batch 2a, task 16) ---------------
test("the page draws the stage's planned levels on the level charts, and none when there is no plan", async () => {
  const planned = { light: [[1794817834, 0], [1794819000, 70]] };
  const withPlan = await envText("en", { ...RUNNING, planned });
  assert.ok(withPlan.includes("Planned level"));
  const without = await envText("en", { ...RUNNING, planned: {} });
  assert.ok(!without.includes("Planned"));
});
