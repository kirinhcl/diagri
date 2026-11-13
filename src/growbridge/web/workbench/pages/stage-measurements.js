// Manual measurements of the stage's experiment: the list with its correction chain, and the form.
// Raw records are never edited; a correction is a new record that names the one it corrects.
import { h } from "../ui/dom.js";
import { simpleForm } from "../ui/forms.js";
import { note, timeText } from "../ui/section.js";
import { table } from "../ui/table.js";

// id -> {corrects, correctedBy}: both ends of every correction in the list.
export function correctionLinks(measurements) {
  const list = Array.isArray(measurements) ? measurements : [];
  const correctedBy = new Map(list.map((record) => [record.id, []]));
  for (const record of list) {
    if (record.corrects && correctedBy.has(record.corrects)) correctedBy.get(record.corrects).push(record.id);
  }
  return new Map(list.map((record) => [record.id, { corrects: record.corrects ?? null, correctedBy: correctedBy.get(record.id) }]));
}

function correctionCell(ctx, link) {
  if (!link) return "—";
  const parts = [];
  if (link.corrects) parts.push(h("span", { text: ctx.t("measure.correctsValue", { id: link.corrects }) }));
  if (link.correctedBy.length) {
    parts.push(h("span", { class: "pill pill-waiting", text: ctx.t("measure.correctedBy", { ids: link.correctedBy.join(", ") }) }));
  }
  return parts.length ? h("span", { class: "cell-stack" }, parts) : "—";
}

export function measurementTable(ctx, measurements) {
  const list = Array.isArray(measurements) ? measurements : [];
  if (!list.length) return note(ctx.t("measure.empty"));
  const links = correctionLinks(list);
  const columns = [
    { label: ctx.t("measure.measuredAt"), cell: (m) => timeText(ctx, m.measured_at) },
    { label: ctx.t("measure.plant"), cell: (m) => m.plant_id },
    { label: ctx.t("measure.batch"), cell: (m) => m.batch },
    { label: ctx.t("measure.position"), cell: (m) => m.position || "—" },
    { label: ctx.t("measure.metric"), cell: (m) => m.metric },
    { label: ctx.t("measure.value"), cell: (m) => `${m.value} ${m.unit}` },
    { label: ctx.t("measure.method"), cell: (m) => m.method },
    { label: ctx.t("measure.layout"), cell: (m) => m.layout_version },
    { label: ctx.t("measure.operator"), cell: (m) => m.operator },
    { label: ctx.t("col.id"), cell: (m) => h("code", { text: m.id }) },
    { label: ctx.t("measure.correction"), cell: (m) => correctionCell(ctx, links.get(m.id)) },
  ];
  return table(columns, list, { label: ctx.t("measure.list") });
}

function fields(ctx) {
  const text = (name, key, required = true) => ({ name, label: ctx.t(`measure.${key}`), required });
  return [
    { name: "measured_at", label: ctx.t("measure.measuredAt"), type: "datetime", required: true },
    text("plant_id", "plant"),
    text("batch", "batch"),
    text("layout_version", "layout"),
    text("position", "position", false),
    text("metric", "metric"),
    { name: "value", label: ctx.t("measure.value"), type: "number", required: true },
    text("unit", "unit"),
    text("method", "method"),
    text("corrects", "corrects", false),
  ];
}

// experiment_id comes from the stage; measured_at is wall time in the site's zone, shown beside it.
export function measurementForm(ctx, stage, onRecorded) {
  const submitLabel = ctx.t("measure.record");
  const onSubmit = async (values) => {
    const body = { position: "", ...values, experiment_id: stage.experiment_id };
    const answer = await ctx.api.post("/measurements", body, { action: submitLabel });
    await onRecorded(ctx.t("measure.recorded", { id: answer && answer.id }));
  };
  const timeZone = (ctx.me && ctx.me.timezone) || "UTC";
  const form = simpleForm({ fields: fields(ctx), submitLabel, onSubmit, draftKey: `measurement:${stage.experiment_id}`, timeZone, ctx });
  form.classList.add("form-columns");
  return h("div", { class: "measure-new" }, note(ctx.t("measure.lead", { id: stage.experiment_id })), form);
}
