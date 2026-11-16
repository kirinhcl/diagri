// Manual measurements of the stage's experiment: the list with its correction chain, and the form.
// Raw records are never edited; a correction is a new record that names the one it corrects.
import { h } from "../ui/dom.js";
import { formControls, simpleForm } from "../ui/forms.js";
import { note, techDetails, timeText } from "../ui/section.js";
import { table } from "../ui/table.js";

const SUGGESTED = ["metric", "unit", "method"];
// What Correct copies from a record into the form; `corrects` is then set to the record's id.
const COPIED = ["measured_at", "plant_id", "batch", "layout_version", "position", "metric", "value", "unit", "method"];

// id -> {corrects, correctedBy}: both ends of every correction in the list.
export function correctionLinks(measurements) {
  const list = Array.isArray(measurements) ? measurements : [];
  const correctedBy = new Map(list.map((record) => [record.id, []]));
  for (const record of list) {
    if (record.corrects && correctedBy.has(record.corrects)) correctedBy.get(record.corrects).push(record.id);
  }
  return new Map(list.map((record) => [record.id, { corrects: record.corrects ?? null, correctedBy: correctedBy.get(record.id) }]));
}

// The distinct metric, unit and method names already recorded, sorted: what the form suggests.
export function measurementOptions(measurements) {
  const list = Array.isArray(measurements) ? measurements : [];
  const distinct = (name) => [...new Set(list.map((record) => record && record[name]).filter((value) => typeof value === "string" && value !== ""))].sort();
  return Object.fromEntries(SUGGESTED.map((name) => [name, distinct(name)]));
}

// Batch, position, layout, the record's id and both ends of its corrections, told by time.
function rowDetails(ctx, record, link, byId) {
  const timeOf = (id) => timeText(ctx, byId.get(id).measured_at);
  const corrected = link.corrects && byId.has(link.corrects) ? ctx.t("measure.correctsValue", { time: timeOf(link.corrects) }) : null;
  return techDetails(ctx.t, [
    [ctx.t("measure.batch"), record.batch],
    [ctx.t("measure.position"), record.position],
    [ctx.t("measure.layout"), record.layout_version],
    [ctx.t("tech.recordId"), record.id],
    [ctx.t("measure.correction"), corrected],
    [ctx.t("measure.correctsId"), link.corrects],
    ...link.correctedBy.map((id) => [ctx.t("measure.correction"), ctx.t("measure.correctedBy", { time: timeOf(id) })]),
    ...link.correctedBy.map((id) => [ctx.t("measure.correctedById"), id]),
  ]);
}

function valueCell(ctx, record, link) {
  const value = `${record.value} ${record.unit}`;
  if (!link.correctedBy.length) return value;
  return h("span", { class: "cell-stack" }, value, h("span", { class: "pill pill-waiting", text: ctx.t("measure.superseded") }));
}

// Who recorded it, then Correct (not for a record already corrected) and the row's details.
function recordCell(ctx, record, link, tools) {
  const { byId, onCorrect } = tools;
  const button = onCorrect && !link.correctedBy.length ? h("button", { class: "button button-quiet", attrs: { type: "button" }, text: ctx.t("measure.correct") }) : null;
  if (button) button.addEventListener("click", () => onCorrect(record));
  return h("div", { class: "measure-record" }, h("span", { text: record.operator }), button, rowDetails(ctx, record, link, byId));
}

export function measurementTable(ctx, measurements, { onCorrect } = {}) {
  const list = Array.isArray(measurements) ? measurements : [];
  if (!list.length) return note(ctx.t("measure.empty"));
  const links = correctionLinks(list);
  const tools = { byId: new Map(list.map((record) => [record.id, record])), onCorrect };
  const columns = [
    { label: ctx.t("measure.measuredAt"), cell: (m) => timeText(ctx, m.measured_at) },
    { label: ctx.t("measure.plant"), cell: (m) => m.plant_id },
    { label: ctx.t("measure.metric"), cell: (m) => m.metric },
    { label: ctx.t("measure.value"), cell: (m) => valueCell(ctx, m, links.get(m.id)) },
    { label: ctx.t("measure.method"), cell: (m) => m.method },
    { label: ctx.t("measure.operator"), cell: (m) => recordCell(ctx, m, links.get(m.id), tools) },
  ];
  return table(columns, list, { label: ctx.t("measure.list") });
}

