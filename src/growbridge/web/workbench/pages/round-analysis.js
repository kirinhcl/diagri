// The confirmatory analysis of a round's protocol: the frozen script, its snapshots, and the two writes.
// Most rounds never need it, so the whole block is folded until asked for.
import { ApiError } from "../api.js";
import { labelOr } from "../i18n.js";
import { h } from "../ui/dom.js";
import { jsonEditor, simpleForm } from "../ui/forms.js";
import { displayName, nameDetails } from "../ui/names.js";
import { afterWrite, errorParts, keyValues, note, techDetails, timeText } from "../ui/section.js";
import { table } from "../ui/table.js";

const array = (value) => (Array.isArray(value) ? value : []);
const STATE_KEYS = { notStarted: "analysis.state.notStarted", locked: "analysis.state.locked", ran: "analysis.state.ran" };
// The last run's answer, shown once after the page reloads; never kept for another round.
let lastRun = null;

async function readAnalysis(ctx, round) {
  const path = `/protocols/${encodeURIComponent(round.protocol_id)}/analysis?project_id=${encodeURIComponent(round.project_id)}`;
  try {
    return { analysis: await ctx.api.get(path), error: null };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    return { analysis: null, error };
  }
}

// Where the analysis stands, in one word: no script yet, a script frozen, or a run on record.
export function analysisState(analysis) {
  if (!analysis.frozen) return "notStarted";
  const ran = array(analysis.snapshots).some((row) => row.run_status && row.run_status !== "none");
  return ran ? "ran" : "locked";
}

// When and by whom the script was frozen; its text and fingerprint are folded away.
function frozenView(ctx, analysis) {
  const frozen = analysis.frozen;
  if (!frozen) return note(ctx.t("analysis.notFrozen"));
  const script = ctx.t("analysis.scriptFold");
  return [
    keyValues([
      [ctx.t("analysis.frozenAt"), timeText(ctx, frozen.frozen_at)],
      [ctx.t("analysis.frozenBy"), frozen.frozen_by],
    ]),
    techDetails(ctx.t, [[ctx.t("analysis.script"), frozen.script]], { summary: script }),
    techDetails(ctx.t, [[ctx.t("analysis.sha"), frozen.script_sha256]]),
  ];
}

function snapshotsView(ctx, analysis) {
  const snapshots = array(analysis.snapshots);
  if (!snapshots.length) return note(ctx.t("analysis.noSnapshots"));
  const name = (row) => h("div", { class: "cell-stack" }, displayName(ctx, "snapshot", row), techDetails(ctx.t, nameDetails(row, ctx.t)));
  const columns = [
    { label: ctx.t("analysis.snapshot"), cell: name },
    { label: ctx.t("analysis.complete"), cell: (row) => ctx.t(row.complete ? "common.yes" : "common.no") },
    { label: ctx.t("analysis.runStatus"), cell: (row) => labelOr(ctx.t, "analysis.runState", row.run_status) },
  ];
  return table(columns, snapshots, { label: ctx.t("analysis.snapshots") });
}

function freezeEditor(ctx, round) {
  const submitLabel = ctx.t("analysis.freeze");
  const onSubmit = async (body) => {
    await ctx.api.post(`/protocols/${encodeURIComponent(round.protocol_id)}/analysis`, body, { action: submitLabel });
    afterWrite(ctx);
  };
  const value = { project_id: round.project_id, script: "" };
  const label = ctx.t("analysis.freezeJson");
  return jsonEditor({ label, value, submitLabel, onSubmit, draftKey: `freeze:${round.protocol_id}`, ctx });
}

function runForm(ctx, round, analysis) {
  const submitLabel = ctx.t("analysis.run");
  const snapshots = array(analysis.snapshots);
  const label = ctx.t("analysis.snapshot");
  const options = snapshots.map((row) => ({ value: row.snapshot_id, label: displayName(ctx, "snapshot", row) }));
  const field = snapshots.length
    ? { name: "snapshot_id", label, type: "select", options, required: true }
    : { name: "snapshot_id", label, type: "text", required: true };
  const onSubmit = async ({ snapshot_id: snapshotId }) => {
    const body = { project_id: round.project_id, protocol_id: round.protocol_id, snapshot_id: snapshotId };
    const run = await ctx.api.post("/analysis/runs", body, { action: submitLabel });
    lastRun = { roundId: round.round_id, run };
    afterWrite(ctx);
  };
  return simpleForm({ fields: [field], submitLabel, onSubmit, draftKey: `run:${round.round_id}`, ctx });
}

// One run's answer: its status in words; its id, exit code and output in the details.
export function runView(ctx, run) {
  return h(
    "div",
    { class: "run-result" },
    keyValues([
      [ctx.t("analysis.runStatus"), labelOr(ctx.t, "analysis.runState", run.status)],
      [ctx.t("analysis.timedOut"), ctx.t(run.timed_out ? "common.yes" : "common.no")],
    ]),
    techDetails(ctx.t, [
      [ctx.t("analysis.runId"), run.run_id],
      [ctx.t("analysis.exitCode"), run.exit_code],
      [ctx.t("analysis.stdout"), run.stdout],
      [ctx.t("analysis.stderr"), run.stderr],
    ]),
  );
}

function runResult(ctx, round) {
  if (!lastRun || lastRun.roundId !== round.round_id) return null;
  const { run } = lastRun;
  lastRun = null;
  return runView(ctx, run);
}

// The server shows the protocol's latest version; null when that is the round's own version.
export function versionMismatch(analysis, round) {
  return analysis.version === round.protocol_version ? null : { latest: analysis.version, round: round.protocol_version };
}

// The block, closed until opened: a <details> titled like a section heading.
function fold(ctx, ...children) {
  const summary = h("summary", { class: "block-head" }, h("h2", { text: ctx.t("analysis.title") }));
  return h("details", { class: "block analysis-fold" }, summary, h("div", { class: "analysis-body" }, ...children));
}

function facts(ctx, round, analysis) {
  return keyValues([
    [ctx.t("col.state"), ctx.t(STATE_KEYS[analysisState(analysis)])],
    [ctx.t("col.protocol"), ctx.t("round.protocolValue", { id: analysis.protocol_id, v: analysis.version })],
    [ctx.t("analysis.roundVersion"), ctx.t("analysis.versionValue", { v: round.protocol_version })],
    [ctx.t("analysis.started"), ctx.t(analysis.started ? "common.yes" : "common.no")],
  ]);
}

export async function analysisSection(ctx, round) {
  const { analysis, error } = await readAnalysis(ctx, round);
  if (!analysis) return fold(ctx, h("div", { class: "form-status form-status-error" }, errorParts(ctx, error)));
  const mismatch = versionMismatch(analysis, round);
  const status = (text) => h("div", { class: "form-status form-status-error", attrs: { role: "status" } }, h("p", { text }));
  return fold(
    ctx,
    mismatch ? status(ctx.t("analysis.otherVersion", mismatch)) : null,
    facts(ctx, round, analysis),
    frozenView(ctx, analysis),
    analysis.frozen ? note(ctx.t("analysis.frozenNote")) : freezeEditor(ctx, round),
    snapshotsView(ctx, analysis),
    runForm(ctx, round, analysis),
    runResult(ctx, round),
  );
}
