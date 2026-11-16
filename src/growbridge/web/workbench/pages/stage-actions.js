// Stage controls. Which ones show follows stage-rules.js; the server stays the judge and every
// refusal is shown with its reason. Nothing is shown as done before the server answered.
import { ApiError } from "../api.js";
import { labelOr } from "../i18n.js";
import { claimIntent, intentKey, settleIntent, settleOnFinal } from "../intents.js";
import { answerLost, pollReceipt, RECEIPT_LIMIT_MS } from "../receipts.js";
import { approveBody, availableActions, heldByEntry, sheetCheck } from "../stage-rules.js";
import { confirmAction } from "../ui/dialog.js";
import { h } from "../ui/dom.js";
import { errorLines, jsonEditor, simpleForm } from "../ui/forms.js";
import { messageParts, messageView } from "../messages.js";
import { displayName } from "../ui/names.js";
import { formatDuration, levelText, shortDigest } from "../format.js";
import { differenceText } from "./stage-diff.js";
import { errorBox, errorFold, note, replaceParts, showErrors, techDetails, timeText } from "../ui/section.js";

// A manual write may only switch the pump off; irrigation is what switches it on.
const CHANNELS = ["light", "exhaust", "fan", "pump"];
const RECEIPT_TONE = {
  pending: "pill",
  applied: "pill pill-active",
  unknown: "pill pill-waiting",
  failed: "pill pill-onsite",
  unsettled: "pill pill-waiting",
};
// Controls that are one request without a body: the route verb, the button tone, an optional ask.
const PLAIN = {
  start: { verb: "start", tone: "primary" },
  resume: { verb: "resume", tone: "primary" },
  takeover: { verb: "takeover", tone: "quiet", ask: true },
  stop: { verb: "stop", tone: "danger", ask: true },
};
let counter = 0;

const stagePath = (stage, verb) => `/stages/${encodeURIComponent(stage.stage_id)}/${verb}`;

function group(name, title, ...children) {
  const wide = name === "draft";
  return h(
    "div",
    { class: ["action-group", wide && "action-group-wide"], attrs: { "data-action": name } },
    h("h3", { class: "action-title", text: title }),
    ...children,
  );
}

// After a write the server accepted: say so, then read the page again.
async function accepted(env, label) {
  env.ctx.notify(env.ctx.t("stage.actionDone", { action: label }), "ok");
  await env.onChanged();
}

// A refusal stays under its button; a state conflict is also announced and the page read again.
async function refused(env, box, error) {
  showErrors(box, error, env.ctx);
  if (error instanceof ApiError && error.code === "state") {
    env.ctx.notify(errorLines(error, env.ctx.lang, env.ctx.t).join(" "), "error");
    await env.onChanged();
  }
}

// A button that asks first when `ask` gives the dialog's text, and is disabled while it works.
function actionButton(env, { label, tone = "primary", ask = null, run }) {
  const box = errorBox();
  const button = h("button", { class: ["button", `button-${tone}`], attrs: { type: "button" }, text: label });
  button.addEventListener("click", async () => {
    box.hidden = true;
    const question = typeof ask === "function" ? ask() : ask;
    if (question && !(await confirmAction(env.ctx.t, { ...question, confirmLabel: label }))) return;
    button.disabled = true;
    try {
      await run();
      await accepted(env, label);
    } catch (error) {
      await refused(env, box, error);
    } finally {
      button.disabled = false;
    }
  });
  return { button, element: h("div", { class: "action" }, button, box) };
}

// What the confirm dialog of a plain action says: the stage by its name, never its id.
export function plainActionLines(ctx, name, stage) {
  return [ctx.t(`stage.${name}.line`, { stage: displayName(ctx, "stage", stage) })];
}

function plainAction(env, name) {
  const { ctx, stage } = env;
  const spec = PLAIN[name];
  const label = ctx.t(`stage.${name}`);
  const ask = spec.ask ? { title: ctx.t(`stage.${name}.title`), lines: plainActionLines(ctx, name, stage) } : null;
  const run = () => ctx.api.post(stagePath(stage, spec.verb), {}, { action: label });
  const control = actionButton(env, { label, tone: spec.tone, ask, run });
  return group(name, label, note(ctx.t(`stage.${name}.note`)), control.element);
}

// Blocking groups first; inside each, one group per code in order of first appearance.
export function groupFindings(findings) {
  const groups = [];
  for (const finding of Array.isArray(findings) ? findings : []) {
    const blocking = Boolean(finding.blocking);
    let group = groups.find((g) => g.blocking === blocking && g.code === finding.code);
    if (!group) {
      group = { blocking, code: finding.code, items: [] };
      groups.push(group);
    }
    group.items.push(finding);
  }
  return [...groups.filter((g) => g.blocking), ...groups.filter((g) => !g.blocking)];
}

