// One project: its conversation, rounds, goals and tasks, protocols, call budget and holdouts.
import { ApiError } from "../api.js";
import { formatMoney, formatNumber } from "../format.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { displayName, nameDetails, protocolName, roleLabel } from "../ui/names.js";
import { errorParts, foldedText, keyValues, note, pageHead, section, techDetails, timeText } from "../ui/section.js";
import { statePill } from "../ui/status.js";
import { table } from "../ui/table.js";
import { conversationSection } from "./conversation.js";
import { guideButton } from "./guide-entry.js";
import { budgetForm, holdoutEditor, protocolEditor, startRoundForm } from "./project-forms.js";

const array = (value) => (Array.isArray(value) ? value : []);
const POLL_SECONDS = 4;

// The round by number; its id, and the id of a stage that stopped for a choice, in the row's details.
function roundCell(ctx, row) {
  const link = h("a", { class: "text-link", attrs: { href: hrefFor("round", { roundId: row.round_id }) }, text: displayName(ctx, "round", row) });
  const ids = techDetails(ctx.t, [...nameDetails(row, ctx.t), [ctx.t("tech.id.stage_id"), row.awaiting_choice]]);
  return h("span", { class: "cell-stack" }, link, ids);
}

// The project read does not say which stage stopped, so the row says that one did.
function roundsTable(ctx, project) {
  const rounds = array(project.rounds);
  if (!rounds.length) return note(ctx.t("project.rounds.empty"));
  const columns = [
    { label: ctx.t("col.round"), cell: (row) => roundCell(ctx, row) },
    { label: ctx.t("col.state"), cell: (row) => statePill(ctx.t, row.state) },
    { label: ctx.t("col.protocol"), cell: (row) => protocolName(ctx.t, row.protocol_id, row.protocol_version) },
    { label: ctx.t("round.awaitingChoice"), cell: (row) => (row.awaiting_choice ? ctx.t("project.rounds.awaiting") : "—") },
    { label: ctx.t("col.created"), cell: (row) => timeText(ctx, row.created_at) },
  ];
  return table(columns, rounds, { label: ctx.t("project.rounds.title") });
}

function protocolsTable(ctx, project) {
  const protocols = array(project.protocols);
  if (!protocols.length) return note(ctx.t("project.protocols.empty"));
  const columns = [
    { label: ctx.t("col.protocol"), cell: (row) => h("span", { class: "cell-stack" }, protocolName(ctx.t, row.protocol_id), techDetails(ctx.t, nameDetails(row, ctx.t))) },
    { label: ctx.t("col.version"), cell: (row) => String(row.version) },
    { label: ctx.t("col.created"), cell: (row) => timeText(ctx, row.created_at) },
  ];
  return table(columns, protocols, { label: ctx.t("project.protocols.title") });
}

// "used / total", each shown as it is: a cost can be spent past its limit.
function usedOfTotal(label, used, total, show) {
  return [label, `${show(used)} / ${show(total)}`];
}

// What is left of the call budget, in the page's language; when either runs out, no model is called.
export function budgetView(ctx, project) {
  const budget = project.budget;
  if (!budget) return note(ctx.t("project.budget.none"));
  const rows = [];
  // An old server answers only what is left; the used and total figures come with a new one.
  if (budget.used_calls !== undefined && budget.max_calls !== undefined) rows.push(usedOfTotal(ctx.t("project.budget.callsUsed"), budget.used_calls, budget.max_calls, (n) => formatNumber(n, 0, ctx.lang)));
  if (budget.used_cost !== undefined && budget.max_cost !== undefined) rows.push(usedOfTotal(ctx.t("project.budget.costUsed"), budget.used_cost, budget.max_cost, (n) => formatMoney(n, ctx.lang)));
  rows.push(
    [ctx.t("project.budget.callsLeft"), formatNumber(budget.calls_left, 0, ctx.lang)],
    [ctx.t("project.budget.costLeft"), formatMoney(budget.cost_left, ctx.lang)],
  );
  return h("div", {}, keyValues(rows), note(ctx.t("project.budget.help")));
}

