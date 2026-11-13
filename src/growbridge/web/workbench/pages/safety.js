// The approved safety limits and an editor to approve a new set. Approval lists every change first.
import { ApiError } from "../api.js";
import { configDiff } from "../diff.js";
import { confirmAction } from "../ui/dialog.js";
import { clear, h } from "../ui/dom.js";
import { errorLines, jsonEditor } from "../ui/forms.js";
import { keyValues, note, pageHead, section, timeText } from "../ui/section.js";
import { table } from "../ui/table.js";
import { baselineChanged, diffLines, visibleChanges } from "./safety-diff.js";
import { safetySkeleton } from "./safety-skeleton.js";

const array = (value) => (Array.isArray(value) ? value : []);

function rulesTable(ctx, rules) {
  const columns = [
    { label: ctx.t("col.id"), cell: (row) => h("code", { text: row.id }) },
    { label: ctx.t("safety.sensor"), cell: (row) => `${row.sensor} (${row.unit})` },
    { label: ctx.t("safety.trigger"), cell: (row) => `${row.trigger.op} ${row.trigger.value}` },
    { label: ctx.t("safety.duration"), cell: (row) => String(row.duration_seconds) },
    { label: ctx.t("safety.validity"), cell: (row) => String(row.validity_seconds) },
    { label: ctx.t("safety.action"), cell: (row) => `${row.action.channel} → ${row.action.level}` },
  ];
  return table(columns, rules, { label: ctx.t("safety.rules") });
}

function currentView(ctx, config) {
  if (!config) return note(ctx.t("safety.none"));
  const facts = keyValues([
    [ctx.t("col.version"), String(config.version)],
    [ctx.t("safety.approvedBy"), config.approved_by],
    [ctx.t("safety.approvedAt"), timeText(ctx, config.approved_at)],
  ]);
  const rules = array(config.rules);
  return h("div", { class: "review" }, facts, rules.length ? rulesTable(ctx, rules) : note(ctx.t("safety.noRules")));
}

// The editor's own context: a refusal (409 included) re-reads only the current limits, never the editor.
// The form says "Done." after onSubmit returns, so that text is made to tell what really happened.
function editorContext(ctx, refreshCurrent, outcome) {
  const t = (key, values) => {
    if (key === "form.done") return outcome.text;
    if (key === "error.title" && outcome.refused) return ctx.t("safety.notApproved");
    return ctx.t(key, values);
  };
  return { ...ctx, t, reload: refreshCurrent };
}

// Not approved, and said in the refusal style (not as a success): the form shows a thrown error that way.
function notApproved(ctx, outcome, key) {
  outcome.refused = true;
  return new ApiError(0, "not_approved", ctx.t(key));
}

// The limits are read again right before the diff and again after the operator confirms; a set that
// changed in between is never overwritten, because the write replaces the whole config.
function approver(ctx, state, outcome, readCurrent, refreshCurrent) {
  const label = ctx.t("safety.approve");
  return async (edited) => {
    outcome.refused = false;
    await readCurrent();
    const baseline = state.current;
    const lines = diffLines(visibleChanges(configDiff(baseline || safetySkeleton(), edited)), ctx.t);
    const shown = lines.length ? lines : [ctx.t("safety.noChanges")];
    if (!(await confirmAction(ctx.t, { title: ctx.t("safety.confirmTitle"), lines: shown, confirmLabel: label }))) {
      throw notApproved(ctx, outcome, "safety.cancelled");
    }
    await readCurrent();
    if (baselineChanged(baseline, state.current)) throw notApproved(ctx, outcome, "safety.changedMeanwhile");
    const done = await ctx.api.post("/safety/approve", { config: edited }, { action: label });
    outcome.text = ctx.t("safety.approved", { right: done.protection_right });
    await refreshCurrent(); // the approval itself has succeeded; a failed re-read is only a notice
  };
}

export async function render(ctx) {
  const state = { current: null };
  const currentBox = h("div", { class: "safety-current" });
  const readCurrent = async () => {
    const data = await ctx.api.get("/safety");
    state.current = (data && data.safety) || null;
    clear(currentBox).append(currentView(ctx, state.current));
  };
  const refreshCurrent = () =>
    readCurrent().catch((error) => ctx.notify(errorLines(error, ctx.lang, ctx.t).join(" "), "error"));
  await readCurrent();
  const outcome = { text: ctx.t("form.done"), refused: false };
  const editor = jsonEditor({
    label: ctx.t("safety.json"),
    value: state.current || safetySkeleton(),
    submitLabel: ctx.t("safety.approve"),
    onSubmit: approver(ctx, state, outcome, readCurrent, refreshCurrent),
    draftKey: "safety",
    ctx: editorContext(ctx, refreshCurrent, outcome),
  });
  const lead = state.current ? ctx.t("safety.editLead") : ctx.t("safety.skeletonLead");
  const element = h(
    "div",
    { class: "page safety" },
    pageHead(ctx.t("nav.safety"), ctx.t("safety.lead")),
    section(ctx.t("safety.current"), currentBox),
    section(ctx.t("safety.edit"), note(lead), editor),
  );
  return { element };
}
