import assert from "node:assert/strict";
import test from "node:test";

import {
  formatDateTime,
  formatDuration,
  formatMoney,
  formatNumber,
  formatTime,
  levelText,
  offsetMinutes,
  shortDigest,
  zonedToEpoch,
} from "../../src/growbridge/web/workbench/format.js";
import { makeT } from "../../src/growbridge/web/workbench/i18n.js";

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

const tz = makeT("zh"), te = makeT("en");
test("formatDuration picks the unit by size", () => {
  assert.equal(formatDuration(tz, 20), "20 秒");
  assert.equal(formatDuration(tz, 119.6), "2 分钟");
  assert.equal(formatDuration(tz, 300), "5 分钟");
  assert.equal(formatDuration(tz, 412.6), "7 分钟");
  assert.equal(formatDuration(tz, 12000), "3 小时 20 分钟");
  assert.equal(formatDuration(tz, 7200), "2 小时");
  assert.equal(formatDuration(tz, 504 * 3600), "21 天");
  assert.equal(formatDuration(te, 49.5 * 3600), "2 days 2 h");
  assert.equal(formatDuration(te, 600), "10 min");
  assert.equal(formatDuration(tz, -5), "—");
  assert.equal(formatDuration(tz, NaN), "—");
});
test("formatDateTime follows the language and shows the year only when it differs", () => {
  const at = Date.UTC(2026, 10, 20, 8, 0) / 1000; // 10:00 in Helsinki
  const now = Date.UTC(2026, 10, 21) / 1000;
  assert.equal(formatDateTime(at, "Europe/Helsinki", "zh", now), "11月20日 10:00");
  assert.equal(formatDateTime(at, "Europe/Helsinki", "en", now), "20 Nov 10:00");
  assert.equal(formatDateTime(at, "Europe/Helsinki", "zh", Date.UTC(2027, 0, 2) / 1000), "2026年11月20日 10:00");
  assert.equal(formatDateTime(Date.UTC(2026, 11, 31, 22, 30) / 1000, "Europe/Helsinki", "en", Date.UTC(2026, 11, 1) / 1000), "1 Jan 2027 00:30");
  assert.equal(formatDateTime(undefined, "UTC", "zh", now), "—");
});
test("levelText writes value over full scale", () => {
  assert.equal(levelText(tz, "fan", 3), "3 / 10");
  assert.equal(levelText(tz, "fan", 3, [0, 8]), "3 / 8");
  assert.equal(levelText(tz, "light", 50), "50 %");
  assert.equal(levelText(tz, "pump", 1), "开");
  assert.equal(levelText(te, "pump", 0), "off");
  assert.equal(levelText(tz, "fan", null), "—");
});
test("formatMoney has no float noise", () => {
  assert.equal(formatMoney(1.8300000000000001, "en"), "1.83");
  assert.equal(formatMoney(1234.5, "en"), "1,234.50");
  assert.equal(formatMoney(null, "zh"), "—");
});
test("shortDigest keeps eight characters", () => {
  assert.equal(shortDigest("8bc36a6f" + "0".repeat(56)), "8bc36a6f…");
  assert.equal(shortDigest(""), "—");
  assert.equal(shortDigest(undefined), "—");
});

test("levelText never prints undefined for an empty or null range", async () => {
  const { levelText } = await import("../../src/growbridge/web/workbench/format.js");
  const t = (key, vars) => (vars ? `${key}${JSON.stringify(vars)}` : key);
  assert.equal(levelText(t, "fan", 3, null), "3");
  assert.equal(levelText(t, "fan", 3, []), "3");
});
