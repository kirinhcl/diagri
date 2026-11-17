// The research protocol as a form: the question, the treatments and allocations as rows, the analysis plan as fields.
// It never invents science: allocations start empty, the control and every allocation are chosen from the treatment
// rows, and the id and version are worked out, never typed. It builds exactly the object the JSON fold would send.
import codes from "../i18n/codes.en.js";
import { h } from "../ui/dom.js";
import { linesField, rowGroup } from "../ui/field-forms.js";
import { convert, fieldRow, initialText, placeFieldErrors, simpleForm } from "../ui/forms.js";

const MAX_ID_CHARS = 100;
const DEFAULT_MISSING = 0.2;
const DEFAULT_DEVIATION = 0.1;
const FIXED_METHODS = ["paired_block", "two_group"];
const METRICS = Object.keys(codes).filter((key) => key.startsWith("metric.")).map((key) => key.slice("metric.".length));

const array = (value) => (Array.isArray(value) ? value : []);
const unique = (values) => [...new Set(values.filter((value) => typeof value === "string" && value !== ""))];
const encode = encodeURIComponent;

// --- parsing -----------------------------------------------------------------------------------

const trimmed = (text, t) => {
  const value = text.trim();
  return value ? { value } : { error: t("form.required") };
};

const code = (text, t) => {
  const result = trimmed(text, t);
  if (result.error || result.value.length <= MAX_ID_CHARS) return result;
  return { error: t("form.tooLong", { max: MAX_ID_CHARS }) };
};

const whole = (min) => (text, t) => {
  const number = Number(text);
  if (!Number.isSafeInteger(number)) return { error: t("protocol.form.whole") };
  return number < min ? { error: t("form.tooSmall", { min }) } : { value: number };
};

// "key=value" per line; a value that is a finite number becomes a number, else it stays text.
function factors(text, t) {
  const found = {};
  for (const line of text.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)) {
    const at = line.indexOf("=");
    const key = at < 0 ? "" : line.slice(0, at).trim();
    const raw = at < 0 ? "" : line.slice(at + 1).trim();
    if (!key || !raw) return { error: t("protocol.form.factorLine") };
    if (Object.hasOwn(found, key)) return { error: t("protocol.form.factorTwice") };
    found[key] = Number.isFinite(Number(raw)) ? Number(raw) : raw;
  }
  return { value: found };
}

// --- reading the treatment rows straight from the page -------------------------------------------

function namedInputs(root, name, found = []) {
  if (root.getAttribute && root.getAttribute("name") === name) found.push(root);
  for (const child of root.children || []) namedInputs(child, name, found);
  return found;
}

function setOptions(select, ids, t, wanted) {
  const keep = ids.includes(wanted) ? wanted : "";
  const option = (value, text) => h("option", { attrs: { value, selected: value === keep }, text });
  select.replaceChildren(option("", t("form.choose")), ...ids.map((id) => option(id, id)));
  select.value = keep;
}

// --- a few fields as one part (the form's own parts are the rows and these) ----------------------

// A titled group of plain fields that joins simpleForm as a part: values() is {name: {...}} when `nest`, else the bare object.
function fieldsPart({ ctx, name, label, fields, nest = false }) {
  const zone = (ctx.me && ctx.me.timezone) || "UTC";
  const entries = fields.map((field) => fieldRow(field, initialText(field, zone, ctx.lang), zone));
  const element = h("fieldset", { class: "field-group" }, h("legend", { text: label }), entries.map((entry) => entry.row));
  const names = new Set(fields.map((field) => field.name));
  const values = () => {
    const found = convert(entries, zone, ctx.t);
    return found && (nest ? { [name]: found } : found);
  };
  const placeErrors = (problems) => {
    const mine = problems.filter((problem) => problem.loc.some((part) => names.has(part)));
    placeFieldErrors(entries, mine, ctx);
    return problems.filter((problem) => !mine.includes(problem));
  };
  const draft = () => Object.fromEntries(entries.map((entry) => [entry.field.name, entry.input.value]));
  const restore = (saved) => {
    for (const entry of entries) if (Object.hasOwn(saved, entry.field.name)) entry.input.value = saved[entry.field.name];
  };
  return { name, element, values, placeErrors, draft, restore, entries };
}

// --- the sections ------------------------------------------------------------------------------

