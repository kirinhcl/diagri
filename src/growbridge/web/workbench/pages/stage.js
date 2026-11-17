// One stage: status, controls, environment curves, run sheet review, manual tasks, measurements
// and history.
// Read again every 15 s; each part is redrawn only when what it shows changed, so nothing typed
// into a form is lost, and the results of writes stay listed while the controls change. The readings
// of a finished stage are asked for again only every five minutes.
import { formatDuration, shortDigest } from "../format.js";
import { hrefFor } from "../router.js";
import { openChartFolds, readingsChart, restoreChartFolds } from "../ui/chart.js";
import { clear, h } from "../ui/dom.js";
import { errorDetail, errorLines } from "../ui/forms.js";
import { deviceName, displayName, nameDetails } from "../ui/names.js";
import { errorParts, keyValues, replaceParts, section, techDetails, timeText } from "../ui/section.js";
import { statePill, statePillKeeper } from "../ui/status.js";
import { actionsView, activityLog, findingsList } from "./stage-actions.js";
import { historyView } from "./stage-history.js";
import { measurementForm, measurementsView } from "./stage-measurements.js";
import { tasksView } from "./stage-tasks.js";

const POLL_SECONDS = 15;
const READING_POINTS = 600;

const enc = encodeURIComponent;
const zoneOf = (ctx) => (ctx.me && ctx.me.timezone) || "UTC";

// Runs fn now, or once more after the run in flight: a write is always followed by a read that
// started after it, even when a timed refresh was already under way.
export function coalesce(fn) {
  let running = null;
  let queued = null;
  const start = () => {
    let result;
    try {
      result = Promise.resolve(fn());
    } catch (error) {
      result = Promise.reject(error);
    }
    running = result.finally(() => {
      running = null;
    });
    return running;
  };
  return () => {
    if (!running) return start();
    if (!queued) {
      queued = running
        .catch(() => {})
        .then(() => {
          queued = null;
          return start();
        });
    }
    return queued;
  };
}

// --- reading ----------------------------------------------------------------------------------------
const settle = (result) => (result.status === "fulfilled" ? { value: result.value } : { error: result.reason });

// A finished stage's window can still gain late backlog samples, so its readings are re-read every
// FINISHED_REREAD_SECONDS rather than every poll or never. They are kept only when the payload
// proves it is the finished window: the stage is finished and the window ends at the stage's state_at.
const FINISHED = new Set(["ended", "stopped"]);
export const FINISHED_REREAD_SECONDS = 300;
export function frozenReadings(stage, readings) {
  if (!stage || !FINISHED.has(stage.state) || !readings || readings.error) return null;
  const end = readings.value && readings.value.window ? readings.value.window.end : undefined;
  return typeof end === "number" && end === stage.state_at ? readings : null;
}

// Kept readings are used while younger than the re-read interval (times in milliseconds).
export const keptIsFresh = (keptAt, nowMs) => keptAt !== null && nowMs - keptAt < FINISHED_REREAD_SECONDS * 1000;

// The stage itself must be readable; any other part that fails says so in its own place.
// `kept` is a finished stage's readings result, used instead of asking again.
async function loadAll(ctx, stageId, kept = null) {
  const base = `/stages/${enc(stageId)}`;
  const readingsPath = kept ? null : `${base}/readings?points=${READING_POINTS}`;
  const paths = [base, `${base}/run-sheet`, readingsPath, `${base}/measurements`, `${base}/history`, `${base}/manual-tasks`];
  const ask = (path) => (path ? ctx.api.get(path) : Promise.resolve(null));
  const results = (await Promise.allSettled(paths.map(ask))).map(settle);
  const [stage, review, readings, measurements, history, tasks] = results;
  if (stage.error) throw stage.error;
  return { stage: stage.value, review, readings: kept || readings, measurements, history, tasks };
}

