// The compute service: the balance an operator read from MyCSC, task budgets and usage, and open or stuck attempts.
import { formatNumber } from "../format.js";
import { h } from "../ui/dom.js";
import { simpleForm } from "../ui/forms.js";
import { afterWrite, keyValues, note, pageHead, section, timeText } from "../ui/section.js";
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
    afterWrite(ctx);
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

function budgetsTable(ctx, tasks) {
  const pair = (used, reserved, budget) =>
    ctx.t("compute.budget.usage", { used: num(ctx, used), reserved: num(ctx, reserved), budget: num(ctx, budget) });
  const columns = [
    { label: ctx.t("compute.task"), cell: (row) => row.task_id },
    { label: ctx.t("compute.budget.cpu"), cell: (row) => pair(row.cpu_hours_used, row.cpu_hours_reserved, row.cpu_hours_budget) },
    { label: ctx.t("compute.budget.storage"), cell: (row) => pair(row.storage_gb_used, row.storage_gb_reserved, row.storage_gb_budget) },
  ];
  return table(columns, tasks, { label: ctx.t("compute.budget.title") });
}

function budgetForm(ctx) {
  const submitLabel = ctx.t("compute.budget.set");
  const fields = [
    { name: "task_id", label: ctx.t("compute.task"), type: "text", required: true },
    { name: "cpu_hours", label: ctx.t("compute.budget.cpuLimit"), type: "number", required: true },
    { name: "storage_gb", label: ctx.t("compute.budget.storageLimit"), type: "number", required: true },
  ];
  const onSubmit = async ({ task_id: taskId, ...limits }) => {
    await ctx.api.post(`/compute/tasks/${encodeURIComponent(taskId)}/budget`, limits, { action: submitLabel });
    afterWrite(ctx);
  };
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: "compute-budget", ctx });
}

function overviewPage(ctx, overview) {
  const tasks = array(overview.tasks);
  const budgets = tasks.length ? budgetsTable(ctx, tasks) : note(ctx.t("compute.budget.none"));
  return [
    section(ctx.t("compute.balance.title"), balanceView(ctx, overview.balance), balanceForm(ctx)),
    section(ctx.t("compute.service.title"), serviceView(ctx, overview.service)),
    section(ctx.t("compute.budget.title"), budgets, budgetForm(ctx)),
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
