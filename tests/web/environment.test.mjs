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

test("sensors follow the chart order and units; ages read in the largest whole unit", () => {
  assert.deepEqual(
    sensorValues({ latest: reading() }).map(({ metric, value }) => [metric.key, value]),
    [["temp", 22.5], ["humi", 55], ["co2", 500]],
  );
  assert.equal(ageText(t, 42), 'env.ageSeconds{"n":42}');
  assert.equal(ageText(t, 600), 'env.ageMinutes{"n":10}');
  assert.equal(ageText(t, 7200), 'env.ageHours{"n":2}');
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
