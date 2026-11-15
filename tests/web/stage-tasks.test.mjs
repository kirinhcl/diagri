import assert from "node:assert/strict";
import test from "node:test";

import { AHEAD_SECONDS, irrigationNotice, rowActions, visibleRows } from "../../src/growbridge/web/workbench/pages/stage-tasks.js";

const NOW = 100_000;
const row = (fields) => ({ task_id: "water", kind: "irrigation", seconds: 5, status: "open", record: null, due_at: NOW, ...fields });
const body = (fields = {}) => ({ now: NOW, early_seconds: 3600, stage_state: "running", occurrences: [], ...fields });

test("rows are listed newest first and at most a day ahead", () => {
  const rows = [row({ due_at: NOW - 10 }), row({ due_at: NOW + 10 }), row({ due_at: NOW + AHEAD_SECONDS + 1 })];
  assert.deepEqual(visibleRows(body({ occurrences: rows })).map((r) => r.due_at), [NOW + 10, NOW - 10]);
});

test("a planned irrigation can be started only while the stage runs and it is not done", () => {
  assert.deepEqual(rowActions(row(), body()), { record: true, irrigate: true });
  assert.deepEqual(rowActions(row({ status: "done" }), body()), { record: true, irrigate: false });
  assert.deepEqual(rowActions(row(), body({ stage_state: "paused" })), { record: true, irrigate: false });
  assert.deepEqual(rowActions(row({ seconds: null }), body()), { record: true, irrigate: false });
  assert.deepEqual(rowActions(row({ kind: "photo", seconds: null }), body()), { record: true, irrigate: false });
});

test("a planned irrigation is offered only while it is upcoming or open", () => {
  // the server runs the pump once per occurrence and never after its deadline ("missed")
  for (const status of ["missed", "skipped", "late"]) {
    assert.equal(rowActions(row({ status }), body()).irrigate, false, status);
  }
  assert.equal(rowActions(row({ status: "upcoming", due_at: NOW + 60 }), body()).irrigate, true);
});

test("a task more than an hour away cannot be recorded yet", () => {
  assert.deepEqual(rowActions(row({ due_at: NOW + 3601 }), body()), { record: false, irrigate: false });
  assert.deepEqual(rowActions(row({ due_at: NOW + 3600 }), body()).record, true);
});

test("the notice after a planned run says whether it was done, partial or not recorded", () => {
  const action = { request_id: "planned-x-1" };
  const answer = (task) => ({ action, task });
  assert.deepEqual(irrigationNotice(answer({ status: "done" })), { key: "tasks.irrigated", tone: "ok", id: "planned-x-1" });
  assert.deepEqual(irrigationNotice(answer({ status: "partial" })), { key: "tasks.irrigatePartial", tone: "error", id: "planned-x-1" });
  assert.deepEqual(irrigationNotice(answer(null)), { key: "tasks.irrigateUnconfirmed", tone: "error", id: "planned-x-1" });
});
