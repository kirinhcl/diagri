// One round: its state, stages, the choice after a stop, abort, and the confirmatory analysis.
import { hrefFor } from "../router.js";
import { confirmAction } from "../ui/dialog.js";
import { h } from "../ui/dom.js";
import { simpleForm } from "../ui/forms.js";
import { afterWrite, confirmedButton, keyValues, note, pageHead, section } from "../ui/section.js";
import { statePill } from "../ui/status.js";
import { table } from "../ui/table.js";
import { analysisSection } from "./round-analysis.js";

const CHOICES = ["redo", "next", "verify", "abort"];

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

export async function render(ctx, params) {
  const round = await ctx.api.get(`/rounds/${encodeURIComponent(params.roundId)}`);
  ctx.setBreadcrumbs([
    { label: ctx.t("nav.projects"), href: hrefFor("projects") },
    { label: ctx.t("crumb.project", { id: round.project_id }), href: hrefFor("project", { projectId: round.project_id }) },
    { label: ctx.t("crumb.round", { id: round.round_id }) },
  ]);
  const analysis = await analysisSection(ctx, round);
  const element = h(
    "div",
    { class: "page round" },
    pageHead(ctx.t("crumb.round", { id: round.round_id }), ctx.t("round.lead")),
    section(ctx.t("round.summary"), summary(ctx, round)),
    round.awaiting_choice ? choiceForm(ctx, round) : null,
    section(ctx.t("round.stages"), stagesView(ctx, round)),
    section(ctx.t("round.abortSection"), note(ctx.t("round.abortNote")), abortButton(ctx, round)),
    analysis,
  );
  return { element };
}
