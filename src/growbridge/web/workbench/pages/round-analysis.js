// The confirmatory analysis of a round's protocol: the frozen script, its snapshots, and the two writes.
import { ApiError } from "../api.js";
import { h } from "../ui/dom.js";
import { jsonEditor, simpleForm } from "../ui/forms.js";
import { afterWrite, codeBlock, errorParts, keyValues, note, section, timeText } from "../ui/section.js";
import { table } from "../ui/table.js";

const array = (value) => (Array.isArray(value) ? value : []);
const orNull = (value) => (value === null || value === undefined ? null : String(value));
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

function frozenView(ctx, analysis) {
  const frozen = analysis.frozen;
  if (!frozen) return note(ctx.t("analysis.notFrozen"));
  return h(
    "div",
    {},
    keyValues([
      [ctx.t("analysis.sha"), h("code", { text: frozen.script_sha256 })],
      [ctx.t("analysis.frozenAt"), timeText(ctx, frozen.frozen_at)],
      [ctx.t("analysis.frozenBy"), frozen.frozen_by],
    ]),
    frozen.script ? codeBlock(frozen.script) : null,
  );
}

function snapshotsView(ctx, analysis) {
  const snapshots = array(analysis.snapshots);
  if (!snapshots.length) return note(ctx.t("analysis.noSnapshots"));
  const columns = [
    { label: ctx.t("analysis.snapshot"), cell: (row) => h("code", { text: row.snapshot_id }) },
    { label: ctx.t("analysis.experiment"), cell: (row) => row.experiment_id },
    { label: ctx.t("analysis.complete"), cell: (row) => ctx.t(row.complete ? "common.yes" : "common.no") },
    { label: ctx.t("analysis.runStatus"), cell: (row) => orNull(row.run_status) || "—" },
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
  const options = snapshots.map((row) => row.snapshot_id);
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

function runResult(ctx, round) {
  if (!lastRun || lastRun.roundId !== round.round_id) return null;
  const { run } = lastRun;
  lastRun = null;
  return h(
    "div",
    { class: "run-result" },
    keyValues([
      [ctx.t("analysis.runId"), h("code", { text: run.run_id })],
      [ctx.t("analysis.runStatus"), String(run.status)],
      [ctx.t("analysis.exitCode"), orNull(run.exit_code)],
      [ctx.t("analysis.timedOut"), ctx.t(run.timed_out ? "common.yes" : "common.no")],
    ]),
    run.stdout ? codeBlock(run.stdout) : null,
    run.stderr ? codeBlock(run.stderr) : null,
  );
}

// The server shows the protocol's latest version; null when that is the round's own version.
export function versionMismatch(analysis, round) {
  return analysis.version === round.protocol_version ? null : { latest: analysis.version, round: round.protocol_version };
}

export async function analysisSection(ctx, round) {
  const { analysis, error } = await readAnalysis(ctx, round);
  const title = ctx.t("analysis.title");
  if (!analysis) return section(title, h("div", { class: "form-status form-status-error" }, errorParts(ctx, error)));
  const mismatch = versionMismatch(analysis, round);
  return section(
    title,
    mismatch ? h("div", { class: "form-status form-status-error", attrs: { role: "status" } }, h("p", { text: ctx.t("analysis.otherVersion", mismatch) })) : null,
    keyValues([
      [ctx.t("col.protocol"), `${analysis.protocol_id} v${analysis.version}`],
      [ctx.t("analysis.roundVersion"), `v${round.protocol_version}`],
      [ctx.t("analysis.started"), ctx.t(analysis.started ? "common.yes" : "common.no")],
    ]),
    frozenView(ctx, analysis),
    analysis.frozen ? note(ctx.t("analysis.frozenNote")) : freezeEditor(ctx, round),
    snapshotsView(ctx, analysis),
    runForm(ctx, round, analysis),
    runResult(ctx, round),
  );
}
