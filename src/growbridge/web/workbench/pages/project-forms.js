// The write forms of the project page: start a round, set the budget, save a protocol, register a holdout.
// Goals are set in the project conversation, not here. All but the first wait closed under "Edit…".
import { hasDraft } from "../drafts.js";
import { formatMoney, formatNumber } from "../format.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { advancedJson, linesField } from "../ui/field-forms.js";
import { simpleForm } from "../ui/forms.js";
import { afterWrite } from "../ui/section.js";
import { protocolForm } from "./protocol-form.js";

const MAX_HOLDOUT_ITEMS = 50; // the server's HoldoutIn limits
const MAX_HOLDOUT_CHARS = 100;

// A write form closed under "Edit…"; it opens by itself when it brings back a draft not yet sent.
function editFold(ctx, draftKey, build) {
  const open = hasDraft(draftKey);
  return h("details", { class: "edit-fold", attrs: { open } }, h("summary", { text: ctx.t("project.edit") }), build(draftKey));
}

// A minimal protocol that passes the server's checks (same shape as growbridge.sim.fixtures.make_protocol).
export function protocolExample(projectId, number) {
  return {
    id: `protocol-${number}-${projectId.slice(-6)}`, // protocol ids are shared by all projects, so the suggestion carries a project mark
    project_id: projectId,
    version: 1,
    question: "",
    hypothesis: "",
    crop: "lettuce",
    batch: "batch-1",
    treatments: [
      { id: "control", name: "light 40 %", factors: { light: 40 } },
      { id: "high", name: "light 70 %", factors: { light: 70 } },
    ],
    control_treatment_id: "control",
    allocations: [
      { round: 1, block: 1, unit: "tent-1", treatment_id: "high" },
      { round: 2, block: 1, unit: "tent-1", treatment_id: "control" },
      { round: 3, block: 2, unit: "tent-1", treatment_id: "control" },
      { round: 4, block: 2, unit: "tent-1", treatment_id: "high" },
    ],
    randomization_seed: 20261118,
    analysis: { primary_endpoint: "canopy_area_growth", target_effect: 0.15, method: "paired_block" },
    stages: ["vegetative"],
    rounds: 4,
    blocks: 2,
  };
}

// With no saved protocol the field is free text, so a refusal can still be tried and read.
export function startRoundForm(ctx, project) {
  const protocols = project.protocols || [];
  const label = ctx.t("project.protocol");
  const options = protocols.map((item) => ({ value: item.protocol_id, label: ctx.t("round.protocolValue", { id: item.protocol_id, v: item.version }) }));
  const field = protocols.length
    ? { name: "protocol_id", label, type: "select", options, required: true }
    : { name: "protocol_id", label, type: "text", required: true };
  const submitLabel = ctx.t("project.startRound");
  const onSubmit = async ({ protocol_id: protocolId }) => {
    const body = { project_id: project.project_id, protocol_id: protocolId };
    const made = await ctx.api.post("/rounds", body, { action: submitLabel });
    ctx.notify(ctx.t("project.roundStarted"), "ok");
    ctx.navigate(hrefFor("round", { roundId: made.round_id }));
  };
  return simpleForm({ fields: [field], submitLabel, onSubmit, draftKey: `round:${project.project_id}`, ctx });
}

export function budgetForm(ctx, project) {
  const submitLabel = ctx.t("project.budget.set");
  const fields = [
    { name: "max_calls", label: ctx.t("project.budget.maxCalls"), type: "number", step: 1, required: true },
    { name: "max_cost", label: ctx.t("project.budget.maxCost"), type: "number", required: true },
  ];
  const onSubmit = async (values) => {
    await ctx.api.post(`/projects/${encodeURIComponent(project.project_id)}/budget`, values, { action: submitLabel });
    const saved = { calls: formatNumber(values.max_calls, 0, ctx.lang), cost: formatMoney(values.max_cost, ctx.lang) };
    afterWrite(ctx, ctx.t("project.budget.saved", saved));
  };
  return editFold(ctx, `budget:${project.project_id}`, (draftKey) => simpleForm({ fields, submitLabel, onSubmit, draftKey, ctx }));
}

// The protocol as a form; the whole JSON stays under "Advanced (JSON)" with the old draft key, so an old JSON draft still comes back.
export function protocolEditor(ctx, project) {
  const submitLabel = ctx.t("project.protocols.save");
  const post = async (protocol) => {
    const saved = await ctx.api.post("/protocols", { protocol }, { action: submitLabel });
    afterWrite(ctx, ctx.t("project.protocols.saved", { id: saved.protocol_id, version: saved.version }));
  };
  const jsonKey = `protocol:${project.project_id}`;
  const open = hasDraft(jsonKey) || hasDraft(`${jsonKey}-form`);
  const value = protocolExample(project.project_id, (project.protocols || []).length + 1);
  const form = protocolForm(ctx, { project, onSubmit: ({ protocol }) => post(protocol) });
  const advanced = advancedJson({ ctx, label: ctx.t("project.protocols.json"), value, onSubmit: post, draftKey: jsonKey, submitLabel });
  return h("details", { class: "edit-fold", attrs: { open } }, h("summary", { text: ctx.t("project.edit") }), form, advanced);
}

// Three lists, one batch or field per line; the server takes 1 to 50 of each, up to 100 characters per line.
export function holdoutEditor(ctx, project) {
  const submitLabel = ctx.t("project.holdouts.register");
  const list = (name, label) => linesField({ name, label, required: true, maxItems: MAX_HOLDOUT_ITEMS, maxItemLength: MAX_HOLDOUT_CHARS, hint: ctx.t("holdout.form.lineHint") });
  const fields = [
    list("batch_ids", ctx.t("project.holdouts.batches")),
    list("development_batch_ids", ctx.t("project.holdouts.development")),
    list("outcome_fields", ctx.t("project.holdouts.fields")),
  ];
  const onSubmit = async (values) => {
    await ctx.api.post("/holdouts", { project_id: project.project_id, ...values }, { action: submitLabel });
    afterWrite(ctx, ctx.t("project.holdouts.saved"));
  };
  return editFold(ctx, `holdout:${project.project_id}-form`, (draftKey) => [
    h("p", { class: "note", text: ctx.t("holdout.form.hint") }),
    simpleForm({ fields, submitLabel, onSubmit, draftKey, ctx }),
  ]);
}
