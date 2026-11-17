// One round: its state, stages, the choice after a stop, abort, and the confirmatory analysis.
import { shortDigest } from "../format.js";
import { hasLabel, labelOr } from "../i18n.js";
import { messageParts } from "../messages.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { confirmOrCancel, simpleForm } from "../ui/forms.js";
import { displayName, nameDetails, protocolName } from "../ui/names.js";
import { inline, richText } from "../ui/rich-text.js";
import { afterWrite, confirmedButton, errorParts, keyValues, note, pageHead, section, techDetails } from "../ui/section.js";
import { statePill } from "../ui/status.js";
import { table } from "../ui/table.js";
import { analysisSection } from "./round-analysis.js";

const CHOICES = ["redo", "next", "verify", "abort"];
const CLOSED = new Set(["delivered", "aborted"]); // nothing is left to abort
const LIMITATIONS_SHOWN = 3; // the rest of a report's limitations are folded away
const EFFECT_DIGITS = 3; // significant digits of an estimated effect
const P_DIGITS = 2; // significant digits of its p value

const isBlank = (value) => value === null || value === undefined || value === "";
const stagesOf = (round) => (Array.isArray(round.stages) ? round.stages : []);

function summary(ctx, round) {
  const href = hrefFor("project", { projectId: round.project_id });
  const project = h("a", { class: "text-link", attrs: { href }, text: displayName(ctx, "project", round) });
  return keyValues([
    [ctx.t("col.state"), statePill(ctx.t, round.state)],
    [ctx.t("round.project"), project],
    [ctx.t("col.protocol"), protocolName(ctx.t, round.protocol_id, round.protocol_version)],
    [ctx.t("round.progress"), `${round.stages_done} / ${round.stage_total}`],
  ]);
}

function stagesView(ctx, round) {
  const stages = stagesOf(round);
  if (!stages.length) return note(ctx.t("round.noStages"));
  const link = (row) => h("a", { class: "text-link", attrs: { href: hrefFor("stage", { stageId: row.stage_id }) }, text: displayName(ctx, "stage", row) });
  const columns = [
    { label: ctx.t("col.stage"), cell: link },
    { label: ctx.t("col.state"), cell: (row) => statePill(ctx.t, row.state) },
  ];
  return table(columns, stages, { label: ctx.t("round.stages") });
}

// What aborting does, said of the round by name.
export function abortLines(ctx, round) {
  return [ctx.t("round.abortLine", { round: displayName(ctx, "round", round) })];
}

// Every choice is asked first: abort in its own words, the others with one line of consequence.
function choicePrompt(ctx, round, choice) {
  if (choice === "abort") return { title: ctx.t("round.abortTitle"), lines: abortLines(ctx, round), confirmLabel: ctx.t("round.abort") };
  const label = ctx.t(`round.choice.${choice}`);
  return { title: label, lines: [ctx.t(`round.choice.${choice}.line`)], confirmLabel: label };
}

// Only shown while a stopped stage waits for the operator; the options are the server's choices.
function choiceForm(ctx, round) {
  const submitLabel = ctx.t("round.choose");
  const options = [{ value: "", label: ctx.t("form.choose") }, ...CHOICES.map((value) => ({ value, label: ctx.t(`round.choice.${value}`) }))];
  const field = { name: "choice", label: ctx.t("round.choiceLabel"), type: "select", options, required: true };
  const onSubmit = async ({ choice }) => {
    await confirmOrCancel(ctx, choicePrompt(ctx, round, choice));
    await ctx.api.post(`/rounds/${encodeURIComponent(round.round_id)}/choice`, { choice }, { action: submitLabel });
    afterWrite(ctx, ctx.t("round.chosen", { choice: ctx.t(`round.choice.${choice}`) }));
  };
  const form = simpleForm({ fields: [field], submitLabel, onSubmit, draftKey: `choice:${round.round_id}`, ctx });
  const stopped = stagesOf(round).find((row) => row.stage_id === round.awaiting_choice);
  return section(ctx.t("round.choiceTitle"), note(ctx.t("round.choiceStopped", { stage: displayName(ctx, "stage", stopped) })), form);
}

