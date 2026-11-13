import assert from "node:assert/strict";
import test from "node:test";

import { coalesce } from "../../src/growbridge/web/workbench/pages/stage.js";
import { detailText, timeline } from "../../src/growbridge/web/workbench/pages/stage-history.js";
import { correctionLinks } from "../../src/growbridge/web/workbench/pages/stage-measurements.js";

// A run that waits until the test lets it finish.
function gatedRuns() {
  const runs = { started: 0, gates: [] };
  runs.fn = () => {
    runs.started += 1;
    return new Promise((resolve, reject) => runs.gates.push({ resolve, reject }));
  };
  runs.finish = async (index, error) => {
    const gate = runs.gates[index];
    if (error) gate.reject(error);
    else gate.resolve();
    await new Promise((resolve) => setImmediate(resolve)); // after every pending promise job
  };
  return runs;
}

test("coalesce runs once more after the current run, for every call made meanwhile", async () => {
  const runs = gatedRuns();
  const refresh = coalesce(runs.fn);
  const first = refresh();
  const second = refresh();
  const third = refresh();
  assert.equal(runs.started, 1);
  assert.equal(second, third);
  await runs.finish(0);
  await first;
  assert.equal(runs.started, 2); // the queued run reads again after the one in flight
  await runs.finish(1);
  await second;
  assert.equal(runs.started, 2);
});

test("coalesce starts afresh once everything settled, even after a failure", async () => {
  const runs = gatedRuns();
  const refresh = coalesce(runs.fn);
  const failing = assert.rejects(refresh(), /offline/);
  await runs.finish(0, new Error("offline"));
  await failing;
  const next = refresh();
  assert.equal(runs.started, 2);
  await runs.finish(1);
  await next;
});

test("a call queued behind a failed run still runs", async () => {
  const runs = gatedRuns();
  const refresh = coalesce(runs.fn);
  refresh().catch(() => {});
  const queued = refresh();
  await runs.finish(0, new Error("offline"));
  assert.equal(runs.started, 2);
  await runs.finish(1);
  await queued;
});

const move = (at, from, to, event = "e", detail = {}) => ({ at, from, to, event, detail });
const act = (at, kind, extra = {}) => ({ stage_id: "s1", at, kind, operator: "ann", ...extra });

test("timeline merges transitions and interventions by time", () => {
  const entries = timeline(
    [move(10, "pending_review", "running"), move(30, "running", "manual")],
    [act(20, "takeover"), act(40, "accepted", { differences: [] })],
  );
  assert.deepEqual(
    entries.map((entry) => [entry.at, entry.type]),
    [
      [10, "transition"],
      [20, "intervention"],
      [30, "transition"],
      [40, "intervention"],
    ],
  );
});

test("timeline keeps a transition before an intervention at the same time", () => {
  const entries = timeline([move(5, "running", "manual")], [act(5, "takeover")]);
  assert.deepEqual(
    entries.map((entry) => entry.type),
    ["transition", "intervention"],
  );
});

test("an intervention's detail leaves out what the line already says", () => {
  const [entry] = timeline([], [act(1, "accepted", { differences: [], accepted: true })]);
  assert.deepEqual(entry.detail, { differences: [], accepted: true });
  assert.equal(entry.operator, "ann");
  assert.equal(entry.kind, "accepted");
});

test("timeline accepts missing lists and does not change its input", () => {
  assert.deepEqual(timeline(undefined, null), []);
  const history = [move(2, "a", "b"), move(1, "b", "c")];
  const copy = structuredClone(history);
  timeline(history, []);
  assert.deepEqual(history, copy);
});

test("detailText shows each field once, nested values as JSON", () => {
  assert.equal(detailText({}), "");
  assert.equal(detailText(null), "");
  assert.equal(detailText({ reason: "dry", by: "ann" }), "reason: dry · by: ann");
  assert.equal(detailText({ differences: [{ channel: "light" }] }), 'differences: [{"channel":"light"}]');
});

test("correctionLinks marks both ends of each correction", () => {
  const links = correctionLinks([
    { id: "m1", corrects: null },
    { id: "m2", corrects: "m1" },
    { id: "m3", corrects: "m2" },
    { id: "m4", corrects: "m1" },
  ]);
  assert.deepEqual(links.get("m1"), { corrects: null, correctedBy: ["m2", "m4"] });
  assert.deepEqual(links.get("m2"), { corrects: "m1", correctedBy: ["m3"] });
  assert.deepEqual(links.get("m3"), { corrects: "m2", correctedBy: [] });
  assert.deepEqual(links.get("m4"), { corrects: "m1", correctedBy: [] });
});

test("a correction of a record not in the list still names it", () => {
  const links = correctionLinks([{ id: "m9", corrects: "gone" }]);
  assert.deepEqual(links.get("m9"), { corrects: "gone", correctedBy: [] });
  assert.equal(links.has("gone"), false);
  assert.equal(correctionLinks(undefined).size, 0);
});