function tasksTable(ctx, project) {
  const tasks = array(project.tasks);
  if (!tasks.length) return note(ctx.t("project.tasks.empty"));
  const columns = [
    { label: ctx.t("project.tasks.question"), cell: (row) => foldedText(ctx, row.question) },
    { label: ctx.t("project.tasks.owner"), cell: (row) => roleLabel(ctx.t, row.owner_role) },
    { label: ctx.t("col.state"), cell: (row) => statePill(ctx.t, row.state) },
  ];
  return table(columns, tasks, { label: ctx.t("project.goals.title") });
}

function readsText(ctx, reads) {
  const n = array(reads).length;
  return n === 1 ? ctx.t("project.holdouts.readsOne") : ctx.t("project.holdouts.readsCount", { n });
}

// The held-out batches carry the registration's id in their details.
function holdoutsTable(ctx, holdouts) {
  const list = (values) => (Array.isArray(values) ? values.join(", ") : "—");
  const batches = (row) => h("span", { class: "cell-stack" }, list(row.batch_ids), techDetails(ctx.t, [[ctx.t("tech.id.holdout_id"), row.holdout_id]]));
  const columns = [
    { label: ctx.t("project.holdouts.batches"), cell: batches },
    { label: ctx.t("project.holdouts.development"), cell: (row) => list(row.development_batch_ids) },
    { label: ctx.t("project.holdouts.fields"), cell: (row) => list(row.outcome_fields) },
    { label: ctx.t("project.holdouts.reads"), cell: (row) => readsText(ctx, row.reads) },
    { label: ctx.t("col.created"), cell: (row) => timeText(ctx, row.registered_at) },
  ];
  return [table(columns, holdouts, { label: ctx.t("project.holdouts.title") }), note(ctx.t("project.holdouts.readsHelp"))];
}

// The holdout list is a side read: when it fails the rest of the page still works.
async function readHoldouts(ctx, projectId) {
  try {
    const data = await ctx.api.get(`/holdouts?project_id=${encodeURIComponent(projectId)}`);
    return { holdouts: array(data && data.holdouts), error: null };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    return { holdouts: [], error };
  }
}

function holdoutsBlock(ctx, project, read) {
  const problem = read.error ? h("div", { class: "form-status form-status-error" }, errorParts(ctx, read.error)) : null;
  const shown = read.holdouts.length ? holdoutsTable(ctx, read.holdouts) : note(ctx.t("project.holdouts.empty"));
  return section(ctx.t("project.holdouts.title"), problem, shown, holdoutEditor(ctx, project));
}

// The conversation and the rounds come first; the editors wait closed in their sections.
export async function render(ctx, params) {
  const projectId = params.projectId;
  const [project, read] = await Promise.all([
    ctx.api.get(`/projects/${encodeURIComponent(projectId)}`),
    readHoldouts(ctx, projectId),
  ]);
  const name = displayName(ctx, "project", project);
  ctx.setBreadcrumbs([{ label: ctx.t("nav.projects"), href: hrefFor("projects") }, { label: name }]);
  const lead = ctx.t("project.lead", { time: timeText(ctx, project.created_at) });
  const chat = conversationSection(ctx, project);
  await chat.refresh();
  const element = h(
    "div",
    { class: "page project" },
    pageHead(name, lead),
    techDetails(ctx.t, nameDetails(project, ctx.t)),
    section(ctx.t("chat.title"), chat.element),
    section(ctx.t("project.rounds.title"), roundsTable(ctx, project), startRoundForm(ctx, project)),
    section(ctx.t("project.goals.title"), tasksTable(ctx, project)),
    section(ctx.t("project.protocols.title"), protocolsTable(ctx, project), guideButton(ctx, project), protocolEditor(ctx, project)),
    section(ctx.t("project.budget.title"), budgetView(ctx, project), budgetForm(ctx, project)),
    holdoutsBlock(ctx, project, read),
  );
  return { element, refresh: chat.refresh, pollSeconds: POLL_SECONDS };
}
