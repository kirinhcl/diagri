// One stage: status, controls, environment curves, run sheet review, measurements and history.
// Read again every 15 s; each part is redrawn only when what it shows changed, so nothing typed
// into a form is lost, and the results of writes stay listed while the controls change. The readings
// of a finished stage are asked for again only every five minutes.
import { formatNumber } from "../format.js";
import { hrefFor } from "../router.js";
import { readingsChart } from "../ui/chart.js";
import { clear, h } from "../ui/dom.js";
import { errorLines } from "../ui/forms.js";
import { codeBlock, keyValues, section, timeText } from "../ui/section.js";
import { statePill } from "../ui/status.js";
import { actionsView, activityLog, findingsList } from "./stage-actions.js";
import { historyView } from "./stage-history.js";
import { measurementForm, measurementTable } from "./stage-measurements.js";

const POLL_SECONDS = 15;
const READING_POINTS = 600;
const SECONDS_PER_HOUR = 3600;

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
  const paths = [base, `${base}/run-sheet`, readingsPath, `${base}/measurements`, `${base}/history`];
  const ask = (path) => (path ? ctx.api.get(path) : Promise.resolve(null));
  const results = (await Promise.allSettled(paths.map(ask))).map(settle);
  const [stage, review, readings, measurements, history] = results;
  if (stage.error) throw stage.error;
  return { stage: stage.value, review, readings: kept || readings, measurements, history };
}

// --- parts ------------------------------------------------------------------------------------------
function region(className) {
  const element = h("div", { class: className });
  let shown = null;
  const show = (signature, build) => {
    if (signature === shown) return;
    shown = signature;
    clear(element).append(build());
  };
  return { element, show };
}

function problemBox(lines) {
  return h("div", { class: "form-status form-status-error", attrs: { role: "status" } }, lines.map((line) => h("p", { text: line })));
}

function showResult(part, ctx, result, signatureOf, build) {
  if (result.error) {
    const lines = errorLines(result.error, ctx.lang, ctx.t);
    part.show(`error:${lines.join("|")}`, () => problemBox(lines));
    return;
  }
  part.show(signatureOf(result.value), () => build(result.value));
}

function roundCell(roundId) {
  return roundId ? h("a", { class: "text-link", attrs: { href: hrefFor("round", { roundId }) }, text: roundId }) : null;
}

function statusView(ctx, stage) {
  const projectHref = hrefFor("project", { projectId: stage.project_id });
  const dash = (value) => (value === null || value === undefined ? "—" : String(value));
  const rights = ctx.t("stage.rightsValue", { stage: dash(stage.right_number), care: dash(stage.care_right), manual: dash(stage.manual_right) });
  const rows = [
    [ctx.t("col.state"), statePill(ctx.t, stage.state)],
    stage.prior_state ? [ctx.t("stage.prior"), statePill(ctx.t, stage.prior_state)] : null,
    [ctx.t("stage.project"), h("a", { class: "text-link", attrs: { href: projectHref }, text: stage.project_id })],
    [ctx.t("stage.round"), roundCell(stage.round_id)],
    [ctx.t("stage.experiment"), stage.experiment_id],
    [ctx.t("stage.started"), timeText(ctx, stage.started_at)],
    [ctx.t("stage.pausedAt"), timeText(ctx, stage.paused_at)],
    [ctx.t("stage.endPending"), ctx.t(stage.end_pending ? "common.yes" : "common.no")],
    [ctx.t("stage.rights"), rights],
  ];
  return keyValues(rows.filter(Boolean));
}

function reviewView(ctx, review) {
  const sheet = review.run_sheet || {};
  const hours = Number.isFinite(sheet.duration_seconds) ? formatNumber(sheet.duration_seconds / SECONDS_PER_HOUR, 1, ctx.lang) : null;
  const facts = keyValues([
    [ctx.t("stage.review.version"), String(review.run_sheet_version)],
    [ctx.t("stage.review.digest"), h("code", { text: review.run_sheet_digest })],
    [ctx.t("col.protocol"), `${sheet.protocol_id} v${sheet.protocol_version}`],
    [ctx.t("stage.review.device"), sheet.device_id],
    [ctx.t("stage.review.duration"), hours && ctx.t("stage.review.durationValue", { hours })],
    [ctx.t("stage.review.timezone"), sheet.timezone],
  ]);
  const blocking = review.blocking ? problemBox([ctx.t("stage.review.blocking")]) : null;
  const json = h("details", { class: "sheet-json" }, h("summary", { text: ctx.t("stage.review.json") }), codeBlock(JSON.stringify(review.run_sheet, null, 2)));
  const findingsTitle = h("h3", { class: "action-title", text: ctx.t("stage.review.findings") });
  return h("div", { class: "review" }, facts, blocking, findingsTitle, findingsList(ctx, review.findings), json);
}

