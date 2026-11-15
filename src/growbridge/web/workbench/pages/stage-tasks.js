// The stage's manual tasks: every daily occurrence the run sheet plans, its state, and the buttons
// that record it. A planned irrigation (an irrigation task with seconds) is started here by a
// person on the on-site entry; the stage keeps running. Records are appended, the latest counts.
import { confirmAction } from "../ui/dialog.js";
import { h } from "../ui/dom.js";
import { errorBox, note, showErrors, timeText } from "../ui/section.js";
import { table } from "../ui/table.js";

export const AHEAD_SECONDS = 86400; // upcoming occurrences are listed one day ahead
export const SHOWN_ROWS = 9; // three days of a typical sheet; older occurrences fold away
const DONE = new Set(["done", "late"]);
// a planned irrigation runs once per occurrence and never after its deadline (then "missed")
const RUNNABLE = new Set(["upcoming", "open"]);
const PILL = { done: "pill-active", late: "pill-waiting", open: "pill-waiting", missed: "pill-onsite", skipped: "pill-onsite", partial: "pill-onsite", upcoming: "" };

// Newest first, without what is more than a day away.
export function visibleRows(body) {
  const rows = Array.isArray(body && body.occurrences) ? body.occurrences : [];
  const until = (body.now || 0) + AHEAD_SECONDS;
  return rows.filter((row) => row.due_at <= until).reverse();
}

// What the row offers: record it (due within the hour or past), and run a planned irrigation.
export function rowActions(row, body) {
  const due = (body.now || 0) >= row.due_at - (body.early_seconds || 0);
  const started = body.stage_state !== "pending_review";
  const record = due && started;
  const irrigate = record && row.kind === "irrigation" && Boolean(row.seconds) && body.stage_state === "running" && RUNNABLE.has(row.status);
  return { record, irrigate };
}

// After a planned run: done, partial (cut short or not confirmed), or nothing recorded (it never
// reached the device). The server derives the request id from the occurrence.
export function irrigationNotice(answer) {
  const id = (answer && answer.action && answer.action.request_id) || "";
  const task = answer && answer.task;
  if (!task) return { key: "tasks.irrigateUnconfirmed", tone: "error", id };
  if (task.status === "partial") return { key: "tasks.irrigatePartial", tone: "error", id };
  return { key: "tasks.irrigated", tone: "ok", id };
}

function partialText(ctx, record) {
  const why = record.ended_early || "";
  if (typeof record.ran_seconds !== "number") return ctx.t("tasks.partialUnconfirmed", { why });
  return ctx.t("tasks.partialRan", { seconds: Math.round(record.ran_seconds * 10) / 10, why });
}

function statusCell(ctx, row) {
  const pill = h("span", { class: ["pill", PILL[row.status]], text: ctx.t(`tasks.status.${row.status}`) });
  const record = row.record;
  if (!record) return pill;
  const when = record.done_at ? ctx.t("tasks.doneAt", { time: timeText(ctx, record.done_at), who: record.operator }) : ctx.t("tasks.by", { who: record.operator });
  const meta = [h("span", { class: "task-meta", text: when })];
  if (record.outcome === "partial") meta.push(h("span", { class: "task-meta", text: partialText(ctx, record) }));
  return h("span", { class: "cell-stack" }, pill, ...meta);
}

function kindCell(ctx, row) {
  const kind = ctx.t(`tasks.kind.${row.kind}`);
  return row.seconds ? ctx.t("tasks.pumpRun", { kind, seconds: row.seconds }) : kind;
}

function button(label, tone, run, box) {
  const element = h("button", { class: ["button", `button-${tone}`], attrs: { type: "button" }, text: label });
  element.addEventListener("click", async () => {
    box.hidden = true;
    element.disabled = true;
    try {
      await run();
    } catch {
      // already shown under the buttons by wrap()
    } finally {
      element.disabled = false;
    }
  });
  return element;
}

function actionsCell(env, body, row) {
  const { ctx, stage, onChanged } = env;
  const allowed = rowActions(row, body);
  if (!allowed.record) return "—";
  const box = errorBox();
  const base = `/stages/${encodeURIComponent(stage.stage_id)}/manual-tasks`;
  const occurrence = { task_id: row.task_id, due_at: row.due_at };
  const record = (outcome, label) => async () => {
    await ctx.api.post(base, { ...occurrence, outcome }, { action: label });
    ctx.notify(ctx.t("tasks.recorded", { task: row.task_id }), "ok");
    await onChanged();
  };
  const irrigate = async () => {
    const label = ctx.t("tasks.irrigate", { seconds: row.seconds });
    const lines = [ctx.t("tasks.irrigateLine", { seconds: row.seconds }), ctx.t("tasks.irrigateOnSite")];
    if (!(await confirmAction(ctx.t, { title: label, lines, confirmLabel: label }))) return;
    const answer = await ctx.api.post(`${base}/irrigate`, occurrence, { action: label });
    const notice = irrigationNotice(answer);
    ctx.notify(ctx.t(notice.key, { id: notice.id }), notice.tone);
    await onChanged();
  };
  const wrap = (run) => async () => {
    try {
      await run();
    } catch (error) {
      showErrors(box, error, ctx);
      throw error;
    }
  };
  const buttons = [];
  if (allowed.irrigate) buttons.push(button(ctx.t("tasks.irrigate", { seconds: row.seconds }), "primary", wrap(irrigate), box));
  if (!DONE.has(row.status)) buttons.push(button(ctx.t("tasks.markDone"), allowed.irrigate ? "quiet" : "primary", wrap(record("done", ctx.t("tasks.markDone"))), box));
  if (row.status !== "skipped") buttons.push(button(ctx.t("tasks.markSkipped"), "quiet", wrap(record("skipped", ctx.t("tasks.markSkipped"))), box));
  return h("div", { class: "task-actions" }, h("div", { class: "task-buttons" }, buttons), box);
}

export function tasksView(env, body) {
  const { ctx } = env;
  const rows = visibleRows(body);
  if (!rows.length) return note(ctx.t(body.occurrences && body.occurrences.length ? "tasks.noneYet" : "tasks.empty"));
  const columns = [
    { label: ctx.t("tasks.due"), cell: (row) => timeText(ctx, row.due_at) },
    { label: ctx.t("tasks.task"), cell: (row) => h("code", { text: row.task_id }) },
    { label: ctx.t("tasks.kindTitle"), cell: (row) => kindCell(ctx, row) },
    { label: ctx.t("col.state"), cell: (row) => statusCell(ctx, row) },
    { label: ctx.t("tasks.actions"), cell: (row) => actionsCell(env, body, row) },
  ];
  const recent = rows.slice(0, SHOWN_ROWS);
  const older = rows.slice(SHOWN_ROWS);
  const more = older.length
    ? h("details", { class: "tasks-older" }, h("summary", { text: ctx.t("tasks.older", { count: older.length }) }), table(columns, older, { label: ctx.t("tasks.list") }))
    : null;
  return h("div", { class: "tasks" }, note(ctx.t("tasks.lead")), table(columns, recent, { label: ctx.t("tasks.list") }), more);
}
