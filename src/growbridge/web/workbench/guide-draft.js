// The guide's composed protocol, written as the draft the normal protocol form (pages/protocol-form.js) starts from.
// A draft is what the form would hold as typed text, so this is only the reverse of buildProtocol: every value is text,
// a list is one item per line, the factors of a treatment one "key=value" per line. Nothing is decided here.
const array = (value) => (Array.isArray(value) ? value : []);
const text = (value) => (value === null || value === undefined ? "" : String(value));
const lines = (values) => array(values).map(text).join("\n");
const factorLines = (factors) => Object.entries(factors && typeof factors === "object" ? factors : {}).map(([key, value]) => `${key}=${text(value)}`).join("\n");

const treatmentRow = (row) => ({ id: text(row.id), name: text(row.name), description: text(row.description), factors: factorLines(row.factors) });
const allocationRow = (row) => ({ round: text(row.round), block: text(row.block), unit: text(row.unit), treatment_id: text(row.treatment_id) });

function analysisPart(protocol) {
  const plan = protocol.analysis || {};
  return {
    variables: lines(protocol.variables),
    primary_endpoint: text(plan.primary_endpoint),
    target_effect: text(plan.target_effect),
    method: text(plan.method),
    exclusion_rules: lines(plan.exclusion_rules),
    max_missing_fraction: text(plan.max_missing_fraction),
    max_deviation_fraction: text(plan.max_deviation_fraction),
  };
}

// saveAs: the saved protocol this one is the next version of, or "" for a new protocol.
// Returns {fields, parts} in the shape simpleForm keeps a draft in (ui/forms.js).
export function protocolFormDraft(protocol, { saveAs }) {
  const fields = {
    save_as: text(saveAs),
    question: text(protocol.question),
    hypothesis: text(protocol.hypothesis),
    crop: text(protocol.crop),
    crop_taxon: text(protocol.crop_taxon),
    cultivar: text(protocol.cultivar),
    batch: text(protocol.batch),
    experimental_unit: text(protocol.experimental_unit),
    randomization_seed: text(protocol.randomization_seed),
    stages: lines(protocol.stages),
    rounds: text(protocol.rounds),
    blocks: text(protocol.blocks),
  };
  const parts = {
    treatments: array(protocol.treatments).map(treatmentRow),
    control: { control_treatment_id: text(protocol.control_treatment_id) },
    allocations: array(protocol.allocations).map(allocationRow),
    analysis: analysisPart(protocol),
  };
  return { fields, parts };
}
