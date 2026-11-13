import assert from "node:assert/strict";
import test from "node:test";

import { METRICS, gapLimit, metricValue, seriesPoints, splitAtGaps } from "../../src/growbridge/web/workbench/chart-math.js";

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

// --- gaps: the line is never drawn across time without data ------------------------------------
const at = (...times) => times.map((t) => ({ t }));
const times = (segments) => segments.map((segment) => segment.map((point) => point.t));

test("seriesPoints marks a point that follows samples without this value", () => {
  const { points } = seriesPoints([sample(0, null), sample(1, 5), sample(2, null), sample(3, null), sample(4, 6), sample(5, 7)], "temp", box);
  assert.deepEqual(
    points.map((p) => [p.t, p.afterMissing]),
    [
      [1, false],
      [4, true],
      [5, false],
    ],
  );
});

test("splitAtGaps splits where consecutive points are further apart than the limit", () => {
  assert.deepEqual(times(splitAtGaps(at(0, 1, 2, 10, 11), 2.5)), [
    [0, 1, 2],
    [10, 11],
  ]);
});

test("splitAtGaps keeps points within the limit together, the limit itself included", () => {
  assert.deepEqual(times(splitAtGaps(at(0, 2, 4.5, 7), 2.5)), [[0, 2, 4.5, 7]]);
});

test("a lone point stays a segment of one", () => {
  assert.deepEqual(times(splitAtGaps(at(0, 1, 9, 20, 21), 2.5)), [[0, 1], [9], [20, 21]]);
  assert.deepEqual(times(splitAtGaps(at(5), 2.5)), [[5]]);
});

test("splitAtGaps of no points is no segments", () => {
  assert.deepEqual(splitAtGaps([], 2.5), []);
  assert.deepEqual(splitAtGaps(undefined, 2.5), []);
});

test("a point after missing values starts a new segment even within the limit", () => {
  const points = [{ t: 0 }, { t: 1 }, { t: 2, afterMissing: true }, { t: 3 }];
  assert.deepEqual(times(splitAtGaps(points, 10)), [
    [0, 1],
    [2, 3],
  ]);
});

test("without a limit only missing values split the line", () => {
  assert.deepEqual(times(splitAtGaps(at(0, 100, 1000), Infinity)), [[0, 100, 1000]]);
});

test("splitAtGaps does not change its input", () => {
  const points = at(0, 1, 9);
  const copy = structuredClone(points);
  splitAtGaps(points, 2.5);
  assert.deepEqual(points, copy);
});

test("gapLimit is 2.5 buckets, or 2.5 sampling intervals when those are longer", () => {
  assert.equal(gapLimit({ bucket_seconds: 4 }), 10);
  assert.equal(gapLimit({ bucket_seconds: 1 }, 5), 12.5);
  assert.equal(gapLimit({ bucket_seconds: 6 }, 2), 15);
  assert.equal(gapLimit(null, 2), 5);
  assert.equal(gapLimit(null), Infinity);
  assert.equal(gapLimit({ bucket_seconds: 0 }, Number.NaN), Infinity);
});