function abortButton(ctx, round) {
  const run = async () => {
    await ctx.api.post(`/rounds/${encodeURIComponent(round.round_id)}/abort`, {}, { action: ctx.t("round.abort") });
    afterWrite(ctx, ctx.t("round.aborted"));
  };
  return confirmedButton(ctx, { label: ctx.t("round.abort"), title: ctx.t("round.abortTitle"), lines: abortLines(ctx, round), tone: "danger", run });
}

// --- the published report ------------------------------------------------------------------------

// `count` significant digits in the page's language, never with an exponent ("1,230", not "1.23e+3").
function digits(value, count, lang) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(lang, { minimumSignificantDigits: count, maximumSignificantDigits: count }).format(value);
}

// The server's coded note on the estimate in the console's language, when the report has one.
function estimateNote(ctx, estimate) {
  const code = estimate && estimate.note_code;
  return typeof code === "string" && code ? messageParts(ctx, "estimate", code, estimate.note_params) : null;
}

// What the estimate says, in one line: the effect with its p value, or why there is none.
export function estimateText(ctx, estimate) {
  if (!estimate) return "—";
  if (!estimate.estimable) {
    const parts = estimateNote(ctx, estimate);
    return parts && parts.known ? parts.text : ctx.t("report.notEstimable");
  }
  const effect = digits(estimate.effect, EFFECT_DIGITS, ctx.lang);
  return ctx.t("report.estimate", { effect, p: digits(estimate.p_value, P_DIGITS, ctx.lang), blocks: estimate.blocks });
}

// The estimate's entries for the report's fold: its note's code and params, or an old report's
// English sentence (why there is no estimate, or, beside one, how its p value was approximated).
function estimateDetails(ctx, estimate) {
  const parts = estimateNote(ctx, estimate);
  if (parts) return parts.details;
  const old = estimate && !isBlank(estimate.note);
  return old ? [[ctx.t("report.estimateNote"), estimate.note]] : [];
}

// The estimate; under it the p value's meaning, what the note says to do, a note on an approximated
// p value and the measured quantity.
function estimateView(ctx, estimate, endpoint) {
  const text = estimateText(ctx, estimate);
  const withP = Boolean(estimate && estimate.estimable && typeof estimate.p_value === "number");
  const parts = estimateNote(ctx, estimate);
  const lines = [h("span", { text })];
  if (withP) lines.push(note(ctx.t("report.pHelp")));
  if (parts && estimate.estimable && parts.known) lines.push(note(parts.text));
  if (parts && !estimate.estimable && parts.action) lines.push(note(parts.action));
  if (!isBlank(endpoint)) lines.push(note(ctx.t("report.metric", { metric: ctx.t("common.quoted", { text: endpoint }) })));
  return lines.length === 1 ? text : h("div", {}, ...lines);
}

// A label or conclusion the report leaves out is "not stated", never a default.
function stated(ctx, prefix, value) {
  return isBlank(value) ? ctx.t("report.notStated") : labelOr(ctx.t, prefix, value);
}

// The label as a pill and, for a label the console knows, what it allows one to conclude.
function labelView(ctx, label) {
  const known = hasLabel(ctx.t, "report.labels", label);
  const pill = h("span", { class: ["pill", known ? `pill-label-${label}` : null], text: stated(ctx, "report.labels", label) });
  return known ? h("div", {}, pill, note(labelOr(ctx.t, "report.labelHelp", label))) : pill;
}

// The report's fold: its full fingerprint, its snapshot and its own id (the round's report id when
// the answer lacks one), and any code without text.
function reportDetails(ctx, data, label, round) {
  const report = data.report || {};
  const unknown = (prefix, value) => (isBlank(value) || hasLabel(ctx.t, prefix, value) ? null : value);
  return techDetails(ctx.t, [
    [ctx.t("report.sha256"), data.sha256],
    [ctx.t("tech.id.snapshot_id"), report.snapshot_id],
    [ctx.t("report.artifactId"), data.artifact_id || round.report_artifact_id],
    [ctx.t("report.label"), unknown("report.labels", label)],
    [ctx.t("report.conclusion"), unknown("report.conclusions", report.conclusion)],
    ...estimateDetails(ctx, report.estimate),
  ]);
}

