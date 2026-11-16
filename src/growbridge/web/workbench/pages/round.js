// One round: its state, stages, the choice after a stop, abort, and the confirmatory analysis.
import { labelOr } from "../i18n.js";
import { hrefFor } from "../router.js";
import { confirmAction } from "../ui/dialog.js";
import { h } from "../ui/dom.js";
import { errorLines, simpleForm } from "../ui/forms.js";
import { afterWrite, confirmedButton, keyValues, note, pageHead, section } from "../ui/section.js";
import { statePill } from "../ui/status.js";
import { table } from "../ui/table.js";
import { analysisSection } from "./round-analysis.js";

const CHOICES = ["redo", "next", "verify", "abort"];
const CLOSED = new Set(["delivered", "aborted"]); // nothing is left to abort

function summary(ctx, round) {
  const project = h("a", { class: "text-link", attrs: { href: hrefFor("project", { projectId: round.project_id }) }, text: round.project_id });
  return keyValues([
    [ctx.t("col.state"), statePill(ctx.t, round.state)],
    [ctx.t("round.project"), project],
    [ctx.t("col.protocol"), `${round.protocol_id} v${round.protocol_version}`],
    [ctx.t("round.progress"), `${round.stages_done} / ${round.stage_total}`],
    [ctx.t("round.snapshot"), round.snapshot_id],
    [ctx.t("round.report"), round.report_artifact_id],
  ]);
}

function stagesView(ctx, round) {
  const stages = Array.isArray(round.stages) ? round.stages : [];
  if (!stages.length) return note(ctx.t("round.noStages"));
  const columns = [
    {
      label: ctx.t("col.stage"),
      cell: (row) => h("a", { class: "text-link", attrs: { href: hrefFor("stage", { stageId: row.stage_id }) }, text: row.stage_id }),
    },
    { label: ctx.t("col.state"), cell: (row) => statePill(ctx.t, row.state) },
  ];
  return table(columns, stages, { label: ctx.t("round.stages") });
}

function askAbort(ctx, round) {
  const lines = [ctx.t("round.abortLine", { id: round.round_id })];
  return confirmAction(ctx.t, { title: ctx.t("round.abortTitle"), lines, confirmLabel: ctx.t("round.abort") });
}

// Only shown while a stopped stage waits for the operator; the options are the server's choices.
function choiceForm(ctx, round) {
  const submitLabel = ctx.t("round.choose");
  const options = CHOICES.map((value) => ({ value, label: ctx.t(`round.choice.${value}`) }));
  const field = { name: "choice", label: ctx.t("round.choiceLabel"), type: "select", options, required: true };
  const onSubmit = async ({ choice }) => {
    if (choice === "abort" && !(await askAbort(ctx, round))) return;
    await ctx.api.post(`/rounds/${encodeURIComponent(round.round_id)}/choice`, { choice }, { action: submitLabel });
    afterWrite(ctx);
  };
  const form = simpleForm({ fields: [field], submitLabel, onSubmit, draftKey: `choice:${round.round_id}`, ctx });
  return section(ctx.t("round.choiceTitle"), note(ctx.t("inbox.roundChoice", { stage: round.awaiting_choice })), form);
}

function abortButton(ctx, round) {
  const run = async () => {
    await ctx.api.post(`/rounds/${encodeURIComponent(round.round_id)}/abort`, {}, { action: ctx.t("round.abort") });
    afterWrite(ctx);
  };
  const lines = [ctx.t("round.abortLine", { id: round.round_id })];
  return confirmedButton(ctx, { label: ctx.t("round.abort"), title: ctx.t("round.abortTitle"), lines, tone: "danger", run });
}

// --- the published report ------------------------------------------------------------------------

// What the estimate says, in one line: the effect with its p value, or why there is none.
export function estimateText(ctx, estimate) {
  if (!estimate) return "—";
  if (!estimate.estimable) return estimate.note || ctx.t("report.notEstimable");
  const p = typeof estimate.p_value === "number" ? estimate.p_value.toPrecision(2) : "—";
  return ctx.t("report.estimate", { effect: estimate.effect, p, blocks: estimate.blocks });
}

