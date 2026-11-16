// Open and stuck compute attempts; a stuck one can be settled by a person, with a reason, after a confirmation.
import { confirmAction } from "../ui/dialog.js";
import { clear, h } from "../ui/dom.js";
import { afterWrite, errorBox, note, section, showErrors, techDetails, timeText } from "../ui/section.js";
import { shortDigest } from "../format.js";
import { displayName } from "../ui/names.js";
import { statePill } from "../ui/status.js";
import { stuckSentences } from "./compute-stuck.js";
import { table } from "../ui/table.js";

const array = (value) => (Array.isArray(value) ? value : []);

// A task as people read it: the first 8 characters of its id after the prefix, the same everywhere.
export function taskLabel(ctx, taskId) {
  const id = String(taskId ?? "");
  return ctx.t("compute.taskLabel", { fingerprint: shortDigest(id.slice(id.indexOf("_") + 1)) });
}

function settleLines(ctx, row, reason) {
  return [
    ctx.t("compute.settleWhat", { attempt: displayName(ctx, "attempt", row), task: taskLabel(ctx, row.task_id) }),
    ctx.t("compute.settleCharge"),
    ctx.t("compute.settleReason", { reason }),
  ];
}

function settleControl(ctx, row) {
  const label = ctx.t("compute.settle");
  const inputAttrs = { type: "text", maxlength: 500, "aria-label": ctx.t("compute.reason") };
  const input = h("input", { class: "input", attrs: inputAttrs });
  const button = h("button", { class: "button button-danger", attrs: { type: "button" }, text: label });
  const box = errorBox();
  button.addEventListener("click", async () => {
    box.hidden = true;
    const reason = input.value.trim();
    if (!reason) {
      clear(box).append(h("p", { text: ctx.t("compute.reasonRequired") }));
      box.hidden = false;
      return;
    }
    const title = ctx.t("compute.settleTitle");
    if (!(await confirmAction(ctx.t, { title, lines: settleLines(ctx, row, reason), confirmLabel: label }))) return;
    button.disabled = true;
    try {
      await ctx.api.post(`/compute/attempts/${encodeURIComponent(row.attempt_id)}/settle`, { reason }, { action: label });
    } catch (error) {
      showErrors(box, error, ctx);
      button.disabled = false;
      return;
    }
    afterWrite(ctx, ctx.t("compute.settled", { id: displayName(ctx, "attempt", row) }));
  });
  return h("div", { class: "action" }, h("div", { class: "inline-control" }, input, button), box);
}

// The attempt by its submission time, the task it belongs to, and its ids one click away.
function attemptCell(ctx, row, extra = []) {
  const ids = [[ctx.t("tech.id.attempt_id"), row.attempt_id], [ctx.t("tech.id.task_id"), row.task_id], ...extra];
  return h("div", { class: "cell-stack" }, displayName(ctx, "attempt", row), techDetails(ctx.t, ids));
}

function jobsTable(ctx, jobs) {
  const columns = [
    { label: ctx.t("compute.attempt"), cell: (row) => attemptCell(ctx, row, [[ctx.t("compute.remoteJob"), row.remote_job_id]]) },
    { label: ctx.t("compute.task"), cell: (row) => taskLabel(ctx, row.task_id) },
    { label: ctx.t("compute.template"), cell: (row) => row.template_id },
    { label: ctx.t("compute.phase"), cell: (row) => statePill(ctx.t, row.phase) },
    { label: ctx.t("col.created"), cell: (row) => timeText(ctx, row.created_at) },
  ];
  return table(columns, jobs, { label: ctx.t("compute.open") });
}

// What happened and what to do next, with every technical detail in one fold.
function whyCell(ctx, row) {
  const { lines, entries } = stuckSentences(ctx, row);
  return h("div", { class: "cell-stack" }, lines.map((line) => h("p", { text: line })), techDetails(ctx.t, entries));
}

function stuckTable(ctx, stuck) {
  const columns = [
    { label: ctx.t("compute.attempt"), cell: (row) => attemptCell(ctx, row) },
    { label: ctx.t("compute.task"), cell: (row) => taskLabel(ctx, row.task_id) },
    { label: ctx.t("compute.phase"), cell: (row) => statePill(ctx.t, row.phase) },
    { label: ctx.t("compute.why"), cell: (row) => whyCell(ctx, row) },
    { label: ctx.t("compute.since"), cell: (row) => timeText(ctx, row.since) },
    { label: ctx.t("compute.settleColumn"), cell: (row) => settleControl(ctx, row) },
  ];
  return table(columns, stuck, { label: ctx.t("compute.stuck") });
}

export function attemptSections(ctx, overview) {
  const jobs = array(overview.jobs);
  const stuck = array(overview.stuck);
  return [
    section(ctx.t("compute.open"), jobs.length ? jobsTable(ctx, jobs) : note(ctx.t("compute.openEmpty"))),
    section(ctx.t("compute.stuck"), stuck.length ? stuckTable(ctx, stuck) : note(ctx.t("compute.stuckEmpty"))),
  ];
}
