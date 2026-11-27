// The cards of the six answer steps of the guide (question, crop, treatments, measures, analysis, scale).
// Each card sends exactly what the choose route takes: {answer, option_ids}. Options come from the
// server's lists; nothing is invented here, and a step reopened shows the answer given before.
import { ApiError } from "../api.js";
import { textOr } from "../i18n.js";
import { h } from "../ui/dom.js";
import { linesField, rowGroup } from "../ui/field-forms.js";
import { convert, fieldRow, initialText, setFieldError } from "../ui/forms.js";
import { errorBox, note, section, showErrors, techDetails } from "../ui/section.js";
import { findingsList } from "./stage-actions.js";

const OTHER = "__other__";
const NCBI_TAXONOMY = "https://www.ncbi.nlm.nih.gov/taxonomy";
const PILOT_BLOCKS = 2;
const MIN_COUNT = 1;
const array = (value) => (Array.isArray(value) ? value : []);
const enc = encodeURIComponent;
let counter = 0;

// --- small pieces ------------------------------------------------------------------------------------

const zoneOf = (ctx) => (ctx.me && ctx.me.timezone) || "UTC";
const labelOf = (ctx, option) => (ctx.lang === "zh" ? option.label_zh : option.label_en) || option.label_en || option.label_zh || "";
const chosenOf = (session, step) => (array(session.steps).find((entry) => entry.step === step) || {}).chosen || null;
const answerOf = (session, step) => (chosenOf(session, step) || {}).answer || {};
const trimmed = (text, t) => (text.trim() ? { value: text.trim() } : { error: t("form.required") });

// The fields of `answer` named by `keys` that hold something; what a reopened step carries over unseen.
function carried(answer, keys) {
  const has = (key) => answer && answer[key] !== undefined && answer[key] !== null && answer[key] !== "";
  return Object.fromEntries(keys.filter(has).map((key) => [key, answer[key]]));
}

function refuse(box, message) {
  box.replaceChildren(h("p", { text: message }));
  box.hidden = false;
}

// Plain fields as rows; read() gives the converted values, or null with the errors shown beside the fields.
function fieldSet(ctx, specs, values = {}) {
  const zone = zoneOf(ctx);
  const entries = specs.map((spec) => {
    const value = values[spec.name] ?? spec.value;
    return fieldRow(spec, initialText({ ...spec, value }, zone, ctx.lang), zone);
  });
  const entry = (name) => entries.find((candidate) => candidate.field.name === name);
  return { rows: entries.map((item) => item.row), read: (only = entries) => convert(only, zone, ctx.t), entry };
}

// Radios or check boxes sharing one name; chosen() lists the ticked ids in the order of `items`.
function choiceGroup({ name, legend, kind = "radio", items, selected = [], onChange }) {
  const boxes = items.map((item) => {
    const input = h("input", { class: "input-check", attrs: { type: kind, name, value: item.id, checked: selected.includes(item.id) } });
    if (onChange) input.addEventListener("change", onChange);
    const hint = item.hint ? h("span", { class: "field-hint", text: item.hint }) : null;
    return { item, input, label: h("label", { class: "guide-choice" }, input, h("span", { text: item.label }), hint) };
  });
  const element = h("fieldset", { class: "field-group guide-choices" }, h("legend", { text: legend }), boxes.map((box) => box.label));
  const chosen = () => boxes.filter((box) => box.input.checked).map((box) => box.item.id);
  return { element, chosen };
}

// A drop-down whose choices change with other answers; the person's pick is kept while it stays offered.
function selectField(ctx, { name, label, picked = "" }) {
  counter += 1;
  const id = `guide-${name}-${counter}`;
  let wanted = picked;
  const select = h("select", { class: "input", attrs: { id, name } });
  select.addEventListener("change", () => {
    wanted = select.value;
  });
  const error = h("p", { class: "field-error", attrs: { hidden: true } });
  const option = (value, text, on) => h("option", { attrs: { value, selected: on }, text });
  const refresh = (choices) => {
    const keep = choices.some((choice) => choice.value === wanted) ? wanted : "";
    select.replaceChildren(option("", ctx.t("form.choose"), keep === ""), ...choices.map((choice) => option(choice.value, choice.label, choice.value === keep)));
    select.value = keep;
  };
  const fail = (message) => {
    error.textContent = message || "";
    error.hidden = !message;
  };
  const control = h("div", { class: "field-control" }, select);
  const row = h("div", { class: "field" }, h("label", { class: "field-label", attrs: { for: id }, text: label }), control, error);
  return { row, refresh, fail, value: () => select.value };
}

