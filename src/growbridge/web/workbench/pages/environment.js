// Live environment: what the device reads and does now, and what the running stage's run sheet
// expects of each channel at this moment. Refreshed every few seconds; a reading that stops
// arriving is said plainly, never shown as if it were current.
import { LEVELS, METRICS } from "../chart-math.js";
import { formatAge, formatNumber, levelText } from "../format.js";
import { hrefFor } from "../router.js";
import { openChartFolds, readingsChart, restoreChartFolds } from "../ui/chart.js";
import { clear, h } from "../ui/dom.js";
import { displayName } from "../ui/names.js";
import { note, pageHead, section, timeText } from "../ui/section.js";
import { statePillKeeper } from "../ui/status.js";

export const WINDOWS = [3600, 6 * 3600, 24 * 3600, 7 * 86400];
export const POLL_SECONDS = 5;
const POINTS = 360;
const CHANNELS = ["light", "exhaust", "fan", "pump"];
const IDLE_STALE_SECONDS = 180; // between stages the device is still read every few seconds
let chosenWindow = 6 * 3600; // kept while the console stays open

// Seconds without a new reading after which the newest one is no longer "now".
export function staleAfter(env) {
  const sampling = env && env.stage ? env.stage.sampling_seconds : null;
  return Number.isFinite(sampling) && sampling > 0 ? Math.max(3 * sampling, 60) : IDLE_STALE_SECONDS;
}

export function freshness(env) {
  const latest = env && env.latest;
  if (!latest) return "none";
  return latest.age_seconds > staleAfter(env) ? "stale" : "fresh";
}

// One row per channel: the recorded level and state, and what the running stage wants now.
// mismatch: the stage controls the channel, sets a level for now, and the device reports another.
export function channelRows(env) {
  const recorded = (env && env.latest && env.latest.channels) || {};
  const planned = (env && env.stage && env.stage.channels) || {};
  return CHANNELS.map((key) => {
    const now = recorded[key] || {};
    const plan = planned[key] || null;
    const level = typeof now.level === "number" ? now.level : null;
    const expected = plan && typeof plan.expected === "number" ? plan.expected : null;
    return {
      key,
      level,
      on: typeof now.on === "boolean" ? now.on : null,
      ownership: plan ? plan.ownership : null,
      expected,
      mismatch: expected !== null && level !== null && level !== expected,
    };
  });
}

// The sensors of the newest reading, in the order and with the units of the charts.
export function sensorValues(env) {
  const sensors = (env && env.latest && env.latest.sensors) || {};
  return METRICS.filter((metric) => typeof sensors[metric.key] === "number").map((metric) => ({
    metric,
    value: sensors[metric.key],
  }));
}

// How old the newest reading is, in the bands of every other duration; a device clock a little
// ahead reads as now.
export function ageText(t, seconds) {
  return formatAge(t, typeof seconds === "number" ? Math.max(0, seconds) : seconds);
}

function statusLine(ctx, env, statePillOf) {
  const parts = [];
  const state = freshness(env);
  if (state === "none") parts.push(h("span", { class: ["pill", "pill-waiting"], text: ctx.t("env.noData") }));
  else {
    const age = ageText(ctx.t, env.latest.age_seconds);
    const pill = state === "fresh" ? ["pill-active", "env.fresh"] : ["pill-onsite", "env.stale"];
    parts.push(h("span", { class: ["pill", pill[0]], text: ctx.t(pill[1], { age }) }));
    if (!env.latest.clock_synced) parts.push(h("span", { class: ["pill", "pill-waiting"], text: ctx.t("env.unsynced") }));
    if (env.latest.quality !== "ok") parts.push(h("span", { class: ["pill", "pill-waiting"], text: ctx.t("env.flagged") }));
  }
  if (env.stage) {
    const link = h("a", { attrs: { href: hrefFor("stage", { stageId: env.stage.stage_id }) }, text: ctx.t("env.stage", { name: displayName(ctx, "stage", env.stage) }) });
    parts.push(h("span", { class: "env-stage" }, link, statePillOf(env.stage.state)));
  } else parts.push(h("span", { class: "env-muted", text: ctx.t("env.noStage") }));
  const open = Object.values(env.alerts || {}).reduce((sum, n) => sum + n, 0);
  if (open > 0) parts.push(h("a", { class: "env-alerts", attrs: { href: hrefFor("alerts") }, text: ctx.t("env.alerts", { count: open }) }));
  return h("div", { class: "env-status", attrs: { role: "status" } }, parts);
}

function sensorTile(ctx, { metric, value }) {
  const text = `${formatNumber(value, metric.precision, ctx.lang)} ${metric.unit}`.trim();
  return h(
    "div",
    { class: "env-tile" },
    h("span", { class: "env-tile-name", text: ctx.t(`metric.${metric.key}`) }),
    h("span", { class: "env-tile-value", text }),
  );
}

function planLine(ctx, env, row) {
  if (row.ownership === null) return null;
  if (row.ownership !== "host") return ctx.t("env.deviceOwned");
  if (row.expected === null) return ctx.t(row.key === "pump" ? "env.pumpNotPlanned" : "env.notPlanned");
  return ctx.t("env.expected", { level: levelText(ctx.t, row.key, row.expected, rangeOf(env, row.key)) });
}

