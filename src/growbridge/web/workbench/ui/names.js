// What a thing is called on screen: a name or a number, never its id. The ids go to the technical
// details through nameDetails.
import { formatDateTime } from "../format.js";
import { labelOr } from "../i18n.js";

const ROLES = new Set(["user", "orchestrator", "planner", "researcher", "auditor"]);
const QUESTION_CHARS = 60;
// The ids a row may carry and the catalog key naming each in the technical details.
const ID_LABELS = {
  project_id: "tech.id.project_id",
  round_id: "tech.id.round_id",
  stage_id: "tech.id.stage_id",
  experiment_id: "tech.id.experiment_id",
  snapshot_id: "tech.id.snapshot_id",
  attempt_id: "tech.id.attempt_id",
  task_id: "tech.id.task_id",
  protocol_id: "tech.id.protocol_id",
  id: "tech.id.id",
};
// The ids the protocol form makes ("protocol-3-ab12cd": a number, then the project id's last six
// characters) and the simulator's ("protocol-1").
const MADE_PROTOCOL_ID = /^protocol-(\d+)(?:-.{1,6})?$/;

const has = (value) => value !== undefined && value !== null && value !== "";

export function roleLabel(t, role) {
  return labelOr(t, "chat.role", ROLES.has(role) ? role : "other");
}

function timeOf(ctx, seconds) {
  return formatDateTime(seconds, ctx.me?.timezone ?? "UTC", ctx.lang, ctx.now ?? Date.now() / 1000);
}

function stageName(ctx, row) {
  if (!has(row.stage_index)) return ctx.t("name.stage.unnamed");
  const n = row.stage_index;
  return has(row.phase) ? ctx.t("name.stage.phase", { n, phase: row.phase }) : ctx.t("name.stage", { n });
}

function snapshotName(ctx, row) {
  if (!has(row.created_at)) return ctx.t("name.snapshot.none");
  const time = timeOf(ctx, row.created_at);
  return ctx.t(row.complete ? "name.snapshot.complete" : "name.snapshot.incomplete", { time });
}

function questionName(ctx, row) {
  const question = typeof row.question === "string" ? row.question.trim() : "";
  if (!question) return ctx.t("name.task.unnamed");
  const chars = [...question];
  return chars.length > QUESTION_CHARS ? `${chars.slice(0, QUESTION_CHARS).join("")}…` : question;
}

function manualTaskName(ctx, row) {
  const kind = labelOr(ctx.t, "tasks.kind", row.kind);
  return has(row.due_at) ? ctx.t("name.manual.due", { kind, time: timeOf(ctx, row.due_at) }) : kind;
}

function attemptName(ctx, row) {
  const at = row.created_at ?? row.since;
  return has(at) ? ctx.t("name.attempt", { time: timeOf(ctx, at) }) : ctx.t("name.attempt.none");
}

const NAMERS = {
  project: (ctx, row) => (has(row.name ?? row.project_name) ? String(row.name ?? row.project_name) : ctx.t("name.project.unnamed")),
  round: (ctx, row) => (has(row.round_number) ? ctx.t("name.round", { n: row.round_number }) : ctx.t("name.round.unnamed")),
  stage: stageName,
  snapshot: snapshotName,
  researchTask: questionName,
  manualTask: manualTaskName,
  attempt: attemptName,
};

// The simulator's device id; a person reads "Simulated device" instead, a real device by its id.
export const SIMULATED_DEVICE = "SIMULATED";

export function deviceName(t, id) {
  return id === SIMULATED_DEVICE ? t("stage.review.simulated") : id;
}

export function displayName(ctx, kind, row) {
  return NAMERS[kind](ctx, row || {});
}

// A protocol the console made is "Protocol 3"; one whose id a person typed in the JSON fold is called
// by that text, the only name they gave it. With a version: "Protocol 3, version 2". The id itself
// goes to the technical details (nameDetails reads `protocol_id`).
export function protocolName(t, id, version = null) {
  const made = MADE_PROTOCOL_ID.exec(has(id) ? String(id) : "");
  const name = made ? t("name.protocol", { n: Number(made[1]) }) : has(id) ? t("name.protocol.typed", { name: id }) : t("name.protocol.unnamed");
  return has(version) ? t("name.protocol.version", { name, v: version }) : name;
}

// The ids a row carries, as [label, value] pairs for techDetails. The label is the catalog key
// `tech.id.<key>`, or its text when the page passes its `t`.
export function nameDetails(row, t = (key) => key) {
  const source = row || {};
  return Object.entries(ID_LABELS)
    .filter(([key]) => has(source[key]))
    .map(([key, label]) => [t(label), source[key]]);
}