// A whole number of one or more (blocks, rounds).
const wholeFromOne = (text, t) => {
  const number = Number(text);
  return Number.isSafeInteger(number) && number >= MIN_COUNT ? { value: number } : { error: t("guide.scale.whole") };
};

// --- question ----------------------------------------------------------------------------------------

function questionBody(ctx, { session, post }) {
  const specs = [
    { name: "question", label: ctx.t("guide.question.question"), type: "textarea", required: true, parse: trimmed },
    { name: "hypothesis", label: ctx.t("guide.question.hypothesis"), type: "textarea" },
  ];
  const fields = fieldSet(ctx, specs, answerOf(session, "question"));
  const submit = async () => {
    const values = fields.read();
    if (values) await post({ hypothesis: "", ...values }, []);
  };
  return { content: fields.rows, submit };
}

// --- crop --------------------------------------------------------------------------------------------

// What a reopened crop step starts with: the listed crop it was, or the typed species.
function cropStart(prev, options) {
  if (!prev) return { selected: [], name: "", taxon: "" };
  const answer = prev.answer || {};
  const ids = array(prev.option_ids);
  const hit = options.find((o) => ids.includes(o.id)) || options.find((o) => o.value && o.value.crop_taxon === answer.crop_taxon);
  if (hit) return { selected: [hit.id], name: "", taxon: "" };
  return { selected: [OTHER], name: answer.crop || "", taxon: answer.crop_taxon || "" };
}

function cropBody(ctx, { session, options, post, box }) {
  const prev = chosenOf(session, "crop");
  const start = cropStart(prev, options);
  const items = [...options.map((o) => ({ id: o.id, label: labelOf(ctx, o) })), { id: OTHER, label: ctx.t("guide.crop.other") }];
  const specs = [
    { name: "crop_name", label: ctx.t("guide.crop.name"), required: true },
    { name: "crop_taxon", label: ctx.t("guide.crop.taxon"), hint: ctx.t("guide.crop.taxonHint"), required: true },
  ];
  const own = fieldSet(ctx, specs, { crop_name: start.name, crop_taxon: start.taxon });
  const link = h("a", { class: "guide-lookup", attrs: { href: NCBI_TAXONOMY, target: "_blank", rel: "noopener noreferrer" }, text: ctx.t("guide.crop.lookup") });
  const typed = h("div", { class: "guide-own" }, own.rows, link);
  const sync = () => typed.toggleAttribute("hidden", group.chosen()[0] !== OTHER);
  const group = choiceGroup({ name: "crop", legend: ctx.t("guide.step.crop"), items, selected: start.selected, onChange: sync });
  sync();
  // Typed beside the choice and part of the same answer, so they are always on the card.
  const moreSpecs = [
    { name: "cultivar", label: ctx.t("guide.crop.cultivar") },
    { name: "batch", label: ctx.t("guide.crop.batch") },
  ];
  const more = fieldSet(ctx, moreSpecs, carried(prev && prev.answer, ["cultivar", "batch"]));
  const submit = async () => {
    const [picked] = group.chosen();
    if (!picked) return refuse(box, ctx.t("guide.crop.choose"));
    const extras = more.read();
    if (!extras) return null;
    if (picked !== OTHER) return post({ ...options.find((o) => o.id === picked).value, ...extras }, [picked]);
    const values = own.read();
    return values ? post({ crop: values.crop_name, crop_taxon: values.crop_taxon, ...extras }, []) : null;
  };
  return { content: [group.element, typed, ...more.rows], submit };
}

// --- treatments --------------------------------------------------------------------------------------

function inputsNamed(root, name, found = []) {
  if (root.getAttribute && root.getAttribute("name") === name) found.push(root);
  for (const child of root.children || []) inputsNamed(child, name, found);
  return found;
}

function duplicateIds(ctx) {
  return (rows) => {
    const seen = new Set();
    return rows.flatMap((row, index) => {
      if (!seen.has(row.id)) {
        seen.add(row.id);
        return [];
      }
      return [{ row: index, field: "id", error: ctx.t("guide.treatments.idTwice") }];
    });
  };
}

function treatmentRowFields(ctx) {
  return [
    { name: "id", label: ctx.t("guide.treatments.id"), required: true, parse: trimmed },
    { name: "name", label: ctx.t("guide.treatments.name"), required: true, parse: trimmed },
    { name: "level", label: ctx.t("guide.treatments.level"), type: "number", required: true },
    { name: "description", label: ctx.t("guide.treatments.description") },
  ];
}

