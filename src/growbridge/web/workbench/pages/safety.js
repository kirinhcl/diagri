// The approved safety limits and an editor to approve a new set. Approval lists every change first.
import { ApiError } from "../api.js";
import { hasLabel } from "../i18n.js";
import { configDiff } from "../diff.js";
import { confirmAction } from "../ui/dialog.js";
import { clear, h } from "../ui/dom.js";
import { errorLines, jsonEditor } from "../ui/forms.js";
import { keyValues, note, pageHead, section, techDetails, timeText } from "../ui/section.js";
import { baselineChanged, diffLines, visibleChanges } from "./safety-diff.js";
import { frozenRows } from "./safety-frozen.js";
import { safetySkeleton } from "./safety-skeleton.js";
import { exactText, frozenLine, ruleSentence } from "./safety-text.js";

export { ruleSentence, unitText } from "./safety-text.js";

const array = (value) => (Array.isArray(value) ? value : []);

function ruleItem(ctx, rule) {
  const { t } = ctx;
  const details = techDetails(t, [
    [t("col.id"), rule?.id],
    [t("safety.sensor"), rule?.sensor],
    [t("safety.trigger"), rule?.trigger?.op],
    [t("safety.action"), rule?.action?.channel],
  ]);
  return h("li", { class: "safety-rule" }, h("p", { text: ruleSentence(t, rule) }), details);
}

function rulesList(ctx, rules) {
  return h("ul", { class: "safety-rules", attrs: { "aria-label": ctx.t("safety.rules") } }, rules.map((rule) => ruleItem(ctx, rule)));
}

function frozenView(ctx, frozen) {
  const rows = frozenRows(frozen);
  const seconds = frozen?.max_gap_seconds;
  const gap = keyValues([[ctx.t("safety.frozenGap"), exactText(ctx.t, seconds)]]);
  const list = rows.length
    ? h("ul", { class: "safety-frozen" }, rows.map(([sensor, minutes]) => h("li", { text: frozenLine(ctx.t, sensor, minutes) })))
    : note(ctx.t("safety.frozenNone"));
  const unknown = rows.filter(([sensor]) => !hasLabel(ctx.t, "metric", sensor)).map(([sensor]) => [ctx.t("safety.sensor"), sensor]);
  return h("div", { class: "frozen" }, h("h3", { text: ctx.t("safety.frozen") }), gap, list, techDetails(ctx.t, unknown));
}

function currentView(ctx, config) {
  if (!config) return note(ctx.t("safety.none"));
  const facts = keyValues([
    [ctx.t("col.version"), String(config.version)],
    [ctx.t("safety.approvedBy"), config.approved_by],
    [ctx.t("safety.approvedAt"), timeText(ctx, config.approved_at)],
  ]);
  const rules = array(config.rules);
  const ruleList = rules.length ? rulesList(ctx, rules) : note(ctx.t("safety.noRules"));
  return h("div", { class: "review" }, facts, ruleList, frozenView(ctx, config.frozen));
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
    const start = baseline || safetySkeleton();
    const lines = diffLines(visibleChanges(configDiff(start, edited)), ctx.t, { before: start, after: edited });
    const shown = lines.length ? lines : [ctx.t("safety.noChanges")];
    if (!(await confirmAction(ctx.t, { title: ctx.t("safety.confirmTitle"), lines: shown, confirmLabel: label }))) {
      throw notApproved(ctx, outcome, "safety.cancelled");
    }
    await readCurrent();
    if (baselineChanged(baseline, state.current)) throw notApproved(ctx, outcome, "safety.changedMeanwhile");
    await ctx.api.post("/safety/approve", { config: edited }, { action: label });
    outcome.text = ctx.t("safety.approved");
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
    readCurrent().catch((error) => ctx.notify(errorLines(error, ctx.lang, ctx.t, ctx).join(" "), "error"));
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