// The list, with Correct wired to the form; the form's suggestions follow what was recorded.
export function measurementsView(ctx, measurements, form) {
  form.update(measurements);
  return measurementTable(ctx, measurements, { onCorrect: form.correct });
}

function fields(ctx) {
  const text = (name, key, required = true) => ({ name, label: ctx.t(`measure.${key}`), required });
  const suggested = (name) => ({ ...text(name, name), suggestions: [] });
  return [
    { name: "measured_at", label: ctx.t("measure.measuredAt"), type: "datetime", required: true },
    text("plant_id", "plant"),
    text("batch", "batch"),
    text("layout_version", "layout"),
    text("position", "position", false),
    suggested("metric"),
    { name: "value", label: ctx.t("measure.value"), type: "number", required: true },
    suggested("unit"),
    suggested("method"),
    { name: "corrects", type: "hidden", label: ctx.t("measure.correctedRecord") },
  ];
}

// The line saying which record the next save corrects, with a way out; hidden while it corrects none.
function correctingLine(ctx) {
  const said = h("span");
  const cancel = h("button", { class: "button button-quiet", attrs: { type: "button" }, text: ctx.t("measure.cancelCorrect") });
  const element = h("p", { class: "measure-correcting", attrs: { role: "status", hidden: true } }, said, cancel);
  const show = (id, recorded) => {
    element.hidden = !id;
    const record = id ? recorded.find((item) => item.id === id) : null;
    if (!id) said.textContent = "";
    else if (record) said.textContent = ctx.t("measure.correcting", { time: timeText(ctx, record.measured_at), metric: record.metric });
    else said.textContent = ctx.t("measure.correctingUnknown");
  };
  return { element, cancel, show };
}

// experiment_id comes from the stage; measured_at is wall time in the site's zone, shown beside it.
// Returns the form with correct(record), which fills it in to correct that record, and
// update(measurements), which the list calls with what was recorded.
export function measurementForm(ctx, stage, onRecorded) {
  const submitLabel = ctx.t("measure.record");
  const line = correctingLine(ctx);
  let recorded = [];
  let controls = null;
  let copied = null; // the corrected record's time: its epoch and the minute the field showed for it
  const showCorrecting = () => line.show(controls.get("corrects"), recorded);
  const stopCorrecting = () => {
    controls.set({ corrects: null });
    copied = null;
    showCorrecting();
  };
  // The field holds minutes only: an untouched copied time keeps the record's own seconds.
  const measuredAt = (values) => {
    const untouched = copied && values.corrects === copied.id && controls.get("measured_at") === copied.text;
    return untouched ? copied.epoch : values.measured_at;
  };
  const onSubmit = async (values) => {
    const body = { position: "", ...values, measured_at: measuredAt(values), experiment_id: stage.experiment_id };
    await ctx.api.post("/measurements", body, { action: submitLabel });
    stopCorrecting();
    await onRecorded(ctx.t("measure.recorded", { metric: values.metric, plant: values.plant_id }));
  };
  const timeZone = (ctx.me && ctx.me.timezone) || "UTC";
  const form = simpleForm({ fields: fields(ctx), submitLabel, onSubmit, draftKey: `measurement:${stage.experiment_id}`, timeZone, ctx });
  form.classList.add("form-columns");
  controls = formControls(form);
  line.cancel.addEventListener("click", stopCorrecting);
  showCorrecting(); // a draft restored after a lost session may already correct a record
  const correct = (record) => {
    controls.set({ ...Object.fromEntries(COPIED.map((name) => [name, record[name]])), corrects: record.id });
    copied = { id: record.id, epoch: record.measured_at, text: controls.get("measured_at") };
    showCorrecting();
    controls.focus("value");
  };
  const update = (measurements) => {
    recorded = Array.isArray(measurements) ? measurements : [];
    for (const [name, values] of Object.entries(measurementOptions(recorded))) controls.suggest(name, values);
    showCorrecting();
  };
  return { element: h("div", { class: "measure-new" }, note(ctx.t("measure.lead")), line.element, form), correct, update };
}