// The message code of a finding: its code, plus the variant when it has one. Old data has neither
// a variant nor params.
function findingCode(item) {
  return item.variant ? `${item.code}.${item.variant}` : item.code;
}

function findingParams(item) {
  const p = item.params;
  return p && typeof p === "object" && !Array.isArray(p) ? p : {};
}

// What the group's fold holds: the group code, then each item's message code (when it differs from
// the group's), the server's own sentence and its id parameters.
function groupDetails(ctx, group, parts) {
  const details = [[ctx.t("tech.code"), group.code]];
  group.items.forEach((item, i) => {
    const code = findingCode(item);
    if (code !== group.code) details.push([ctx.t("tech.code"), code]);
    if (item.message) details.push([ctx.t("tech.serverMessage"), item.message]);
    details.push(...parts[i].details.filter(([name]) => name !== ctx.t("tech.code") && name !== ctx.t("tech.params")));
  });
  return details;
}

function howToFix(ctx, parts) {
  const actions = [...new Set(parts.map((p) => p.action).filter(Boolean))];
  if (!actions.length) return null;
  return h("p", { class: "finding-fix", text: `${ctx.t("stage.review.howToFix")} ${actions.join(" ")}` });
}

export function findingsList(ctx, findings) {
  const groups = groupFindings(findings);
  if (!groups.length) return note(ctx.t("stage.review.noFindings"));
  const pillClass = (blocking) => ["pill", blocking ? "pill-onsite" : "pill-waiting"];
  const entry = (group) => {
    const parts = group.items.map((item) => messageParts(ctx, "finding", findingCode(item), findingParams(item)));
    return h(
      "li",
      { class: "finding-group" },
      h(
        "p",
        { class: "finding" },
        h("span", { class: pillClass(group.blocking), text: ctx.t(group.blocking ? "finding.blocking" : "finding.hint") }),
        h("strong", { text: ctx.t("stage.review.groupTitle", { label: labelOr(ctx.t, "finding", group.code), n: group.items.length }) }),
      ),
      howToFix(ctx, parts),
      h("ul", { class: "finding-items" }, parts.map((p) => h("li", { class: "finding-text", text: p.text }))),
      techDetails(ctx.t, groupDetails(ctx, group, parts)),
    );
  };
  return h("ul", { class: "findings" }, groups.map(entry));
}

// --- pending review -------------------------------------------------------------------------------
// The env of a button whose own refusals carry their own title (not "the request failed").
function titledRefusals(env) {
  const own = { title: null };
  const t = (key, values) => (key === "error.title" && own.title ? own.title : env.ctx.t(key, values));
  return { own, env: { ...env, ctx: { ...env.ctx, t } } };
}

// Approve only the run sheet the review block shows: it is read again first and nothing is sent when
// its digest changed; what the server approved is compared too. Either refusal stays in the log.
function approveGroup(env) {
  const { ctx, stage, review } = env;
  const label = ctx.t("stage.approve");
  const reviewed = review ? review.run_sheet_digest : null;
  const { own, env: titled } = titledRefusals(env);
  const refuse = async (titleKey, lineKey, details = []) => {
    own.title = ctx.t(titleKey);
    const line = ctx.t(lineKey);
    env.log.add(label, [own.title, line, techDetails(ctx.t, details)]);
    ctx.notify(`${own.title}. ${line}`, "error");
    await env.onChanged();
    return new ApiError(0, "not_approved", line);
  };
  const run = async () => {
    own.title = null;
    const current = await ctx.api.get(`/stages/${encodeURIComponent(stage.stage_id)}/run-sheet`);
    if (sheetCheck(reviewed, current && current.run_sheet_digest) !== "same") throw await refuse("stage.approve.notApproved", "stage.approve.changed");
    const approval = await ctx.api.post(stagePath(stage, "approve"), approveBody(reviewed), { action: label });
    const time = timeText(ctx, approval.approved_at);
    const approved = ctx.t("stage.approved", { version: approval.run_sheet_version, digest: shortDigest(approval.run_sheet_digest), time });
    env.log.add(label, [approved, techDetails(ctx.t, [[ctx.t("stage.review.digest"), approval.run_sheet_digest]])]);
    if (sheetCheck(reviewed, approval.run_sheet_digest) !== "same") {
      throw await refuse("stage.approve.mismatchTitle", "stage.approve.mismatch", [
        [ctx.t("stage.approve.digestApproved"), approval.run_sheet_digest],
        [ctx.t("stage.approve.digestReviewed"), reviewed],
      ]);
    }
  };
  const control = actionButton(titled, { label, run });
  // Never approve what was not read, nor what the check blocks; the server checks both again.
  const why = !review ? ctx.t("stage.approve.unread") : review.blocking ? ctx.t("stage.approve.blocked") : null;
  control.button.disabled = Boolean(why);
  return group("approve", label, note(why || ctx.t("stage.approve.note")), control.element);
}

