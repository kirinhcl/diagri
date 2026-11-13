// One project: its rounds, protocols, call budget, goals, tasks and holdouts.
import { ApiError } from "../api.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { errorLines } from "../ui/forms.js";
import { keyValues, note, pageHead, section, timeText } from "../ui/section.js";
import { statePill } from "../ui/status.js";
import { table } from "../ui/table.js";
import { budgetForm, goalEditor, holdoutEditor, protocolEditor, startRoundForm } from "./project-forms.js";

const array = (value) => (Array.isArray(value) ? value : []);

function roundsTable(ctx, project) {
  const rounds = array(project.rounds);
  if (!rounds.length) return note(ctx.t("project.rounds.empty"));
  const columns = [
    {
      label: ctx.t("col.round"),
      cell: (row) => h("a", { class: "text-link", attrs: { href: hrefFor("round", { roundId: row.round_id }) }, text: row.round_id }),
    },
    { label: ctx.t("col.state"), cell: (row) => statePill(ctx.t, row.state) },
    { label: ctx.t("col.protocol"), cell: (row) => `${row.protocol_id} v${row.protocol_version}` },
    { label: ctx.t("round.awaitingChoice"), cell: (row) => row.awaiting_choice || "—" },
    { label: ctx.t("col.created"), cell: (row) => timeText(ctx, row.created_at) },
  ];
  return table(columns, rounds, { label: ctx.t("project.rounds.title") });
}

function protocolsTable(ctx, project) {
  const protocols = array(project.protocols);
  if (!protocols.length) return note(ctx.t("project.protocols.empty"));
  const columns = [
    { label: ctx.t("col.protocol"), cell: (row) => h("code", { text: row.protocol_id }) },
    { label: ctx.t("col.version"), cell: (row) => String(row.version) },
    { label: ctx.t("col.created"), cell: (row) => timeText(ctx, row.created_at) },
  ];
  return table(columns, protocols, { label: ctx.t("project.protocols.title") });
}

function budgetView(ctx, project) {
  const budget = project.budget;
  if (!budget) return note(ctx.t("project.budget.none"));
  return keyValues([
    [ctx.t("project.budget.callsLeft"), String(budget.calls_left)],
    [ctx.t("project.budget.costLeft"), String(budget.cost_left)],
  ]);
}

function tasksTable(ctx, project) {
  const tasks = array(project.tasks);
  if (!tasks.length) return note(ctx.t("project.tasks.empty"));
  const columns = [
    { label: ctx.t("project.tasks.question"), cell: (row) => row.question },
    { label: ctx.t("project.tasks.owner"), cell: (row) => row.owner_role },
    { label: ctx.t("col.state"), cell: (row) => statePill(ctx.t, row.state) },
  ];
  return table(columns, tasks, { label: ctx.t("project.tasks.title") });
}

function holdoutsTable(ctx, holdouts) {
  if (!holdouts.length) return note(ctx.t("project.holdouts.empty"));
  const list = (values) => (Array.isArray(values) ? values.join(", ") : "—");
  const columns = [
    { label: ctx.t("col.id"), cell: (row) => h("code", { text: row.holdout_id }) },
    { label: ctx.t("project.holdouts.batches"), cell: (row) => list(row.batch_ids) },
    { label: ctx.t("project.holdouts.development"), cell: (row) => list(row.development_batch_ids) },
    { label: ctx.t("project.holdouts.fields"), cell: (row) => list(row.outcome_fields) },
    { label: ctx.t("project.holdouts.reads"), cell: (row) => String(array(row.reads).length) },
    { label: ctx.t("col.created"), cell: (row) => timeText(ctx, row.registered_at) },
  ];
  return table(columns, holdouts, { label: ctx.t("project.holdouts.title") });
}

// The holdout list is a side read: when it fails the rest of the page still works.
async function readHoldouts(ctx, projectId) {
  try {
    const data = await ctx.api.get(`/holdouts?project_id=${encodeURIComponent(projectId)}`);
    return { holdouts: array(data && data.holdouts), problem: null };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    return { holdouts: [], problem: errorLines(error, ctx.lang, ctx.t) };
  }
}

function holdoutsBlock(ctx, project, read) {
  const lines = read.problem ? read.problem.map((line) => h("p", { text: line })) : [];
  const problem = lines.length ? h("div", { class: "form-status form-status-error" }, lines) : null;
  return section(ctx.t("project.holdouts.title"), problem, holdoutsTable(ctx, read.holdouts), holdoutEditor(ctx, project));
}

export async function render(ctx, params) {
  const projectId = params.projectId;
  const [project, read] = await Promise.all([
    ctx.api.get(`/projects/${encodeURIComponent(projectId)}`),
    readHoldouts(ctx, projectId),
  ]);
  ctx.setBreadcrumbs([{ label: ctx.t("nav.projects"), href: hrefFor("projects") }, { label: project.name }]);
  const lead = ctx.t("project.lead", { id: project.project_id, time: timeText(ctx, project.created_at) });
  const element = h(
    "div",
    { class: "page project" },
    pageHead(project.name, lead),
    section(ctx.t("project.rounds.title"), roundsTable(ctx, project), startRoundForm(ctx, project)),
    section(ctx.t("project.protocols.title"), protocolsTable(ctx, project), protocolEditor(ctx, project)),
    section(ctx.t("project.budget.title"), budgetView(ctx, project), budgetForm(ctx, project)),
    section(ctx.t("project.goals.title"), tasksTable(ctx, project), goalEditor(ctx, project)),
    holdoutsBlock(ctx, project, read),
  );
  return { element };
}
