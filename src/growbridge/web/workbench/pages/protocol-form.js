// The research protocol as a form: the question, the treatments and allocations as rows, the analysis plan as fields.
// It never invents science: allocations start empty, the control and every allocation are chosen from the treatment
// rows, and the id and version are worked out, never typed. It builds exactly the object the JSON fold would send.
import { ApiError } from "../api.js";
import { h } from "../ui/dom.js";
import { fieldsPart, linesField, rowGroup } from "../ui/field-forms.js";
import { simpleForm } from "../ui/forms.js";
import { protocolName } from "../ui/names.js";

const DEFAULT_MISSING = 0.2;
const DEFAULT_DEVIATION = 0.1;
const FIXED_METHODS = ["paired_block", "two_group"];

const PLAIN_DECIMAL = /^-?\d+(\.\d+)?$/;
const array = (value) => (Array.isArray(value) ? value : []);
const unique = (values) => [...new Set(values.filter((value) => typeof value === "string" && value !== ""))];
const encode = encodeURIComponent;

// --- parsing -----------------------------------------------------------------------------------

const trimmed = (text, t) => {
  const value = text.trim();
  return value ? { value } : { error: t("form.required") };
};

const whole = (min) => (text, t) => {
  const number = Number(text);
  if (!Number.isSafeInteger(number)) return { error: t("protocol.form.whole") };
  return number < min ? { error: t("form.tooSmall", { min }) } : { value: number };
};

// "key=value" per line; a plain decimal a number holds exactly as typed ("40", "-1.5") becomes a number. Everything
// else stays text: "0x10", "1e3", "007", and "1.50" or 20 digits, which a number would change.
function factors(text, t) {
  const found = {};
  for (const line of text.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)) {
    const at = line.indexOf("=");
    const key = at < 0 ? "" : line.slice(0, at).trim();
    const raw = at < 0 ? "" : line.slice(at + 1).trim();
    if (!key || !raw) return { error: t("protocol.form.factorLine") };
    if (Object.hasOwn(found, key)) return { error: t("protocol.form.factorTwice") };
    found[key] = PLAIN_DECIMAL.test(raw) && String(Number(raw)) === raw ? Number(raw) : raw;
  }
  return { value: found };
}

// --- reading the treatment rows straight from the page -------------------------------------------

function namedInputs(root, name, found = []) {
  if (root.getAttribute && root.getAttribute("name") === name) found.push(root);
  for (const child of root.children || []) namedInputs(child, name, found);
  return found;
}

function setOptions(select, choices, t, wanted) {
  const keep = choices.some((choice) => choice.value === wanted) ? wanted : "";
  const option = (value, text) => h("option", { attrs: { value, selected: value === keep }, text });
  select.replaceChildren(option("", t("form.choose")), ...choices.map((choice) => option(choice.value, choice.label)));
  select.value = keep;
}

// --- a few fields as one part (the form's own parts are the rows and these) ----------------------

// --- the sections ------------------------------------------------------------------------------

function basicFields(t) {
  // The server asks nothing of the crop, batch and unit text, so neither does the form; the species is the exception (an NCBI Taxonomy ID).
  const text = (name, label, extra = {}) => ({ name, label, ...extra });
  return [
    { name: "question", label: t("protocol.form.question"), hint: t("protocol.form.questionHint"), type: "textarea", required: true, parse: trimmed },
    { name: "hypothesis", label: t("protocol.form.hypothesis"), type: "textarea" },
    text("crop", t("protocol.form.crop")),
    text("crop_taxon", t("protocol.form.cropTaxon"), { hint: t("protocol.form.cropTaxonHint"), required: true, parse: trimmed }),
    text("cultivar", t("protocol.form.cultivar")),
    text("batch", t("protocol.form.batch")),
    text("experimental_unit", t("protocol.form.unit"), { value: "tent" }),
    { name: "randomization_seed", label: t("protocol.form.seed"), hint: t("protocol.form.seedHint"), type: "number", step: 1, required: true, parse: whole(-Number.MAX_SAFE_INTEGER) },
    linesField({ name: "stages", label: t("protocol.form.stages"), hint: t("protocol.form.stagesHint") }),
    { name: "rounds", label: t("protocol.form.rounds"), type: "number", step: 1, required: true, parse: whole(1) },
    { name: "blocks", label: t("protocol.form.blocks"), type: "number", step: 1, required: true, parse: whole(1) },
  ];
}