function listOrNone(ctx, items) {
  const rows = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!rows.length) return note(ctx.t("report.none"));
  return h("ul", { class: "report-list" }, rows.map((item) => h("li", { text: String(item) })));
}

// A report written with coded notes shows each server note in the console's language; an older
// report has only the plain-text fields, which are shown as they are.
export function reportLists(report, lang) {
  if (!Array.isArray(report.notes)) {
    return { reasons: report.reasons || [], limitations: report.limitations || [] };
  }
  const text = (entry) => (entry.text && (entry.text[lang] || entry.text.en)) || entry.code;
  const of = (kind) => report.notes.filter((entry) => entry.kind === kind).map(text);
  return { reasons: of("reason"), limitations: [...(report.model_limitations || []), ...of("limitation")] };
}

function reportView(ctx, data) {
  const report = data.report || {};
  const lists = reportLists(report, ctx.lang);
  const label = report.label || data.label;
  const conclusion = report.conclusion || "uncertain";
  return h(
    "div",
    { class: "report" },
    keyValues([
      [ctx.t("report.label"), h("span", { class: ["pill", `pill-label-${label}`], text: labelOr(ctx.t, "report.labels", label) })],
      [ctx.t("report.conclusion"), labelOr(ctx.t, "report.conclusions", conclusion)],
      [ctx.t("report.estimateTitle"), estimateText(ctx, report.estimate)],
      [ctx.t("report.snapshot"), report.snapshot_id ? h("code", { text: report.snapshot_id }) : null],
      [ctx.t("report.digest"), h("code", { text: data.sha256 })],
    ]),
    h("h3", { class: "report-sub", text: ctx.t("report.reasons") }),
    listOrNone(ctx, lists.reasons),
    h("h3", { class: "report-sub", text: ctx.t("report.limitations") }),
    listOrNone(ctx, lists.limitations),
    h("h3", { class: "report-sub", text: ctx.t("report.unresolved") }),
    listOrNone(ctx, report.unresolved),
    h("h3", { class: "report-sub", text: ctx.t("report.nextRound") }),
    report.next_round ? h("p", { class: "report-text", text: report.next_round }) : note(ctx.t("report.none")),
  );
}

async function reportSection(ctx, round) {
  if (!round.report_artifact_id) return null;
  try {
    const data = await ctx.api.get(`/rounds/${encodeURIComponent(round.round_id)}/report`);
    return section(ctx.t("report.title"), reportView(ctx, data));
  } catch (error) {
    return section(ctx.t("report.title"), note(ctx.t("report.unavailable", { reason: errorLines(error, ctx.lang, ctx.t).join(" ") })));
  }
}

export async function render(ctx, params) {
  const round = await ctx.api.get(`/rounds/${encodeURIComponent(params.roundId)}`);
  ctx.setBreadcrumbs([
    { label: ctx.t("nav.projects"), href: hrefFor("projects") },
    { label: ctx.t("crumb.project", { id: round.project_id }), href: hrefFor("project", { projectId: round.project_id }) },
    { label: ctx.t("crumb.round", { id: round.round_id }) },
  ]);
  const [analysis, report] = await Promise.all([analysisSection(ctx, round), reportSection(ctx, round)]);
  const element = h(
    "div",
    { class: "page round" },
    pageHead(ctx.t("crumb.round", { id: round.round_id }), ctx.t("round.lead")),
    section(ctx.t("round.summary"), summary(ctx, round)),
    report,
    round.awaiting_choice ? choiceForm(ctx, round) : null,
    section(ctx.t("round.stages"), stagesView(ctx, round)),
    CLOSED.has(round.state) ? null : section(ctx.t("round.abortSection"), note(ctx.t("round.abortNote")), abortButton(ctx, round)),
    analysis,
  );
  return { element };
}