function factorItems(ctx, options) {
  return options.map((o) => {
    const unit = o.value && o.value.unit;
    return { id: o.id, label: unit ? `${labelOf(ctx, o)} (${unit})` : labelOf(ctx, o) };
  });
}

// The factors of a carried treatment other than the one being edited: kept as they were, shown read-only.
const otherFactors = (row, picked) => Object.fromEntries(Object.entries(row.factors || {}).filter(([key]) => key !== picked));

function keptFactors(ctx, { options, rowsBefore, picked }) {
  const holder = h("div", { class: "guide-kept-factors" });
  const nameOf = (key) => {
    const found = options.find((o) => o.id === key);
    return found ? labelOf(ctx, found) : key;
  };
  const redraw = () => {
    const lines = rowsBefore
      .map((row) => [row.name, Object.entries(otherFactors(row, picked())).map(([key, value]) => `${nameOf(key)} ${value}`)])
      .filter(([, parts]) => parts.length > 0)
      .map(([name, parts]) => h("li", { text: `${name}: ${parts.join(ctx.t("common.listSep"))}` }));
    holder.replaceChildren(...(lines.length ? [note(ctx.t("guide.treatments.others")), h("ul", { class: "guide-kept-list" }, lines)] : []));
  };
  redraw();
  return { element: holder, redraw };
}

function treatmentsBody(ctx, { session, options, post, box }) {
  const before = answerOf(session, "treatments");
  const rowsBefore = array(before.treatments);
  const factorKey = Object.keys((rowsBefore[0] && rowsBefore[0].factors) || {})[0];
  let kept = null;
  const onFactor = () => kept && kept.redraw();
  const factor = choiceGroup({ name: "factor", legend: ctx.t("guide.treatments.factor"), items: factorItems(ctx, options), selected: factorKey ? [factorKey] : [], onChange: onFactor });
  kept = keptFactors(ctx, { options, rowsBefore, picked: () => factor.chosen()[0] || factorKey });
  const control = selectField(ctx, { name: "control", label: ctx.t("guide.treatments.control"), picked: before.control_treatment_id || "" });
  let group = null;
  const refreshControl = () => {
    if (!group) return;
    const ids = inputsNamed(group.element, "id").map((input) => input.value.trim()).filter(Boolean);
    control.refresh([...new Set(ids)].map((id) => ({ value: id, label: id })));
  };
  group = rowGroup({
    ctx,
    name: "rows",
    label: ctx.t("guide.treatments.rows"),
    fields: treatmentRowFields(ctx),
    rows: rowsBefore.map((row) => ({ id: row.id, name: row.name, level: (row.factors || {})[factorKey], description: row.description || "" })),
    addLabel: ctx.t("guide.treatments.add"),
    removeLabel: ctx.t("guide.treatments.remove"),
    minRows: 2,
    crossCheck: duplicateIds(ctx),
    onChange: refreshControl,
  });
  group.element.addEventListener("input", refreshControl);
  refreshControl();
  const submit = async () => {
    const found = group.rows();
    const [picked] = factor.chosen();
    if (!picked) return refuse(box, ctx.t("guide.treatments.noFactor"));
    refreshControl();
    control.fail("");
    if (!found) return null;
    if (!control.value()) return control.fail(ctx.t("guide.treatments.noControl"));
    const prior = new Map(rowsBefore.map((row) => [row.id, row]));
    const treatments = found.map((row) => ({ id: row.id, name: row.name, description: row.description ?? "", factors: { ...otherFactors(prior.get(row.id) || {}, picked), [picked]: row.level } }));
    return post({ treatments, control_treatment_id: control.value() }, [picked]);
  };
  return { content: [factor.element, group.element, kept.element, control.row], submit };
}

// --- measures ----------------------------------------------------------------------------------------

