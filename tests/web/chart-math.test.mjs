import assert from "node:assert/strict";
import test from "node:test";

import { METRICS, metricValue, seriesPoints } from "../../src/growbridge/web/workbench/chart-math.js";

const sample = (t, temp, extra = {}) => ({
  timestamp: t,
  data: { sensor: { temp } },
  quality: "ok",
  clock_synced: true,
  flagged: 0,
  ...extra,
});
const box = { width: 100, height: 50, start: 0, end: 10 };

test("METRICS matches the dashboard metric list", () => {
  assert.deepEqual(
    METRICS.map((m) => [m.key, m.unit, m.precision]),
    [
      ["temp", "°C", 1],
      ["humi", "% RH", 1],
      ["vpd", "kPa", 2],
      ["co2", "ppm", 0],
      ["ppfd", "µmol/m²/s", 0],
      ["tempSoil", "°C", 1],
    ],
  );
});

test("metricValue reads data.sensor and ignores non-numbers", () => {
  assert.equal(metricValue(sample(1, 23.1), "temp"), 23.1);
  assert.equal(metricValue(sample(1, "x"), "temp"), null);
  assert.equal(metricValue(sample(1, null), "temp"), null);
  assert.equal(metricValue(sample(1, Number.NaN), "temp"), null);
  assert.equal(metricValue({ timestamp: 1 }, "temp"), null);
  assert.equal(metricValue(sample(1, 1), "humi"), null);
});

test("seriesPoints maps time to x and value to inverted y", () => {
  const { points, min, max } = seriesPoints([sample(0, 10), sample(5, 20), sample(10, 30)], "temp", box);
  assert.equal(min, 10);
  assert.equal(max, 30);
  assert.deepEqual(
    points.map((p) => [p.x, p.y, p.t, p.v]),
    [
      [0, 50, 0, 10],
      [50, 25, 5, 20],
      [100, 0, 10, 30],
    ],
  );
});

test("seriesPoints marks flagged samples", () => {
  const { points } = seriesPoints(
    [
      sample(1, 1),
      sample(2, 2, { quality: "suspect" }),
      sample(3, 3, { flagged: 2 }),
      sample(4, 4, { clock_synced: false }),
    ],
    "temp",
    box,
  );
  assert.deepEqual(
    points.map((p) => p.flagged),
    [false, true, true, true],
  );
});

test("seriesPoints skips empty values", () => {
  const { points } = seriesPoints([sample(1, null), sample(2, 5), sample(3, 6)], "temp", box);
  assert.equal(points.length, 2);
});

test("seriesPoints of no samples is empty", () =>
  assert.deepEqual(seriesPoints([], "temp", box), { points: [], min: null, max: null }));

test("a constant series is a centred line", () => {
  const { points } = seriesPoints([sample(1, 7), sample(5, 7)], "temp", box);
  assert.equal(points.length, 2);
  assert.ok(points.every((p) => p.y === box.height / 2));
});