// The items with their **bold** and `code`; past `shown` items, the rest in a closed fold.
function itemList(ctx, items, shown = Infinity) {
  const rows = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!rows.length) return note(ctx.t("report.none"));
  const list = (part) => h("ul", { class: "report-list" }, part.map((item) => h("li", {}, inline(String(item)))));
  if (rows.length <= shown) return list(rows);
  const rest = rows.slice(shown);
  const summaryText = ctx.t("report.moreItems", { count: rest.length });
  return [list(rows.slice(0, shown)), h("details", { class: "report-more" }, h("summary", { text: summaryText }), list(rest))];
}

// A report written with coded notes shows each server note in the console's language; an older
// report has only the plain-text fields, which are shown as they are.
export function reportLists(report, lang) {
  if (!Array.isArray(report.notes)) {
    return { reasons: report.reasons || [], limitations: report.limitations || [] };
  }
  const text = (entry) => (entry.text && (entry.text[lang] || entry.text.en)) || entry.code;
  const of = (kind) => report.notes.filter((entry) => entry.kind === kind).map(text);
  // The server's own findings first, so the cap on limitations never folds them under the model's text.
  return { reasons: of("reason"), limitations: [...of("limitation"), ...(report.model_limitations || [])] };
}

// `round` gives the report id when the report's answer lacks one.
export function reportView(ctx, data, round = {}) {
  const report = data.report || {};
  const lists = reportLists(report, ctx.lang);
  const label = report.label || data.label;
  const sub = (key) => h("h3", { class: "report-sub", text: ctx.t(key) });
  const nextRound = report.next_round ? richText(report.next_round, "rich-text report-text") : note(ctx.t("report.none"));
  return h(
    "div",
    { class: "report" },
    keyValues([
      [ctx.t("report.label"), labelView(ctx, label)],
      [ctx.t("report.conclusion"), stated(ctx, "report.conclusions", report.conclusion)],
      [ctx.t("report.estimateTitle"), estimateView(ctx, report.estimate, data.primary_endpoint)],
      [ctx.t("report.digest"), shortDigest(data.sha256)],
    ]),
    reportDetails(ctx, data, label, round),
    [sub("report.reasons"), itemList(ctx, lists.reasons)],
    [sub("report.limitations"), itemList(ctx, lists.limitations, LIMITATIONS_SHOWN)],
    [sub("report.unresolved"), itemList(ctx, report.unresolved)],
    [sub("report.nextRound"), nextRound],
  );
}

async function reportSection(ctx, round) {
  if (!round.report_artifact_id) return null;
  try {
    const data = await ctx.api.get(`/rounds/${encodeURIComponent(round.round_id)}/report`);
    return section(ctx.t("report.title"), reportView(ctx, data, round));
  } catch (error) {
    // The report could not be read: the error's own fold, and the round's report and snapshot ids.
    const ids = techDetails(ctx.t, [
      [ctx.t("report.artifactId"), round.report_artifact_id],
      [ctx.t("tech.id.snapshot_id"), round.snapshot_id],
    ]);
    return section(ctx.t("report.title"), h("div", { class: "form-status form-status-error" }, errorParts(ctx, error)), ids);
  }
}

export async function render(ctx, params) {
  const round = await ctx.api.get(`/rounds/${encodeURIComponent(params.roundId)}`);
  const name = displayName(ctx, "round", round);
  ctx.setBreadcrumbs([
    { label: ctx.t("nav.projects"), href: hrefFor("projects") },
    { label: displayName(ctx, "project", round), href: hrefFor("project", { projectId: round.project_id }) },
    { label: name },
  ]);
  const [analysis, report] = await Promise.all([analysisSection(ctx, round), reportSection(ctx, round)]);
  const element = h(
    "div",
    { class: "page round" },
    pageHead(name, ctx.t("round.lead")),
    techDetails(ctx.t, nameDetails(round, ctx.t)),
    section(ctx.t("round.summary"), summary(ctx, round)),
    report,
    round.awaiting_choice ? choiceForm(ctx, round) : null,
    section(ctx.t("round.stages"), stagesView(ctx, round)),
    CLOSED.has(round.state) ? null : section(ctx.t("round.abortSection"), note(ctx.t("round.abortNote")), abortButton(ctx, round)),
    analysis,
  );
  return { element };
}