// --- parts ------------------------------------------------------------------------------------------
// A part drawn again only when its signature changes; folds with a data-fold key (the chart's legend
// and data tables, the tasks' folds) that were open stay open across the redraw.
function region(className) {
  const element = h("div", { class: className });
  let shown = null;
  const show = (signature, build) => {
    if (signature === shown) return;
    shown = signature;
    const open = openChartFolds(element);
    clear(element).append(build());
    restoreChartFolds(element, open);
  };
  return { element, show };
}

function problemBox(nodes) {
  return h("div", { class: "form-status form-status-error", attrs: { role: "status" } }, nodes);
}

// A part that could not be read: drawn again only when the error says something else, so a fold
// opened between polls stays open.
function showResult(part, ctx, result, signatureOf, build) {
  if (result.error) {
    const said = [errorLines(result.error, ctx.lang, ctx.t, ctx), errorDetail(result.error, ctx.t)];
    part.show(`error:${JSON.stringify(said)}`, () => problemBox(errorParts(ctx, result.error)));
    return;
  }
  part.show(signatureOf(result.value), () => build(result.value));
}

function roundCell(ctx, stage) {
  const text = displayName(ctx, "round", stage);
  return stage.round_id ? h("a", { class: "text-link", attrs: { href: hrefFor("round", { roundId: stage.round_id }) }, text }) : text;
}

// Write rights are counters for the audit trail, not for the operator: details only.
function rightsEntries(t, stage) {
  return [
    [t("tech.right.stage"), stage.right_number],
    [t("tech.right.care"), stage.care_right],
    [t("tech.right.manual"), stage.manual_right],
  ];
}

export function statusView(ctx, stage) {
  const projectHref = hrefFor("project", { projectId: stage.project_id });
  const projectName = displayName(ctx, "project", stage);
  const rows = [
    [ctx.t("col.state"), statePill(ctx.t, stage.state)],
    stage.prior_state ? [ctx.t("stage.prior"), statePill(ctx.t, stage.prior_state)] : null,
    [ctx.t("stage.project"), h("a", { class: "text-link", attrs: { href: projectHref }, text: projectName })],
    [ctx.t("stage.round"), roundCell(ctx, stage)],
    [ctx.t("stage.started"), timeText(ctx, stage.started_at)],
    stage.paused_at ? [ctx.t("stage.pausedAt"), timeText(ctx, stage.paused_at)] : null,
  ];
  const banner = stage.end_pending ? h("p", { class: "block-note", text: ctx.t("stage.endPending") }) : null;
  const details = techDetails(ctx.t, rightsEntries(ctx.t, stage));
  return h("div", { class: "status-view" }, keyValues(rows.filter(Boolean)), banner, details);
}

export function reviewView(ctx, review) {
  const sheet = review.run_sheet || {};
  const device = deviceName(ctx.t, sheet.device_id);
  const protocol = sheet.protocol_id ? ctx.t("stage.review.protocolValue", { id: sheet.protocol_id, v: sheet.protocol_version }) : null;
  const facts = keyValues([
    [ctx.t("stage.review.version"), ctx.t("stage.review.versionValue", { n: review.run_sheet_version })],
    [ctx.t("stage.review.fingerprint"), shortDigest(review.run_sheet_digest)],
    [ctx.t("col.protocol"), protocol],
    [ctx.t("stage.review.device"), device],
    [ctx.t("stage.review.duration"), Number.isFinite(sheet.duration_seconds) ? formatDuration(ctx.t, sheet.duration_seconds) : null],
    [ctx.t("stage.review.timezone"), sheet.timezone],
  ]);
  const blocking = review.blocking ? problemBox([ctx.t("stage.review.blocking")]) : null;
  const findingsTitle = h("h3", { class: "action-title", text: ctx.t("stage.review.findings") });
  const sheetFold = techDetails(ctx.t, [[ctx.t("stage.review.json"), JSON.stringify(review.run_sheet, null, 2)]], { summary: ctx.t("stage.review.json") });
  const tech = techDetails(ctx.t, [[ctx.t("stage.review.digest"), review.run_sheet_digest]]);
  return h("div", { class: "review" }, facts, sheetFold, blocking, findingsTitle, findingsList(ctx, review.findings), tech);
}