function treatmentFields(t) {
  return [
    { name: "id", label: t("protocol.form.tid"), hint: t("protocol.form.tidHint"), required: true, parse: trimmed },
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
  const endpoints = unique(rows.map((row) => row.primary_endpoint));
  const fraction = (name, label, value) => ({ name, label, hint: t("protocol.form.fractionHint"), type: "number", required: true, min: 0, max: 1, value });
  return [
    linesField({ name: "variables", label: t("protocol.form.variables"), hint: t("protocol.form.variablesHint"), required: true }),
    { name: "primary_endpoint", label: t("protocol.form.endpoint"), hint: t(endpoints.length ? "protocol.form.endpointHint" : "protocol.form.endpointHintNone"), required: true, parse: trimmed, suggestions: endpoints },
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
    crop: values.crop ?? "",
    crop_taxon: values.crop_taxon ?? "",
    cultivar: values.cultivar ?? "",
    batch: values.batch ?? "",
    treatments: values.treatments.map((row) => ({ id: row.id, name: row.name, description: row.description ?? "", factors: row.factors ?? {} })),
    control_treatment_id: values.control_treatment_id,
    allocations: values.allocations.map((row) => ({ round: row.round, block: row.block, unit: row.unit ?? "", treatment_id: row.treatment_id })),
    randomization_seed: values.randomization_seed,
    variables: analysis.variables ?? [],
    analysis: {
      primary_endpoint: analysis.primary_endpoint,
      target_effect: analysis.target_effect,
      method: analysis.method,
      exclusion_rules: analysis.exclusion_rules ?? [],
      max_missing_fraction: analysis.max_missing_fraction,
      max_deviation_fraction: analysis.max_deviation_fraction,
    },
    stages: values.stages ?? [],
    rounds: values.rounds,
    blocks: values.blocks,
    experimental_unit: values.experimental_unit ?? "tent",
  };
}

// --- the form ----------------------------------------------------------------------------------

// The treatment codes as typed on the rows now, and every choice of one (the control, each allocation) kept in step with them.
function treatmentLinks(ctx) {
  const state = { treatments: null, holders: [] };
  // One choice per typed code, shown by the treatment's name; the code only tells apart equal names or stands in for no name yet.
  const treatmentChoices = () => {
    if (!state.treatments) return [];
    const codes = namedInputs(state.treatments.element, "id").map((input) => input.value.trim());
    const names = namedInputs(state.treatments.element, "name").map((input) => input.value.trim());
    const shown = unique(codes).map((code) => ({ value: code, name: names[codes.indexOf(code)] || "" }));
    return shown.map(({ value, name }) => ({ value, label: !name ? `(${value})` : shown.filter((other) => other.name === name).length > 1 ? `${name} (${value})` : name }));
  };
  const choices = () => [{ value: "", label: ctx.t("form.choose") }, ...treatmentChoices()];
  const refresh = (rename) => {
    const now = treatmentChoices();
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
    const name = entries.find((entry) => entry.field.name === "name").input;
    name.addEventListener("input", () => refresh());
    name.addEventListener("change", () => refresh());
  };
  return { state, choices, refresh, onRow };
}

const versionNote = (ctx, rows, id) => {
  const version = nextVersion(rows, id);
  return ctx.t(version === 1 ? "protocol.form.newProtocol" : "protocol.form.newVersion", { version });
};

// "A new protocol", or one of the saved protocols (then the form saves its next version).
function saveAsField(ctx, rows, protocolId) {
  const saved = unique(rows.map((row) => row.protocol_id));
  const options = saved.map((id) => ({ value: id, label: ctx.t("protocol.form.saveAsItem", { name: protocolName(ctx.t, id), version: nextVersion(rows, id) - 1 }) }));
  return { name: "save_as", label: ctx.t("protocol.form.saveAs"), type: "select", value: protocolId, options: [{ value: "", label: ctx.t("protocol.form.saveAsNew") }, ...options] };
}

// The skeleton the JSON fold starts from: only what is not the operator's to decide is filled (the id, version 1, the server's own defaults).
export function protocolSkeleton(projectId, rows) {
  return {
    id: newProtocolId(projectId, rows), project_id: projectId, version: 1, question: "", hypothesis: "", crop: "", crop_taxon: "", cultivar: "", batch: "",
    treatments: [], control_treatment_id: "", allocations: [], randomization_seed: null, variables: [],
    analysis: { primary_endpoint: "", target_effect: null, method: "", exclusion_rules: [], max_missing_fraction: DEFAULT_MISSING, max_deviation_fraction: DEFAULT_DEVIATION },
    stages: [], rounds: null, blocks: null, experimental_unit: "tent",
  };
}

// protocols[] of a fresh project read: the JSON fold may only save a version above the saved ones of its id.
export function versionRefusal(ctx, rows, protocol) {
  const saved = nextVersion(rows, protocol?.id) - 1;
  const version = protocol?.version;
  if (typeof version !== "number" || saved === 0 || version > saved) return null;
  return new ApiError(0, "not_approved", ctx.t("protocol.form.versionTooLow", { saved, next: saved + 1 }));
}

// project: the project read (its protocols[] rows have protocol_id, version, primary_endpoint, method).
// protocolId: the saved protocol the "Save as" choice starts on; left out, the protocol is a new one.
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
      { name: "unit", label: t("protocol.form.allocUnit") },
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
    const id = values.save_as || newProtocolId(project.project_id, rows);
    note.textContent = versionNote(ctx, rows, id);
    await onSubmit({ protocol: buildProtocol(project.project_id, values, id, nextVersion(rows, id)) });
  };
  const form = simpleForm({
    fields: [saveAsField(ctx, array(project.protocols), protocolId), ...basicFields(t)], parts: [treatments, control, allocations, analysis], ctx, onSubmit: send,
    draftKey: `protocol:${project.project_id}-form`, submitLabel: t("project.protocols.save"),
  });
  const rows = array(project.protocols);
  const select = namedInputs(form, "save_as")[0];
  const shown = () => versionNote(ctx, rows, select.value || newProtocolId(project.project_id, rows));
  const note = h("p", { class: "note", text: shown() });
  select.addEventListener("change", () => {
    note.textContent = shown();
  });
  return h("div", { class: "protocol-form" }, note, h("p", { class: "note", text: t("protocol.form.allocationsLead") }), form);
}