function basicFields(t) {
  const text = (name, label, extra = {}) => ({ name, label, required: true, maxlength: MAX_ID_CHARS, parse: trimmed, ...extra });
  return [
    { name: "question", label: t("protocol.form.question"), hint: t("protocol.form.questionHint"), type: "textarea", required: true, parse: trimmed },
    { name: "hypothesis", label: t("protocol.form.hypothesis"), type: "textarea" },
    text("crop", t("protocol.form.crop")),
    text("batch", t("protocol.form.batch")),
    text("experimental_unit", t("protocol.form.unit"), { value: "tent" }),
    { name: "randomization_seed", label: t("protocol.form.seed"), hint: t("protocol.form.seedHint"), type: "number", step: 1, required: true, parse: whole(-Number.MAX_SAFE_INTEGER) },
    linesField({ name: "stages", label: t("protocol.form.stages"), hint: t("protocol.form.stagesHint"), required: true }),
    { name: "rounds", label: t("protocol.form.rounds"), type: "number", step: 1, required: true, parse: whole(1) },
    { name: "blocks", label: t("protocol.form.blocks"), type: "number", step: 1, required: true, parse: whole(1) },
  ];
}

function treatmentFields(t) {
  return [
    { name: "id", label: t("protocol.form.tid"), hint: t("protocol.form.tidHint"), required: true, parse: code },
    { name: "name", label: t("protocol.form.tname"), required: true, parse: trimmed },
    { name: "description", label: t("protocol.form.tdesc") },
    { name: "factors", label: t("protocol.form.tfactors"), hint: t("protocol.form.tfactorsHint"), type: "textarea", parse: factors },
  ];
}

// A code typed on two treatment rows: allocations and the control name a treatment by it.
function duplicateCodes(t) {
  return (rows) => {
    const seen = new Set();
    return rows.flatMap((row, index) => {
      if (!seen.has(row.id)) {
        seen.add(row.id);
        return [];
      }
      return [{ row: index, field: "id", error: t("protocol.form.tidTwice") }];
    });
  };
}

function analysisFields(t, project) {
  const rows = array(project.protocols);
  const fraction = (name, label, value) => ({ name, label, hint: t("protocol.form.fractionHint"), type: "number", required: true, min: 0, max: 1, value });
  return [
    { name: "primary_endpoint", label: t("protocol.form.endpoint"), hint: t("protocol.form.endpointHint"), required: true, parse: trimmed, suggestions: unique([...rows.map((row) => row.primary_endpoint), ...METRICS]) },
    { name: "target_effect", label: t("protocol.form.effect"), hint: t("protocol.form.effectHint"), type: "number", required: true },
    { name: "method", label: t("protocol.form.method"), hint: t("protocol.form.methodHint"), required: true, parse: trimmed, suggestions: unique([...FIXED_METHODS, ...rows.map((row) => row.method)]) },
    linesField({ name: "exclusion_rules", label: t("protocol.form.exclusions"), hint: t("protocol.form.exclusionsHint") }),
    fraction("max_missing_fraction", t("protocol.form.maxMissing"), DEFAULT_MISSING),
    fraction("max_deviation_fraction", t("protocol.form.maxDeviation"), DEFAULT_DEVIATION),
  ];
}

// --- id and version ----------------------------------------------------------------------------

// A protocol id is shared by all projects, so the suggestion carries a project mark; the smallest number no saved protocol uses.
export function newProtocolId(projectId, rows) {
  const taken = new Set(rows.map((row) => row.protocol_id));
  let number = rows.length + 1;
  while (taken.has(`protocol-${number}-${projectId.slice(-6)}`)) number += 1;
  return `protocol-${number}-${projectId.slice(-6)}`;
}

export function nextVersion(rows, id) {
  const versions = rows.filter((row) => row.protocol_id === id).map((row) => row.version);
  return versions.length ? Math.max(...versions) + 1 : 1;
}

// Exactly the object the JSON fold would send; the optional blanks are written out the way the server stores them.
export function buildProtocol(projectId, values, id, version) {
  const { analysis } = values;
  return {
    id,
    project_id: projectId,
    version,
    question: values.question,
    hypothesis: values.hypothesis ?? "",
    crop: values.crop,
    batch: values.batch,
    treatments: values.treatments.map((row) => ({ id: row.id, name: row.name, description: row.description ?? "", factors: row.factors ?? {} })),
    control_treatment_id: values.control_treatment_id,
    allocations: values.allocations.map((row) => ({ round: row.round, block: row.block, unit: row.unit, treatment_id: row.treatment_id })),
    randomization_seed: values.randomization_seed,
    analysis: {
      primary_endpoint: analysis.primary_endpoint,
      target_effect: analysis.target_effect,
      method: analysis.method,
      exclusion_rules: analysis.exclusion_rules ?? [],
      max_missing_fraction: analysis.max_missing_fraction,
      max_deviation_fraction: analysis.max_deviation_fraction,
    },
    stages: values.stages,
    rounds: values.rounds,
    blocks: values.blocks,
    experimental_unit: values.experimental_unit,
  };
}