function measuresBody(ctx, { session, options, post, box }) {
  const before = answerOf(session, "measures");
  const manual = new Set(options.filter((o) => o.value && o.value.kind === "manual").map((o) => o.id));
  const endpoint = selectField(ctx, { name: "endpoint", label: ctx.t("guide.measures.endpoint"), picked: before.primary_endpoint || "" });
  let group = null;
  const refreshEndpoint = () => {
    if (!group) return;
    const ticked = group.chosen();
    const offered = options.filter((o) => manual.has(o.id) && ticked.includes(o.id)).map((o) => ({ value: o.id, label: labelOf(ctx, o) }));
    const keptEndpoint = gone.filter((id) => ticked.includes(id) && id === before.primary_endpoint).map((id) => ({ value: id, label: id }));
    endpoint.refresh([...offered, ...keptEndpoint]);
  };
  // Variables chosen before that the catalog no longer offers stay on the card, ticked, until the person unticks them.
  const offeredIds = new Set(options.map((o) => o.id));
  const gone = array(before.variables).filter((id) => !offeredIds.has(id));
  const goneNote = ctx.t("guide.measures.gone");
  const items = [...options.map((o) => ({ id: o.id, label: labelOf(ctx, o) })), ...gone.map((id) => ({ id, label: id, hint: goneNote }))];
  group = choiceGroup({ name: "variable", legend: ctx.t("guide.measures.variables"), kind: "checkbox", items, selected: array(before.variables), onChange: refreshEndpoint });
  refreshEndpoint();
  const submit = async () => {
    const variables = group.chosen();
    endpoint.fail("");
    if (variables.length === 0) return refuse(box, ctx.t("guide.measures.noneChosen"));
    if (!endpoint.value()) return endpoint.fail(ctx.t("guide.measures.noEndpoint"));
    return post({ variables, primary_endpoint: endpoint.value() }, variables.filter((id) => offeredIds.has(id)));
  };
  return { content: [group.element, endpoint.row], submit };
}

// --- analysis ----------------------------------------------------------------------------------------

function analysisFields(ctx) {
  const fraction = (name, label) => ({ name, label, type: "number", required: true, min: 0, max: 1 });
  return [
    { name: "target_effect", label: ctx.t("guide.analysis.effect"), hint: ctx.t("guide.analysis.effectHint"), type: "number", required: true },
    linesField({ name: "exclusion_rules", label: ctx.t("guide.analysis.exclusions"), hint: ctx.t("guide.analysis.exclusionsHint") }),
    fraction("max_missing_fraction", ctx.t("guide.analysis.missing")),
    fraction("max_deviation_fraction", ctx.t("guide.analysis.deviation")),
  ];
}

function analysisBody(ctx, { session, options, defaults, post, box }) {
  const before = answerOf(session, "analysis");
  const items = options.map((o) => ({ id: o.id, label: labelOf(ctx, o), hint: textOr(ctx.t, "guide.method", o.id) || undefined }));
  const method = choiceGroup({ name: "method", legend: ctx.t("guide.analysis.method"), items, selected: before.method ? [before.method] : [] });
  const start = { max_missing_fraction: defaults.max_missing_fraction, max_deviation_fraction: defaults.max_deviation_fraction, ...before };
  const fields = fieldSet(ctx, analysisFields(ctx), start);
  const submit = async () => {
    const [picked] = method.chosen();
    const values = fields.read();
    if (!picked) return refuse(box, ctx.t("guide.analysis.noMethod"));
    return values ? post({ exclusion_rules: [], ...values, method: picked, ...carried(before, ["script_sha256"]) }, [picked]) : null;
  };
  return { content: [method.element, ...fields.rows, carriedHash(ctx, before.script_sha256)], submit };
}

// A script hash an earlier version declared goes back with the answer; it is shown, never edited here.
function carriedHash(ctx, hash) {
  if (!hash) return null;
  return h("div", { class: "guide-analysis-hash" }, note(ctx.t("guide.analysis.hash")), techDetails(ctx.t, [[ctx.t("analysis.sha"), hash]]));
}

// --- scale -------------------------------------------------------------------------------------------

function scaleFields(ctx) {
  const count = (name, label) => ({ name, label, type: "number", step: 1, required: true, parse: wholeFromOne });
  return [
    count("blocks", ctx.t("guide.scale.blocks")),
    count("rounds", ctx.t("guide.scale.rounds")),
    linesField({ name: "units", label: ctx.t("guide.scale.units"), hint: ctx.t("guide.scale.unitsHint"), required: true }),
    linesField({ name: "stages", label: ctx.t("guide.scale.stages"), hint: ctx.t("guide.scale.stagesHint"), required: true }),
  ];
}