// Cheap enough to compare every 15 s; a running stage's window end moves, so it redraws then.
function readingsKey(readings) {
  const samples = Array.isArray(readings.samples) ? readings.samples : [];
  const last = samples.length ? samples[samples.length - 1].timestamp : null;
  return JSON.stringify([readings.window, readings.total_samples, readings.flagged_total, readings.downsampled, samples.length, last]);
}

// Moves the existing region nodes (keeping forms, the log and receipt polls) when the stage's state
// calls for another order than the one on the page.
function arrange(page, state) {
  const order = sectionOrder(state);
  if (page.applied && page.applied.join() === order.join()) return;
  page.applied = order;
  page.container.append(...order.map((name) => page.regions[name]));
}

function draw(page, data) {
  const { ctx, parts, head } = page;
  const { stage } = data;
  arrange(page, stage.state);
  const review = data.review.error ? null : data.review.value;
  head.pill.replaceChildren(head.statePill(stage.state));
  head.updated.textContent = ctx.t("stage.updated", { time: timeText(ctx, Date.now() / 1000), seconds: formatDuration(ctx.t, POLL_SECONDS) });
  parts.status.show(JSON.stringify(stage), () => statusView(ctx, stage));
  const actionKey = JSON.stringify([stage.state, stage.prior_state, review && review.run_sheet_digest, review && review.blocking, !review]);
  parts.actions.show(actionKey, () => actionsView({ ...page.env, stage, review, roundId: stage.round_id }));
  const sampleSeconds = review && review.run_sheet && review.run_sheet.sampling ? review.run_sheet.sampling.interval_seconds : null;
  const chart = (readings) => readingsChart(ctx.t, readings, { timeZone: zoneOf(ctx), lang: ctx.lang, sampleSeconds, now: ctx.now });
  showResult(parts.readings, ctx, data.readings, (readings) => `${readingsKey(readings)}|${sampleSeconds}`, chart);
  showResult(parts.review, ctx, data.review, (r) => JSON.stringify([r.run_sheet_digest, r.findings]), (r) => reviewView(ctx, r));
  const tasksKey = (r) => JSON.stringify([r.stage_state, r.occurrences, Math.floor((r.now || 0) / 60)]);
  const tasksEnv = { ...page.env, stage }; // ctx, the activity log (planned irrigation receipts), onChanged
  showResult(parts.tasks, ctx, data.tasks, tasksKey, (r) => tasksView(tasksEnv, r));
  showResult(parts.measurements, ctx, data.measurements, (r) => JSON.stringify(r.measurements), (r) => measurementsView(ctx, r.measurements, page.measure));
  showResult(parts.history, ctx, data.history, (r) => JSON.stringify(r), (r) => historyView(ctx, r));
}

// --- the page ---------------------------------------------------------------------------------------
function headView(ctx, stage, onRefresh) {
  const pill = h("span", { class: "stage-pill" });
  const updated = h("p", { class: "page-sub" });
  const button = h("button", { class: "button button-quiet", attrs: { type: "button" }, text: ctx.t("stage.refresh") });
  button.addEventListener("click", () => onRefresh());
  const title = h("div", { class: "stage-title" }, h("h1", { text: displayName(ctx, "stage", stage) }), pill);
  const text = h("div", {}, title, h("p", { class: "page-lead", text: ctx.t("stage.lead") }), updated, techDetails(ctx.t, nameDetails(stage, ctx.t)));
  return { element: h("header", { class: "page-head" }, text, button), pill, updated, statePill: statePillKeeper(ctx.t) };
}

function setCrumbs(ctx, stage) {
  const { project_id: projectId, round_id: roundId } = stage;
  const crumbs = [
    { label: ctx.t("nav.projects"), href: hrefFor("projects") },
    { label: displayName(ctx, "project", stage), href: hrefFor("project", { projectId }) },
  ];
  if (roundId) crumbs.push({ label: displayName(ctx, "round", stage), href: hrefFor("round", { roundId }) });
  crumbs.push({ label: displayName(ctx, "stage", stage) });
  ctx.setBreadcrumbs(crumbs);
}

