// The forms of the evidence page: entering a card, verifying one, and the conditions rows a round's card shares.
import { labelOr } from "../i18n.js";
import { confirmOrCancel, simpleForm } from "../ui/forms.js";
import { rowGroup } from "../ui/field-forms.js";
import { afterWrite } from "../ui/section.js";
import { claimName, variableName } from "./evidence-text.js";

const SOURCE_CLASSES = ["handbook", "paper", "local"];
export const MAX_CONDITIONS = 8;
const CULTIVAR_CHARS = 200;
const STAGE_CHARS = 100;
const NOTE_CHARS = 500;

const yesNo = (ctx) => [
  { value: "yes", label: ctx.t("common.yes") },
  { value: "no", label: ctx.t("common.no") },
];

// The standard variables a card may name, as select options (the server lists only the pickable ones).
function variableOptions(ctx, variables) {
  const choose = { value: "", label: ctx.t("form.choose") };
  return [choose, ...variables.map((variable) => ({ value: variable.id, label: variableName(ctx, variables, variable.id) }))];
}

// The growth stage and the note on conditions: a card and a round's card both carry them.
export function contextFields(ctx) {
  return [
    { name: "growth_stage", label: ctx.t("evidence.growthStage"), type: "text", maxlength: STAGE_CHARS },
    { name: "conditions_note", label: ctx.t("evidence.conditionsNote"), type: "textarea", maxlength: NOTE_CHARS },
  ];
}

// Conditions the card holds under, one row each (a variable and its bounds), at most MAX_CONDITIONS.
export function conditionsPart(ctx, variables) {
  const fields = [
    { name: "variable", label: ctx.t("evidence.condVariable"), type: "select", required: true, options: variableOptions(ctx, variables) },
    { name: "min", label: ctx.t("evidence.condMin"), type: "number" },
    { name: "max", label: ctx.t("evidence.condMax"), type: "number" },
  ];
  const labels = { addLabel: ctx.t("evidence.addCondition"), removeLabel: ctx.t("evidence.removeCondition") };
  return rowGroup({ ctx, name: "conditions", label: ctx.t("evidence.conditions"), fields, maxRows: MAX_CONDITIONS, ...labels });
}

// Whether a card was calibrated is recorded as the operator's own choice: no answer is preset.
export function enterFields(ctx, variables = []) {
  const classes = SOURCE_CLASSES.map((value) => ({ value, label: labelOr(ctx.t, "evidence.class", value) }));
  const calibration = [{ value: "", label: ctx.t("form.choose") }, ...yesNo(ctx)];
  const [stage, note] = contextFields(ctx);
  return [
    { name: "source_class", label: ctx.t("evidence.sourceClass"), type: "select", required: true, options: classes },
    { name: "citation", label: ctx.t("evidence.citation"), type: "textarea", required: true },
    { name: "claim", label: ctx.t("evidence.claim"), type: "textarea", required: true },
    { name: "variable", label: ctx.t("evidence.variable"), type: "select", options: variableOptions(ctx, variables) },
    { name: "value", label: ctx.t("evidence.value"), type: "number" },
    { name: "unit", label: ctx.t("evidence.unit"), type: "text" },
    { name: "calibrated", label: ctx.t("evidence.calibrated"), type: "select", required: true, options: calibration },
    { name: "crop_taxon", label: ctx.t("evidence.cropTaxon"), type: "text" },
    { name: "cultivar", label: ctx.t("evidence.cultivar"), type: "text", maxlength: CULTIVAR_CHARS },
    stage,
    note,
  ];
}

export function enterForm(ctx, variables) {
  const submitLabel = ctx.t("evidence.enter");
  const onSubmit = async ({ calibrated, ...rest }) => {
    await confirmOrCancel(ctx, { title: ctx.t("evidence.enterTitle"), lines: [ctx.t("evidence.enterLine")], confirmLabel: submitLabel });
    const card = await ctx.api.post("/evidence", { ...rest, calibrated: calibrated === "yes" }, { action: submitLabel });
    afterWrite(ctx, ctx.t("evidence.entered", { claim: claimName(card?.claim ?? rest.claim) }));
  };
  const parts = [conditionsPart(ctx, variables)];
  return simpleForm({ fields: enterFields(ctx, variables), parts, submitLabel, onSubmit, draftKey: "evidence:new", ctx });
}

export function verifyForm(ctx, card) {
  const submitLabel = ctx.t("evidence.verify");
  const fields = [
    { name: "note", label: ctx.t("evidence.note"), type: "text" },
    { name: "calibrated", label: ctx.t("evidence.attest"), type: "checkbox" },
  ];
  const onSubmit = async ({ note: text, calibrated }) => {
    await confirmOrCancel(ctx, { title: ctx.t("evidence.verifyTitle"), lines: [ctx.t("evidence.verifyLine")], confirmLabel: submitLabel });
    const body = { note: text || "", calibrated: calibrated === true };
    await ctx.api.post(`/evidence/${encodeURIComponent(card.id)}/verify`, body, { action: submitLabel });
    afterWrite(ctx, ctx.t("evidence.verified", { claim: claimName(card.claim) }));
  };
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: `evidence-verify:${card.id}`, ctx });
}