// --- the form ----------------------------------------------------------------------------------

// The treatment codes as typed on the rows now, and every choice of one (the control, each allocation) kept in step with them.
function treatmentLinks(ctx) {
  const state = { treatments: null, holders: [] };
  const ids = () => (state.treatments ? unique(namedInputs(state.treatments.element, "id").map((input) => input.value.trim())) : []);
  const choices = () => [{ value: "", label: ctx.t("form.choose") }, ...ids().map((id) => ({ value: id, label: id }))];
  const refresh = (rename) => {
    const now = ids();
    for (const holder of state.holders) {
      for (const name of ["control_treatment_id", "treatment_id"]) {
        for (const select of namedInputs(holder.element, name)) {
          const followed = rename && rename.from && select.value === rename.from ? rename.to : select.value;
          setOptions(select, now, ctx.t, followed);
        }
      }
    }
  };
  // A row's code is followed while it is typed: a choice that held the old code now holds the new one.
  const onRow = (entries) => {
    const input = entries.find((entry) => entry.field.name === "id").input;
    let last = input.value.trim();
    const typed = () => {
      const from = last;
      last = input.value.trim();
      if (from !== last) refresh({ from, to: last });
    };
    input.addEventListener("input", typed);
    input.addEventListener("change", typed);
  };
  return { state, choices, refresh, onRow };
}

const versionNote = (ctx, rows, id) => {
  const version = nextVersion(rows, id);
  return ctx.t(version === 1 ? "protocol.form.newProtocol" : "protocol.form.newVersion", { version });
};

// project: the project read (its protocols[] rows have protocol_id, version, primary_endpoint, method).
// protocolId: save as another version of this saved protocol; left out, the protocol is a new one.
// onSubmit({protocol}) sends it. The version is worked out when the form is sent, from a fresh read of the project.
export function protocolForm(ctx, { project, onSubmit, protocolId }) {
  const { t } = ctx;
  const links = treatmentLinks(ctx);
  const choice = (name, label) => ({ name, label, type: "select", required: true, get options() { return links.choices(); } });
  const treatments = rowGroup({
    ctx, name: "treatments", label: t("protocol.form.treatments"), fields: treatmentFields(t), minRows: 1, rows: [{}, {}],
    addLabel: t("protocol.form.addTreatment"), removeLabel: t("protocol.form.removeTreatment"),
    onRow: links.onRow, crossCheck: duplicateCodes(t), onChange: () => links.refresh(),
  });
  links.state.treatments = treatments;
  const control = fieldsPart({ ctx, name: "control", label: t("protocol.form.control"), fields: [choice("control_treatment_id", t("protocol.form.controlPick"))] });
  const allocations = rowGroup({
    ctx, name: "allocations", label: t("protocol.form.allocations"), addLabel: t("protocol.form.addAllocation"), removeLabel: t("protocol.form.removeAllocation"),
    fields: [
      { name: "round", label: t("protocol.form.round"), type: "number", step: 1, required: true, parse: whole(1) },
      { name: "block", label: t("protocol.form.block"), type: "number", step: 1, required: true, parse: whole(1) },
      { name: "unit", label: t("protocol.form.allocUnit"), required: true, parse: code },
      choice("treatment_id", t("protocol.form.allocTreatment")),
    ],
  });
  links.state.holders = [control, allocations];
  // The saved choice comes back after the rows it chooses from have.
  const restoreControl = control.restore;
  control.restore = (saved) => {
    links.refresh();
    restoreControl(saved);
  };
  const analysis = fieldsPart({ ctx, name: "analysis", label: t("protocol.form.analysis"), fields: analysisFields(t, project), nest: true });
  const send = async (values) => {
    const fresh = await ctx.api.get(`/projects/${encode(project.project_id)}`);
    const rows = array(fresh && fresh.protocols);
    const id = protocolId || newProtocolId(project.project_id, rows);
    note.textContent = versionNote(ctx, rows, id);
    await onSubmit({ protocol: buildProtocol(project.project_id, values, id, nextVersion(rows, id)) });
  };
  const form = simpleForm({
    fields: basicFields(t), parts: [treatments, control, allocations, analysis], ctx, onSubmit: send,
    draftKey: `protocol:${project.project_id}-form`, submitLabel: t("project.protocols.save"),
  });
  const note = h("p", { class: "note", text: versionNote(ctx, array(project.protocols), protocolId || newProtocolId(project.project_id, array(project.protocols))) });
  return h("div", { class: "protocol-form" }, note, h("p", { class: "note", text: t("protocol.form.allocationsLead") }), form);
}