// The standard deviation field and the two buttons that fill the number of blocks (or rounds).
function helper(ctx, { session, box, activeCount, changed }) {
  const spread = fieldSet(ctx, [{ name: "sd", label: ctx.t("guide.scale.sd"), hint: ctx.t("guide.scale.sdHint"), type: "number" }]);
  const analysis = answerOf(session, "analysis");
  const known = analysis.target_effect !== undefined && Boolean(analysis.method);
  const pilot = h("div", { class: "guide-pilot" });
  const fill = (n) => {
    activeCount().input.value = String(n);
    changed();
  };
  const button = (cls, text, click) => h("button", { class: ["button", cls], attrs: { type: "button", disabled: cls === "guide-estimate" && !known }, text, on: { click } });
  const estimate = async () => {
    const entry = spread.entry("sd");
    const typed = entry.input.value;
    setFieldError(entry, "");
    box.hidden = true;
    if (!(Number(typed) > 0)) return setFieldError(entry, ctx.t(typed === "" ? "form.required" : "form.badNumber"));
    pilot.replaceChildren();
    try {
      const found = await ctx.api.get(`/guide/sample-size?effect=${enc(analysis.target_effect)}&sd=${enc(Number(typed))}&design=${enc(analysis.method)}`);
      // An estimate above the guide's limit is left out of the field: it usually means two units were mixed.
      if (found && found.over_limit === true) pilot.replaceChildren(note(ctx.t("guide.scale.overLimit")));
      else if (Number.isSafeInteger(found && found.n)) fill(found.n);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      showErrors(box, error, ctx);
    }
    return null;
  };
  const dontKnow = () => {
    fill(PILOT_BLOCKS);
    pilot.replaceChildren(note(ctx.t("guide.scale.pilot")));
  };
  return h("div", { class: "guide-helper" }, ...spread.rows, button("guide-estimate", ctx.t("guide.scale.estimate"), estimate), button("guide-unknown", ctx.t("guide.scale.dontKnow"), dontKnow), pilot);
}

function seedRow(ctx, seed) {
  counter += 1;
  const id = `guide-seed-${counter}`;
  const input = h("input", { class: "input guide-seed", attrs: { id, type: "text", readonly: true, value: String(seed) } });
  return h("div", { class: "field" }, h("label", { class: "field-label", attrs: { for: id }, text: ctx.t("guide.scale.seed") }), h("div", { class: "field-control" }, input), h("p", { class: "field-hint", text: ctx.t("guide.scale.seedHint") }));
}

// After a scale is saved the design is read once; findings that block it keep the person on this step.
async function checkDesign(ctx, { base, extra, box, done, view }) {
  let blocking = [];
  try {
    const review = await ctx.api.get(`${base}/review`);
    blocking = array(review && review.design).filter((finding) => finding && finding.blocking === true);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    showErrors(box, error, ctx);
    return done(view, { stay: true });
  }
  if (blocking.length === 0) return done(view);
  extra.replaceChildren(note(ctx.t("guide.scale.blocking")), findingsList(ctx, blocking));
  return done(view, { stay: true });
}

// The treatments a carried scale was made for are still the ones chosen: the table's own treatments when it
// carries one, otherwise no treatments chosen since the scale.
function sameTreatments(session, before) {
  const ids = array(answerOf(session, "treatments").treatments).map((row) => row.id);
  const table = array(before.allocations);
  if (table.length > 0) {
    const used = new Set(table.map((row) => row.treatment_id));
    return used.size === ids.length && ids.every((id) => used.has(id));
  }
  const seq = (step) => (chosenOf(session, step) || {}).seq;
  return seq("treatments") < seq("scale");
}

// Nothing a carried scale was made for has changed: layout, units, the number of blocks or rounds, and the
// treatments. Only then do the carried values the card does not ask for go back: the other count and a
// hand-written table. Otherwise the server makes them again, the allocation from the seed.
function scaleUnchanged(session, before, layout, values) {
  if (before.layout !== layout) return false;
  const count = layout === "series" ? "blocks" : "rounds";
  return JSON.stringify(values.units) === JSON.stringify(before.units) && values[count] === before[count] && sameTreatments(session, before);
}

const tableStillFits = (session, before, layout, values) => array(before.allocations).length > 0 && scaleUnchanged(session, before, layout, values);

const linesOf = (text) => String(text || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);

// Says, as the person edits, whether a carried hand-written table goes back as it is or is made again from the seed.
function tableNote(ctx, { session, before, current }) {
  const element = h("div", { class: "guide-table-note" });
  const redraw = () => {
    if (array(before.allocations).length === 0) return;
    const { layout, values } = current();
    const key = tableStillFits(session, before, layout, values) ? "guide.scale.tableKept" : "guide.scale.tableRedrawn";
    element.replaceChildren(note(ctx.t(key)));
  };
  redraw();
  return { element, redraw };
}

