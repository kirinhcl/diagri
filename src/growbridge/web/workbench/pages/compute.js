// The compute service: the balance an operator read from MyCSC, task budgets and usage, and open or stuck attempts.
import { formatNumber } from "../format.js";
import { h } from "../ui/dom.js";
import { simpleForm } from "../ui/forms.js";
import { afterWrite, keyValues, note, pageHead, section, techDetails, timeText } from "../ui/section.js";
import { table } from "../ui/table.js";
import { attemptSections } from "./compute-attempts.js";
import { isNotMounted } from "./not-mounted.js";

const array = (value) => (Array.isArray(value) ? value : []);
const num = (ctx, value) => formatNumber(value, 2, ctx.lang);

function balanceView(ctx, balance) {
  if (!balance) return note(ctx.t("compute.balance.none"));
  return keyValues([
    [ctx.t("compute.balance.cpu"), num(ctx, balance.cpu_hours)],
    [ctx.t("compute.balance.by"), balance.entered_by],
    [ctx.t("compute.balance.at"), timeText(ctx, balance.recorded_at)],
    [ctx.t("compute.balance.note"), balance.note],
  ]);
}

function balanceForm(ctx) {
  const submitLabel = ctx.t("compute.balance.record");
  const fields = [
    { name: "cpu_hours", label: ctx.t("compute.balance.cpu"), type: "number", required: true },
    { name: "note", label: ctx.t("compute.balance.note"), type: "text" },
  ];
  const onSubmit = async (values) => {
    await ctx.api.post("/compute/balance", values, { action: submitLabel });
    afterWrite(ctx, ctx.t("compute.balance.saved"));
  };
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: "compute-balance", ctx });
}

function serviceView(ctx, service) {
  if (!service) return note(ctx.t("compute.service.none"));
  const pair = (used, cap) => ctx.t("compute.service.of", { used: num(ctx, used), cap: num(ctx, cap) });
  return keyValues([
    [ctx.t("compute.service.cpu"), pair(service.cpu_hours_committed, service.cpu_hours_cap)],
    [ctx.t("compute.service.storage"), pair(service.storage_gb_committed, service.storage_gb_cap)],
  ]);
}

function budgetsTable(ctx, tasks, pickTask) {
  const usage = (key, used, reserved, budget) =>
    ctx.t(key, { used: num(ctx, used), reserved: num(ctx, reserved), budget: num(ctx, budget) });
  const taskCell = (row, index) =>
    h("div", { class: "cell-stack" }, ctx.t("compute.taskOrdinal", { n: index + 1 }), techDetails(ctx.t, [[ctx.t("tech.id.task_id"), row.task_id]]));
  const change = (row) => {
    const label = ctx.t("compute.budget.change");
    const button = h("button", { class: "button button-quiet", attrs: { type: "button" }, text: label });
    button.addEventListener("click", () => pickTask(row.task_id));
    return button;
  };
  const columns = [
    { label: ctx.t("compute.task"), cell: (row, index) => taskCell(row, index) },
    { label: ctx.t("compute.budget.cpu"), cell: (row) => usage("compute.budget.usage", row.cpu_hours_used, row.cpu_hours_reserved, row.cpu_hours_budget) },
    { label: ctx.t("compute.budget.storage"), cell: (row) => usage("compute.budget.usageStorage", row.storage_gb_used, row.storage_gb_reserved, row.storage_gb_budget) },
    { label: ctx.t("compute.budget.change"), cell: change },
  ];
  return table(columns, tasks, { label: ctx.t("compute.budget.title") });
}

function budgetForm(ctx) {
  const submitLabel = ctx.t("compute.budget.set");
  const fields = [
    { name: "task_id", label: ctx.t("compute.budget.taskField"), type: "text", required: true },
    { name: "cpu_hours", label: ctx.t("compute.budget.cpuLimit"), type: "number", required: true },
    { name: "storage_gb", label: ctx.t("compute.budget.storageLimit"), type: "number", required: true },
  ];
  const onSubmit = async ({ task_id: taskId, ...limits }) => {
    await ctx.api.post(`/compute/tasks/${encodeURIComponent(taskId)}/budget`, limits, { action: submitLabel });
    afterWrite(ctx, ctx.t("compute.budget.saved"));
  };
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: "compute-budget", ctx });
}

const descendants = (node) => [...(node.children || [])].flatMap((child) => [child, ...descendants(child)]);

// "Change budget" on a row: that task goes into the form's task field, and the cursor goes there.
function fillTask(form, taskId) {
  const field = descendants(form).find((el) => el.getAttribute("name") === "task_id");
  if (!field) return;
  field.value = taskId;
  field.focus();
}

function overviewPage(ctx, overview) {
  const tasks = array(overview.tasks);
  const form = budgetForm(ctx);
  const budgets = tasks.length ? budgetsTable(ctx, tasks, (taskId) => fillTask(form, taskId)) : note(ctx.t("compute.budget.none"));
  return [
    section(ctx.t("compute.balance.title"), balanceView(ctx, overview.balance), balanceForm(ctx)),
    section(ctx.t("compute.service.title"), serviceView(ctx, overview.service)),
    section(ctx.t("compute.budget.title"), budgets, form),
    ...attemptSections(ctx, overview),
  ];
}

export async function render(ctx) {
  let overview = null;
  try {
    overview = await ctx.api.get("/compute");
  } catch (error) {
    if (!isNotMounted(error)) throw error;
  }
  const body = overview ? overviewPage(ctx, overview) : [section(ctx.t("nav.compute"), note(ctx.t("compute.unavailable")))];
  const element = h("div", { class: "page compute" }, pageHead(ctx.t("nav.compute"), ctx.t("compute.lead")), ...body);
  return { element };
}