function draftGroup(env) {
  const { ctx, stage, review } = env;
  const title = ctx.t("stage.draft");
  if (!review) return group("draft", title, note(ctx.t("stage.approve.unread")));
  const submitLabel = ctx.t("stage.draft.submit");
  const findings = h("div", { class: "draft-findings", attrs: { hidden: true } });
  const onSubmit = async (body) => {
    findings.hidden = true;
    const answer = await ctx.api.post("/drafts/run-sheet", body, { action: submitLabel });
    const list = Array.isArray(answer && answer.findings) ? answer.findings : [];
    findings.replaceChildren(findingsList(ctx, list));
    findings.hidden = list.length === 0;
    if (list.some((finding) => finding.blocking)) throw new ApiError(0, "not_approved", ctx.t("stage.draft.refused"));
    await accepted(env, submitLabel);
  };
  const value = { round_id: env.roundId, run_sheet: review.run_sheet };
  const label = ctx.t("stage.draft.json");
  const editor = jsonEditor({ label, value, submitLabel, onSubmit, draftKey: `run-sheet:${stage.stage_id}`, ctx });
  return group("draft", title, note(ctx.t("stage.draft.note")), editor, findings);
}

// --- running and paused ---------------------------------------------------------------------------
function pauseGroup(env) {
  const { ctx, stage } = env;
  const submitLabel = ctx.t("stage.pause");
  const onSubmit = async ({ reason }) => {
    await ctx.api.post(stagePath(stage, "pause"), reason ? { reason } : {}, { action: submitLabel });
    await accepted(env, submitLabel);
  };
  const field = { name: "reason", label: ctx.t("stage.pause.reason") };
  return group("pause", submitLabel, simpleForm({ fields: [field], submitLabel, onSubmit, ctx }));
}

// --- manual control -------------------------------------------------------------------------------
// A device write. Its request id is made before it is sent and kept in the module-level intents
// (stage and action, so a re-render or an interleaved submission does not lose it); when no readable
// answer comes back the write may have happened, so it is listed as "result unknown, checking" and
// its receipt is followed under that id, and sending the identical request again reuses the id. The
// intent goes when an answer settles it, or when its followed receipt reaches a final outcome
// (applied, failed, unknown); a timeout, a left page or a failed follow-up keeps it until it expires
// after a few minutes. A resent request is said so in a line under its log heading.
async function deviceWrite(env, { action, channel, path, body, heading, label }) {
  const key = intentKey(env.stage.stage_id, action);
  const { id: requestId, reused } = claimIntent(key, body);
  let record;
  try {
    record = await env.ctx.api.post(path, { ...body, request_id: requestId }, { action: label });
  } catch (error) {
    if (!answerLost(error)) {
      settleIntent(key, requestId);
      throw error;
    }
    const pending = { request_id: requestId, created_at: Date.now() / 1000, state: "pending" };
    env.log.track(heading, pending, { lost: true, resent: reused, channel, onDone: () => settleIntent(key, requestId) });
    throw error;
  }
  settleIntent(key, requestId);
  env.log.track(heading, record, { resent: reused, channel });
  await env.onChanged();
}

export function manualHeading(ctx, channel, level) {
  return ctx.t("receipt.manual", { channel: labelOr(ctx.t, "channel", channel), level: levelText(ctx.t, channel, level) });
}

export function manualGroup(env) {
  const { ctx, stage } = env;
  const title = ctx.t("stage.manual");
  const options = CHANNELS.map((value) => ({ value, label: labelOr(ctx.t, "channel", value) }));
  const fields = [
    { name: "channel", label: ctx.t("stage.manual.channel"), type: "select", options, required: true },
    { name: "level", label: ctx.t("stage.manual.level"), type: "number", step: 1, required: true },
    { name: "note", label: ctx.t("stage.manual.note") },
  ];
  const onSubmit = async ({ channel, level, note: text }) => {
    const body = { stage_id: stage.stage_id, level, note: text || "" };
    const heading = manualHeading(ctx, channel, level);
    await deviceWrite(env, { action: `manual:${channel}`, channel, path: `/manual/${encodeURIComponent(channel)}`, body, heading, label: title });
  };
  const form = simpleForm({ fields, submitLabel: ctx.t("stage.manual.submit"), onSubmit, ctx });
  return group("manual", title, note(ctx.t("stage.manual.ranges")), form);
}