function scaleBody(ctx, { session, options, defaults, post, box, extra, base, done }) {
  const before = answerOf(session, "scale");
  const layouts = options.map((o) => ({ id: o.id, label: labelOf(ctx, o) }));
  const first = before.layout || (layouts[0] && layouts[0].id);
  const fields = fieldSet(ctx, scaleFields(ctx), before);
  const isSeries = () => layout.chosen()[0] !== "tents";
  const activeCount = () => fields.entry(isSeries() ? "blocks" : "rounds");
  let table = null;
  const sync = () => {
    fields.entry("blocks").row.toggleAttribute("hidden", !isSeries());
    fields.entry("rounds").row.toggleAttribute("hidden", isSeries());
    if (table) table.redraw();
  };
  const layout = choiceGroup({ name: "layout", legend: ctx.t("guide.scale.layout"), items: layouts, selected: first ? [first] : [], onChange: sync });
  const current = () => ({ layout: layout.chosen()[0], values: { units: linesOf(fields.entry("units").input.value), [isSeries() ? "blocks" : "rounds"]: Number(activeCount().input.value) } });
  table = tableNote(ctx, { session, before, current });
  for (const name of ["blocks", "rounds", "units"]) for (const kind of ["input", "change"]) fields.entry(name).input.addEventListener(kind, table.redraw);
  sync();
  const seed = before.randomization_seed ?? defaults.randomization_seed;
  const submit = async () => {
    const [picked] = layout.chosen();
    const values = fields.read([activeCount(), fields.entry("units"), fields.entry("stages")]);
    if (!picked || !values) return;
    const unit = before.experimental_unit || defaults.experimental_unit || "tent";
    const other = picked === "tents" ? "blocks" : "rounds";
    const kept = { ...carried(before, ["randomization_seed"]), ...(scaleUnchanged(session, before, picked, values) ? carried(before, [other, "allocations"]) : {}) };
    const view = await post({ layout: picked, ...values, experimental_unit: unit, ...kept }, [picked], { keepStep: true });
    await checkDesign(ctx, { base, extra, box, done, view });
  };
  const count = [fields.entry("blocks").row, fields.entry("rounds").row];
  const rest = [fields.entry("units").row, fields.entry("stages").row, seed === undefined ? null : seedRow(ctx, seed), table.element];
  return { content: [layout.element, ...count, helper(ctx, { session, box, activeCount, changed: table.redraw }), ...rest], submit };
}

// --- the card ----------------------------------------------------------------------------------------

const LEAD_KEYS = Object.fromEntries(["question", "crop", "treatments", "measures", "analysis", "scale"].map((step) => [step, `guide.${step}.lead`]));
const BODIES = { question: questionBody, crop: cropBody, treatments: treatmentsBody, measures: measuresBody, analysis: analysisBody, scale: scaleBody };

// The card of one answer step. `onChosen(view, { stay })` is told the new session view once the answer is
// saved; `stay` is set when the person has to look at something on this step first.
export function stepCard(ctx, { session, step, options, onChosen }) {
  const base = `/guide/sessions/${enc(session.session.session_id)}`;
  const box = errorBox();
  const extra = h("div", { class: "guide-extra" });
  const title = ctx.t(`guide.step.${step}`);
  const post = async (answer, optionIds, { keepStep = false } = {}) => {
    const view = await ctx.api.post(`${base}/steps/${step}/choose`, { answer, option_ids: optionIds }, { action: title });
    if (!keepStep) onChosen(view);
    return view;
  };
  const known = options || {};
  const built = BODIES[step](ctx, { session, options: array(known.options), defaults: known.defaults || {}, post, box, extra, base, done: onChosen });
  const button = h("button", { class: "button button-primary", attrs: { type: "submit" }, text: ctx.t("guide.save") });
  const form = h("form", { class: "form guide-form", attrs: { novalidate: true } }, built.content, box, extra, button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    box.hidden = true;
    extra.replaceChildren();
    button.disabled = true;
    try {
      await built.submit();
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      showErrors(box, error, ctx);
    } finally {
      button.disabled = false;
    }
  });
  const status = (array(session.steps).find((entry) => entry.step === step) || {}).status;
  const recheck = status === "needs_review" ? h("p", { class: "guide-recheck form-status form-status-info", text: ctx.t("guide.status.needs_review") }) : null;
  const card = section(title, note(ctx.t(LEAD_KEYS[step])), recheck, form);
  card.setAttribute("class", "block guide-card");
  return card;
}