// The page's lifetime: it ends when the address moves on or the page is no longer shown, and
// every receipt poll checks it, so no timer outlives the page.
function pageLife(element) {
  const controller = new AbortController();
  const at = location.hash;
  const onMove = () => {
    if (location.hash !== at) controller.abort();
  };
  window.addEventListener("hashchange", onMove, { signal: controller.signal });
  return { signal: controller.signal, alive: () => !controller.signal.aborted && element.isConnected };
}

function makeParts() {
  const names = ["status", "actions", "readings", "review", "tasks", "measurements", "history"];
  return Object.fromEntries(names.map((name) => [name, region(`stage-part stage-part-${name}`)]));
}

// The regions of the page, in the order each state wants them: a stage waiting for review leads
// with the run sheet to read; a live one leads with its readings and controls.
const READING_FIRST = ["status", "readings", "controls", "tasks", "measurements", "runSheet", "history"];
const ORDERS = {
  pending_review: ["status", "runSheet", "controls", "tasks", "measurements", "history", "readings"],
  running: READING_FIRST,
  paused: READING_FIRST,
};
const DEFAULT_ORDER = ["status", "controls", "readings", "runSheet", "tasks", "measurements", "history"];

export function sectionOrder(state) {
  return [...(ORDERS[state] || DEFAULT_ORDER)];
}

function sections(ctx, page, stage, onRecorded) {
  const { parts } = page;
  const newMeasurement = h("h3", { class: "action-title", text: ctx.t("measure.new") });
  page.measure = measurementForm(ctx, stage, onRecorded);
  const regions = {
    status: section(ctx.t("stage.status"), parts.status.element),
    controls: section(ctx.t("stage.controls"), parts.actions.element, page.log.element),
    readings: section(ctx.t("stage.readings"), parts.readings.element),
    runSheet: section(ctx.t("stage.runSheet"), parts.review.element),
    tasks: section(ctx.t("stage.tasks"), parts.tasks.element),
    measurements: section(ctx.t("stage.measurements"), parts.measurements.element, newMeasurement, page.measure.element),
    history: section(ctx.t("stage.history"), parts.history.element),
  };
  page.regions = regions;
  return [page.head.element, page.problem];
}

export async function render(shellCtx, params) {
  const first = await loadAll(shellCtx, params.stageId);
  setCrumbs(shellCtx, first.stage);
  // Everything on this page reads again in place: a form's state conflict (409) calls ctx.reload,
  // and a full re-render would drop the action log and stop the receipt polls still running.
  const ctx = { ...shellCtx, reload: () => refresh() };
  const element = h("div", { class: "page stage" });
  const problem = h("div", { class: "form-status form-status-error", attrs: { role: "status", hidden: true } });
  const page = { ctx, parts: makeParts(), problem, log: activityLog(ctx, pageLife(element)) };
  let kept = null; // { readings, at } of a finished stage, until it is due again
  const refresh = coalesce(async () => {
    try {
      const use = kept && keptIsFresh(kept.at, Date.now()) ? kept.readings : null;
      const data = await loadAll(ctx, params.stageId, use);
      if (!use) {
        const frozen = frozenReadings(data.stage, data.readings);
        kept = frozen ? { readings: frozen, at: Date.now() } : null;
      }
      draw(page, data);
      problem.hidden = true;
    } catch (error) {
      replaceParts(problem, [h("p", { text: ctx.t("stage.stale") }), ...errorParts(ctx, error)]);
      problem.hidden = false;
    }
  });
  page.head = headView(ctx, first.stage, refresh);
  page.env = { ctx, log: page.log, onChanged: refresh };
  const onRecorded = async (message) => {
    ctx.notify(message, "ok");
    await refresh();
  };
  page.container = element;
  element.append(...sections(ctx, page, first.stage, onRecorded));
  draw(page, first);
  return { element, refresh, pollSeconds: POLL_SECONDS };
}