// Off the on-site entry the button stays visible but disabled, with the reason beside it.
function irrigationGroup(env, allowed) {
  const { ctx, stage } = env;
  const title = ctx.t("stage.irrigation");
  const submitLabel = ctx.t("stage.irrigation.submit");
  if (!allowed) {
    const id = `irrigation-why-${++counter}`;
    const why = h("p", { class: "block-note", attrs: { id }, text: ctx.t("stage.irrigation.lanOnly") });
    const attrs = { type: "button", disabled: true, "aria-describedby": id };
    return group("irrigation", title, why, h("button", { class: "button button-primary", attrs, text: submitLabel }));
  }
  const fields = [
    { name: "seconds", label: ctx.t("stage.irrigation.seconds"), type: "number", required: true },
    { name: "note", label: ctx.t("stage.manual.note") },
  ];
  const onSubmit = async ({ seconds, note: text }) => {
    const body = { stage_id: stage.stage_id, seconds, note: text || "" };
    const heading = ctx.t("receipt.irrigation", { seconds: formatDuration(ctx.t, Number(seconds)) });
    await deviceWrite(env, { action: "irrigation", channel: "pump", path: "/irrigation", body, heading, label: submitLabel });
  };
  return group("irrigation", title, simpleForm({ fields, submitLabel, onSubmit, ctx }));
}

export function differenceLines(ctx, differences) {
  const list = Array.isArray(differences) ? differences : [];
  if (!list.length) return [ctx.t("stage.handback.none")];
  const line = (item) => differenceText(ctx.t, item);
  return [ctx.t("stage.handback.differences"), ...list.map(line)];
}

function handbackGroup(env) {
  const { ctx, stage } = env;
  const label = ctx.t("stage.handback");
  const id = `handback-accept-${++counter}`;
  const check = h("input", { attrs: { id, type: "checkbox", name: "accept_as_intervention" } });
  const choice = h("label", { class: "check", attrs: { for: id } }, check, h("span", { text: ctx.t("stage.handback.accept") }));
  const ask = () => ({
    title: ctx.t("stage.handback.title"),
    lines: [ctx.t("stage.handback.line"), ctx.t(check.checked ? "stage.handback.willRecord" : "stage.handback.wontRecord")],
  });
  const run = async () => {
    const body = { accept_as_intervention: check.checked };
    const answer = await ctx.api.post(stagePath(stage, "handback"), body, { action: label });
    env.log.add(label, differenceLines(ctx, answer && answer.differences));
  };
  const control = actionButton(env, { label, ask, run });
  return group("handback", label, note(ctx.t("stage.handback.note")), choice, control.element);
}

// --- recovery check -------------------------------------------------------------------------------
function onsiteGroup(env) {
  const { ctx, stage } = env;
  const submitLabel = ctx.t("stage.onsite");
  const onSubmit = async ({ note: text }) => {
    await ctx.api.post(stagePath(stage, "onsite-check"), { note: text }, { action: submitLabel });
    await accepted(env, submitLabel);
  };
  const field = { name: "note", label: ctx.t("stage.onsite.note"), type: "textarea", required: true };
  return group("onsite_check", submitLabel, note(ctx.t("stage.onsite.lead")), simpleForm({ fields: [field], submitLabel, onSubmit, ctx }));
}

const BUILDERS = {
  approve: approveGroup,
  start: (env) => plainAction(env, "start"),
  draft: draftGroup,
  pause: pauseGroup,
  resume: (env) => plainAction(env, "resume"),
  takeover: (env) => plainAction(env, "takeover"),
  stop: (env) => plainAction(env, "stop"),
  manual: manualGroup,
  irrigation: (env) => irrigationGroup(env, true),
  handback: handbackGroup,
  onsite_check: onsiteGroup,
};

// env = { ctx, stage, review (null when unread), roundId, log, onChanged }
export function actionsView(env) {
  const { ctx, stage } = env;
  const entry = ctx.me && ctx.me.entry;
  const offered = availableActions(stage.state, entry).map((action) => BUILDERS[action](env));
  const held = heldByEntry(stage.state, entry).map(() => irrigationGroup(env, false));
  if (!offered.length && !held.length) return note(ctx.t("stage.noControls"));
  return h("div", { class: "stage-actions" }, offered, held);
}