// Cheap enough to compare every 15 s; a running stage's window end moves, so it redraws then.
function readingsKey(readings) {
  const samples = Array.isArray(readings.samples) ? readings.samples : [];
  const last = samples.length ? samples[samples.length - 1].timestamp : null;
  return JSON.stringify([readings.window, readings.total_samples, readings.flagged_total, readings.downsampled, samples.length, last]);
}

function draw(page, data) {
  const { ctx, parts, head } = page;
  const { stage } = data;
  const review = data.review.error ? null : data.review.value;
  head.pill.replaceChildren(statePill(ctx.t, stage.state));
  head.updated.textContent = ctx.t("stage.updated", { time: timeText(ctx, Date.now() / 1000), seconds: POLL_SECONDS });
  parts.status.show(JSON.stringify(stage), () => statusView(ctx, stage));
  const actionKey = JSON.stringify([stage.state, stage.prior_state, review && review.run_sheet_digest, review && review.blocking, !review]);
  parts.actions.show(actionKey, () => actionsView({ ...page.env, stage, review, roundId: stage.round_id }));
  const sampleSeconds = review && review.run_sheet && review.run_sheet.sampling ? review.run_sheet.sampling.interval_seconds : null;
  const chart = (readings) => readingsChart(ctx.t, readings, { timeZone: zoneOf(ctx), lang: ctx.lang, sampleSeconds });
  showResult(parts.readings, ctx, data.readings, (readings) => `${readingsKey(readings)}|${sampleSeconds}`, chart);
  showResult(parts.review, ctx, data.review, (r) => JSON.stringify([r.run_sheet_digest, r.findings]), (r) => reviewView(ctx, r));
  showResult(parts.measurements, ctx, data.measurements, (r) => JSON.stringify(r.measurements), (r) => measurementTable(ctx, r.measurements));
  showResult(parts.history, ctx, data.history, (r) => JSON.stringify(r), (r) => historyView(ctx, r));
}

// --- the page ---------------------------------------------------------------------------------------
function headView(ctx, stageId, onRefresh) {
  const pill = h("span", { class: "stage-pill" });
  const updated = h("p", { class: "page-sub" });
  const button = h("button", { class: "button button-quiet", attrs: { type: "button" }, text: ctx.t("stage.refresh") });
  button.addEventListener("click", () => onRefresh());
  const title = h("div", { class: "stage-title" }, h("h1", { text: ctx.t("crumb.stage", { id: stageId }) }), pill);
  const text = h("div", {}, title, h("p", { class: "page-lead", text: ctx.t("stage.lead") }), updated);
  return { element: h("header", { class: "page-head" }, text, button), pill, updated };
}

function setCrumbs(ctx, stage) {
  const { project_id: projectId, round_id: roundId } = stage;
  const crumbs = [
    { label: ctx.t("nav.projects"), href: hrefFor("projects") },
    { label: ctx.t("crumb.project", { id: projectId }), href: hrefFor("project", { projectId }) },
  ];
  if (roundId) crumbs.push({ label: ctx.t("crumb.round", { id: roundId }), href: hrefFor("round", { roundId }) });
  crumbs.push({ label: ctx.t("crumb.stage", { id: stage.stage_id }) });
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
  const names = ["status", "actions", "readings", "review", "measurements", "history"];
  return Object.fromEntries(names.map((name) => [name, region(`stage-part stage-part-${name}`)]));
}

function sections(ctx, page, stage, onRecorded) {
  const { parts } = page;
  const newMeasurement = h("h3", { class: "action-title", text: ctx.t("measure.new") });
  return [
    page.head.element,
    page.problem,
    section(ctx.t("stage.status"), parts.status.element),
    section(ctx.t("stage.controls"), parts.actions.element, page.log.element),
    section(ctx.t("stage.readings"), parts.readings.element),
    section(ctx.t("stage.runSheet"), parts.review.element),
    section(ctx.t("stage.measurements"), parts.measurements.element, newMeasurement, measurementForm(ctx, stage, onRecorded)),
    section(ctx.t("stage.history"), parts.history.element),
  ];
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
      problem.replaceChildren(...[ctx.t("stage.stale"), ...errorLines(error, ctx.lang, ctx.t)].map((line) => h("p", { text: line })));
      problem.hidden = false;
    }
  });
  page.head = headView(ctx, params.stageId, refresh);
  page.env = { ctx, log: page.log, onChanged: refresh };
  const onRecorded = async (message) => {
    ctx.notify(message, "ok");
    await refresh();
  };
  element.append(...sections(ctx, page, first.stage, onRecorded));
  draw(page, first);
  return { element, refresh, pollSeconds: POLL_SECONDS };
}
