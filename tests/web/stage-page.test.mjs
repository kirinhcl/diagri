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

// --- final review: a poll that rebuilds the chart or the tasks keeps what the reader opened (F11) --
import { FIXTURES, renderPage } from "./support/render-page.mjs";

const descendantsOf = (node) => [...(node.children || [])].flatMap((child) => [child, ...descendantsOf(child)]);
const classed = (name) => (node) => (node.getAttribute("class") || "").split(/\s+/).includes(name);
const part = (element, name) => descendantsOf(element).find(classed(`stage-part-${name}`));
const folds = (node) => descendantsOf(node).filter((child) => child.localName === "details");

// The running stage page, with the next poll bringing one more sample and a later "now" for the tasks.
const TASKS = FIXTURES["manual-tasks.json"];
const HOURLY = Array.from({ length: 12 }, (_, i) => {
  const due = TASKS.now - (12 - i) * 3600;
  const record = { id: `taskrec_${i}`, task_id: "canopy-photo", kind: "photo", due_at: due, outcome: "done", done_at: due + 60, operator: "dev" };
  return { task_id: "canopy-photo", kind: "photo", due_at: due, make_up_allowed: false, seconds: null, status: "done", record };
});

async function runningStagePage() {
  const stage = { ...FIXTURES["stage.json"], state: "running" };
  const tasks = { ...TASKS, stage_state: "running", occurrences: HOURLY };
  const page = await renderPage("stage", { stageId: stage.stage_id }, { fixtures: { "stage.json": stage, "manual-tasks.json": tasks } });
  const get = page.ctx.api.get;
  page.nextPoll = () => {
    page.ctx.api.get = async (path) => {
      const value = await get(path);
      if (path.includes("/readings")) {
        const last = value.samples[value.samples.length - 1];
        return { ...value, samples: [...value.samples, { ...last, timestamp: last.timestamp + 300 }], total_samples: value.total_samples + 1 };
      }
      return path.endsWith("/manual-tasks") ? { ...value, now: value.now + 120 } : value;
    };
  };
  return page;
}

test("the stage chart's legend and data-table folds stay open when a new sample redraws it", async () => {
  const page = await runningStagePage();
  const readings = part(page.element, "readings");
  const chartFolds = folds(readings).filter((fold) => fold.getAttribute("data-fold"));
  assert.ok(chartFolds.length >= 2, "the chart has a legend and data tables");
  const [legend, table] = [chartFolds.find((fold) => fold.getAttribute("data-fold").endsWith(":legend")), chartFolds.find((fold) => fold.getAttribute("data-fold").endsWith(":table"))];
  legend.setAttribute("open", "");
  table.setAttribute("open", "");
  page.nextPoll();
  await page.refresh();
  const after = folds(readings);
  assert.ok(!after.includes(legend), "the chart was drawn again");
  const open = after.filter((fold) => fold.hasAttribute("open")).map((fold) => fold.getAttribute("data-fold"));
  assert.deepEqual(open.sort(), [legend.getAttribute("data-fold"), table.getAttribute("data-fold")].sort());
});

test("the tasks' row details, earlier tasks and rules stay open when the minute turns", async () => {
  const page = await runningStagePage();
  const tasks = part(page.element, "tasks");
  const rules = folds(tasks).find(classed("tasks-rules"));
  const older = folds(tasks).find(classed("tasks-older"));
  const [rowFold, otherRow] = folds(tasks).filter(classed("tech-details"));
  assert.ok(rules && older && rowFold && otherRow);
  for (const fold of [rules, older, rowFold]) fold.setAttribute("open", "");
  const rowText = rowFold.textContent;
  page.nextPoll();
  await page.refresh();
  const after = folds(tasks);
  assert.ok(!after.includes(rules), "the tasks were drawn again");
  assert.ok(after.find(classed("tasks-rules")).hasAttribute("open"));
  assert.ok(after.find(classed("tasks-older")).hasAttribute("open"));
  const openRows = after.filter(classed("tech-details")).filter((fold) => fold.hasAttribute("open"));
  assert.deepEqual(openRows.map((fold) => fold.textContent), [rowText], "only the same occurrence's details are open again");
});