// --- what came of the operator's writes: kept while the controls above are redrawn --------------
export function logItem(ctx, title, record) {
  const pill = h("span", { class: "pill" });
  const detail = h("div", { class: "activity-detail" });
  const meta = record ? ctx.t("receipt.request", { time: timeText(ctx, record.created_at) }) : null;
  const details = record ? techDetails(ctx.t, [[ctx.t("receipt.requestId"), record.request_id]]) : null;
  const element = h(
    "li",
    { class: "activity-item" },
    h("p", { class: "activity-title" }, record ? pill : null, h("span", { text: title })),
    detail,
    meta ? h("p", { class: "activity-meta", text: meta }) : null,
    details,
  );
  // Lines are text or nodes (a fold); the same again every poll leaves an opened fold as it is.
  const show = (status, lines) => {
    if (status) {
      pill.className = RECEIPT_TONE[status];
      pill.textContent = labelOr(ctx.t, "receipt", status);
    }
    // a failed receipt brings its own fold (with the request id); the item keeps just the one
    if (status === "failed" && details) details.remove();
    replaceParts(detail, lines.filter(Boolean).map((line) => (typeof line === "string" ? h("p", { text: line }) : line)));
  };
  return { element, show };
}

// Why a receipt could not be read, with the error's own words folded away; a 404 means the server
// holds nothing under that request id (yet).
export function checkParts(ctx, error) {
  if (error instanceof ApiError && error.status === 404) return [ctx.t("receipt.noRecord")];
  return [ctx.t("receipt.checkFailed", { error: errorLines(error, ctx.lang, ctx.t).join(" ") }), errorFold(ctx, error)];
}

// A failed write: its code through the catalog; the server's English and the request id in one fold.
function failedLines(ctx, record) {
  if (!record) return [null];
  const extra = [[ctx.t("receipt.requestId"), record.request_id], [ctx.t("tech.serverMessage"), record.error]];
  if (record.error_code) return messageView(ctx, "receipt", record.error_code, record.error_params, { extra });
  return [ctx.t("receipt.failedUnknown"), techDetails(ctx.t, extra)];
}

export function outcomeLines(ctx, { outcome, record, error }, channel) {
  const problem = error ? checkParts(ctx, error) : [];
  if (outcome === "applied") {
    const level = record && record.confirmed_level;
    return [level === null || level === undefined ? null : ctx.t("receipt.confirmedLevel", { level: levelText(ctx.t, channel, level) })];
  }
  if (outcome === "unknown") return [ctx.t("receipt.unknownNote")];
  if (outcome === "failed") return failedLines(ctx, record);
  return [ctx.t("receipt.unsettledNote", { duration: formatDuration(ctx.t, RECEIPT_LIMIT_MS / 1000) }), ...problem];
}

// life = { signal, alive() }: the page's lifetime; a poll ends when the page is left.
export function activityLog(ctx, life) {
  const list = h("ol", { class: "activity" });
  const title = h("h3", { class: "action-title", text: ctx.t("stage.log") });
  const element = h("div", { class: "activity-wrap", attrs: { hidden: true, role: "status", "aria-live": "polite" } }, title, list);
  const push = (item) => {
    element.hidden = false;
    list.prepend(item.element);
    return item;
  };
  const add = (heading, lines) => push(logItem(ctx, heading, null)).show(null, lines);
  // lost: no readable answer came for this write; it is followed under its request id all the same.
  const track = (heading, record, { lost = false, resent = false, channel, onDone = () => {} } = {}) => {
    const item = push(logItem(ctx, heading, record));
    const note = lost ? ctx.t("receipt.lost") : null;
    const resentNote = resent ? ctx.t("receipt.resent") : null;
    const show = (status, lines) => item.show(status, [resentNote, ...lines]);
    show("pending", [note]);
    const onUpdate = ({ error }) => show("pending", [note, ...(error ? checkParts(ctx, error) : [])]);
    const fetchReceipt = () => ctx.api.get(`/receipts/${encodeURIComponent(record.request_id)}`);
    const followed = pollReceipt({ initial: record, fetchReceipt, onUpdate, signal: life.signal, isActive: life.alive })
      .then((result) => {
        if (result.outcome !== "stopped") show(result.outcome === "timeout" ? "unsettled" : result.outcome, outcomeLines(ctx, result, channel));
        return result;
      })
      .catch((error) => show("unsettled", outcomeLines(ctx, { outcome: "unsettled", record, error }, channel)));
    settleOnFinal(followed, onDone);
  };
  return { element, add, track };
}
