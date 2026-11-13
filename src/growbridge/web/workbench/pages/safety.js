// The approved safety limits and an editor to approve a new set. Approval lists every change first.
import { configDiff } from "../diff.js";
import { confirmAction } from "../ui/dialog.js";
import { clear, h } from "../ui/dom.js";
import { errorLines, jsonEditor } from "../ui/forms.js";
import { keyValues, note, pageHead, section, timeText } from "../ui/section.js";
import { table } from "../ui/table.js";
import { diffLines, visibleChanges } from "./safety-diff.js";
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
  const t = (key, values) => (key === "form.done" ? outcome.text : ctx.t(key, values));
  return { ...ctx, t, reload: refreshCurrent };
}

function approver(ctx, state, outcome, refreshCurrent) {
  const label = ctx.t("safety.approve");
  return async (edited) => {
    const baseline = state.current || safetySkeleton();
    const lines = diffLines(visibleChanges(configDiff(baseline, edited)), ctx.t);
    const shown = lines.length ? lines : [ctx.t("safety.noChanges")];
    if (!(await confirmAction(ctx.t, { title: ctx.t("safety.confirmTitle"), lines: shown, confirmLabel: label }))) {
      outcome.text = ctx.t("safety.cancelled");
      return;
    }
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
  const outcome = { text: ctx.t("form.done") };
  const editor = jsonEditor({
    label: ctx.t("safety.json"),
    value: state.current || safetySkeleton(),
    submitLabel: ctx.t("safety.approve"),
    onSubmit: approver(ctx, state, outcome, refreshCurrent),
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