// The server's range for a channel, or undefined so that the default applies.
const rangeOf = (env, key) => env.level_ranges?.[key] ?? undefined;

function channelTile(ctx, env, row) {
  const range = rangeOf(env, row.key);
  const isLevel = row.key !== "pump";
  let value = ctx.t("env.unknown");
  if (isLevel && row.level !== null) value = levelText(ctx.t, row.key, row.level, range);
  else if (!isLevel && row.on !== null) value = ctx.t(row.on ? "env.on" : "env.off");
  let bar = null;
  if (isLevel && row.level !== null && Array.isArray(range) && range[1] > range[0]) {
    const share = Math.min(1, Math.max(0, (row.level - range[0]) / (range[1] - range[0])));
    const fill = h("div", { class: "env-bar-fill" });
    fill.style.width = `${(share * 100).toFixed(1)}%`; // CSSOM: the CSP refuses style attributes
    bar = h("div", { class: "env-bar", attrs: { "aria-hidden": "true" } }, fill);
  }
  const plan = planLine(ctx, env, row);
  return h(
    "div",
    { class: ["env-tile", row.mismatch ? "env-tile-mismatch" : null] },
    h("span", { class: "env-tile-name", text: ctx.t(`env.channel.${row.key}`) }),
    h("span", { class: "env-tile-value", text: value }),
    bar,
    plan ? h("span", { class: "env-tile-meta", text: plan }) : null,
    row.mismatch ? h("span", { class: ["pill", "pill-onsite"], text: `⚠ ${ctx.t("env.mismatch")}` }) : null,
  );
}

function nowView(ctx, env) {
  if (!env.latest) return note(ctx.t("env.noData"));
  const sensors = sensorValues(env);
  return h(
    "div",
    { class: "env-now" },
    h("h3", { class: "env-sub", text: ctx.t("env.sensors") }),
    sensors.length ? h("div", { class: "env-tiles" }, sensors.map((item) => sensorTile(ctx, item))) : note(ctx.t("env.noSensors")),
    h("h3", { class: "env-sub", text: ctx.t("env.channels") }),
    h("div", { class: "env-tiles" }, channelRows(env).map((row) => channelTile(ctx, env, row))),
    h("p", { class: "env-muted", text: ctx.t("env.readAt", { time: timeText(ctx, env.latest.timestamp) }) }),
  );
}

function trendsView(ctx, env) {
  const options = { timeZone: (ctx.me && ctx.me.timezone) || "UTC", lang: ctx.lang, now: ctx.now };
  const sampleSeconds = env.stage ? env.stage.sampling_seconds : null;
  return h(
    "div",
    { class: "env-trends" },
    h("h3", { class: "env-sub", text: ctx.t("env.sensors") }),
    readingsChart(ctx.t, env.readings, { ...options, sampleSeconds, empty: "env.readingsEmpty", scope: "sensors" }),
    h("h3", { class: "env-sub", text: ctx.t("env.channels") }),
    readingsChart(ctx.t, env.readings, { ...options, sampleSeconds, metrics: LEVELS, empty: "env.levelsEmpty", scope: "levels" }),
  );
}

function windowPicker(ctx, onPick) {
  const buttons = WINDOWS.map((seconds) =>
    h("button", {
      class: ["button", "button-quiet", "env-window"],
      attrs: { type: "button", "aria-pressed": String(seconds === chosenWindow) },
      text: ctx.t(`env.window.${seconds}`),
      on: { click: () => onPick(seconds) },
    }),
  );
  const group = h("div", { class: "env-windows", attrs: { role: "group", "aria-label": ctx.t("env.windowLabel") } }, buttons);
  const mark = () => buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(WINDOWS[i] === chosenWindow)));
  return { group, mark };
}

async function load(ctx) {
  return ctx.api.get(`/environment?window=${chosenWindow}&points=${POINTS}`);
}

export async function render(ctx) {
  let env = await load(ctx);
  const status = h("div");
  const now = h("div");
  const trends = h("div");
  const statePillOf = statePillKeeper(ctx.t);
  const draw = () => {
    clear(status).append(statusLine(ctx, env, statePillOf));
    clear(now).append(nowView(ctx, env));
    const open = openChartFolds(trends); // a poll must not close what the reader opened
    clear(trends).append(trendsView(ctx, env));
    restoreChartFolds(trends, open);
  };
  const refresh = async () => {
    env = await load(ctx);
    draw();
  };
  const picker = windowPicker(ctx, async (seconds) => {
    chosenWindow = seconds;
    picker.mark();
    await refresh();
  });
  draw();
  const element = h(
    "div",
    { class: "page environment" },
    pageHead(ctx.t("nav.environment"), ctx.t("env.lead", { seconds: POLL_SECONDS })),
    status,
    section(ctx.t("env.now"), now),
    section(ctx.t("env.trends"), picker.group, trends),
  );
  return { element, refresh, pollSeconds: POLL_SECONDS };
}
