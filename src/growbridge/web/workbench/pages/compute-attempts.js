// Open and stuck compute attempts; a stuck one can be settled by a person, with a reason, after a confirmation.
import { confirmAction } from "../ui/dialog.js";
import { clear, h } from "../ui/dom.js";
import { afterWrite, errorBox, note, section, showErrors, timeText } from "../ui/section.js";
import { statePill } from "../ui/status.js";
import { table } from "../ui/table.js";

const array = (value) => (Array.isArray(value) ? value : []);

function settleLines(ctx, row, reason) {
  return [
    ctx.t("compute.settleWhat", { id: row.attempt_id, task: row.task_id }),
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
    afterWrite(ctx, ctx.t("compute.settled", { id: row.attempt_id }));
  });
  return h("div", { class: "action" }, h("div", { class: "inline-control" }, input, button), box);
}

function jobsTable(ctx, jobs) {
  const columns = [
    { label: ctx.t("compute.attempt"), cell: (row) => h("code", { text: row.attempt_id }) },
    { label: ctx.t("compute.task"), cell: (row) => row.task_id },
    { label: ctx.t("compute.template"), cell: (row) => row.template_id },
    { label: ctx.t("compute.phase"), cell: (row) => statePill(ctx.t, row.phase) },
    { label: ctx.t("compute.remoteJob"), cell: (row) => row.remote_job_id || "—" },
    { label: ctx.t("col.created"), cell: (row) => timeText(ctx, row.created_at) },
  ];
  return table(columns, jobs, { label: ctx.t("compute.open") });
}

function stuckTable(ctx, stuck) {
  const columns = [
    { label: ctx.t("compute.attempt"), cell: (row) => h("code", { text: row.attempt_id }) },
    { label: ctx.t("compute.task"), cell: (row) => row.task_id },
    { label: ctx.t("compute.phase"), cell: (row) => statePill(ctx.t, row.phase) },
    { label: ctx.t("compute.why"), cell: (row) => row.reason },
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
