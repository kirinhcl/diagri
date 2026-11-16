import assert from "node:assert/strict";
import test from "node:test";

import { coalesce, FINISHED_REREAD_SECONDS, frozenReadings, keptIsFresh } from "../../src/growbridge/web/workbench/pages/stage.js";
import { timeline } from "../../src/growbridge/web/workbench/pages/stage-history.js";
import { correctionLinks } from "../../src/growbridge/web/workbench/pages/stage-measurements.js";

const finished = { state: "ended", state_at: 200 };
const windowTo = (end) => ({ value: { samples: [], window: { start: 100, end } } });

test("readings are kept only when their window ends at the stage's state_at", () => {
  const read = windowTo(200);
  assert.equal(frozenReadings(finished, read), read);
  assert.equal(frozenReadings({ state: "stopped", state_at: 200 }, read), read);
  assert.equal(frozenReadings(finished, windowTo(150)), null); // a stale running-window curve
  assert.equal(frozenReadings({ state: "running", state_at: 200 }, read), null);
  assert.equal(frozenReadings(finished, { error: new Error("x") }), null);
  assert.equal(frozenReadings(finished, undefined), null);
  assert.equal(frozenReadings(finished, { value: { samples: [], window: null } }), null);
  assert.equal(frozenReadings({ state: "ended" }, windowTo(200)), null); // no state_at to prove it
});

test("kept readings are read again after five minutes", () => {
  assert.equal(FINISHED_REREAD_SECONDS, 300);
  assert.equal(keptIsFresh(null, 1000), false);
  assert.equal(keptIsFresh(1000, 1000 + 299_999), true);
  assert.equal(keptIsFresh(1000, 1000 + 300_000), false);
});

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

test("timeline merges transitions and interventions by time, newest first", () => {
  const entries = timeline(
    [move(10, "pending_review", "running"), move(30, "running", "manual")],
    [act(20, "takeover"), act(40, "accepted", { differences: [] })],
  );
  assert.deepEqual(
    entries.map((entry) => [entry.at, entry.type]),
    [
      [40, "intervention"],
      [30, "transition"],
      [20, "intervention"],
      [10, "transition"],
    ],
  );
});

test("timeline puts an intervention before a transition of the same second", () => {
  const entries = timeline([move(5, "running", "manual")], [act(5, "takeover")]);
  assert.deepEqual(
    entries.map((entry) => entry.type),
    ["intervention", "transition"],
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
