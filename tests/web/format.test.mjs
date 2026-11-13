import assert from "node:assert/strict";
import test from "node:test";

import { formatNumber, formatTime, offsetMinutes, zonedToEpoch } from "../../src/growbridge/web/workbench/format.js";

const H = "Europe/Helsinki";

test("winter time converts at UTC+2", () =>
  assert.deepEqual(zonedToEpoch("2027-01-15T10:00", H), {
    epoch: Date.UTC(2027, 0, 15, 8, 0) / 1000,
    offsetMinutes: 120,
  }));

test("a time skipped by the spring change is refused", () =>
  assert.throws(() => zonedToEpoch("2027-03-28T03:30", H), RangeError));

test("a time repeated by the autumn change takes the earlier one", () =>
  assert.deepEqual(zonedToEpoch("2027-10-31T03:30", H), {
    epoch: Date.UTC(2027, 9, 31, 0, 30) / 1000,
    offsetMinutes: 180,
  }));

test("UTC converts with zero offset", () =>
  assert.deepEqual(zonedToEpoch("2027-01-15T10:00", "UTC"), {
    epoch: Date.UTC(2027, 0, 15, 10, 0) / 1000,
    offsetMinutes: 0,
  }));

test("offsetMinutes follows summer and winter time", () => {
  assert.equal(offsetMinutes(Date.UTC(2027, 6, 1) / 1000, H), 180);
  assert.equal(offsetMinutes(Date.UTC(2027, 0, 1) / 1000, H), 120);
});

test("formatTime shows the zone's wall time", () =>
  assert.equal(formatTime(Date.UTC(2027, 0, 15, 8, 0) / 1000, H, "en"), "2027-01-15 10:00"));

test("formatTime uses 24 hour clock at midnight", () =>
  assert.equal(formatTime(Date.UTC(2027, 0, 15, 22, 0) / 1000, H, "zh"), "2027-01-16 00:00"));

test("formatNumber shows a dash for missing values", () => {
  assert.equal(formatNumber(null, 1, "en"), "—");
  assert.equal(formatNumber(undefined, 1, "en"), "—");
  assert.equal(formatNumber(Number.NaN, 1, "en"), "—");
  assert.equal(formatNumber(Infinity, 1, "en"), "—");
});

test("impossible dates and times are refused", () => {
  const bad = [
    "2027-13-01T10:00",
    "2027-00-10T10:00",
    "2027-01-32T10:00",
    "2027-01-00T10:00",
    "2027-02-31T10:00",
    "2027-02-29T10:00",
    "2027-01-15T24:00",
    "2027-01-15T10:60",
    "2027-01-15T10:99",
    "",
    "not a time",
    "2027-01-15 10:00",
  ];
  for (const local of bad) {
    assert.throws(() => zonedToEpoch(local, "UTC"), RangeError, local);
  }
});

test("a leap day is accepted only in a leap year", () => {
  assert.equal(zonedToEpoch("2028-02-29T10:00", "UTC").epoch, Date.UTC(2028, 1, 29, 10, 0) / 1000);
  assert.equal(zonedToEpoch("2100-02-28T10:00", "UTC").epoch, Date.UTC(2100, 1, 28, 10, 0) / 1000);
  assert.throws(() => zonedToEpoch("2100-02-29T10:00", "UTC"), RangeError);
});

test("formatNumber applies precision", () => {
  assert.equal(formatNumber(23.14, 1, "en"), "23.1");
  assert.equal(formatNumber(0.5, 2, "en"), "0.50");
  assert.equal(formatNumber(412.6, 0, "en"), "413");
});
