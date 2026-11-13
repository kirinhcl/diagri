import test from "node:test";
import assert from "node:assert/strict";
import { minutePrecision } from "../../src/growbridge/web/workbench/ui/forms.js";
import { STATE_GROUPS, stateGroup } from "../../src/growbridge/web/workbench/ui/status.js";
import {
  KIND_ORDER,
  groupByKind,
  inboxCounts,
  inboxTarget,
  normalizeInbox,
} from "../../src/growbridge/web/workbench/pages/inbox.js";

test("every state from the plan's table lands in its colour group", () => {
  const table = {
    waiting: ["pending_review", "manual", "paused", "needs_attention", "needs_review", "awaiting_choice"],
    onsite: ["recovery_check"],
    active: ["running", "stage_running", "designing", "stage_review", "data_verification", "analysis",
      "in_progress", "computing", "fetching", "remote_queued", "reconcile"],
    done: ["ended", "stopped", "delivered", "aborted", "done"],
  };
  assert.deepEqual(STATE_GROUPS, table);
  for (const [group, states] of Object.entries(table)) {
    for (const state of states) assert.equal(stateGroup(state), group, state);
  }
  assert.equal(stateGroup("prepared"), "other");
  assert.equal(stateGroup("constructor"), "other");
});

test("datetime inputs drop only zero seconds, never the minutes", () => {
  assert.equal(minutePrecision("2025-11-13T16:00"), "2025-11-13T16:00");
  assert.equal(minutePrecision("2025-11-13T16:00:00"), "2025-11-13T16:00");
  assert.equal(minutePrecision("2025-11-13T16:05:00.000"), "2025-11-13T16:05");
  assert.equal(minutePrecision("2025-11-13T16:05:30"), "2025-11-13T16:05:30");
});

test("each inbox kind links to its page", () => {
  const item = (kind, extra = {}) => ({ kind, id: "x/1", project_id: "p1", round_id: "r1", ...extra });
  for (const kind of ["stage_review", "stage_manual", "stage_recovery", "stage_paused"]) {
    assert.equal(inboxTarget(item(kind)), "#/stages/x%2F1");
  }
  assert.equal(inboxTarget(item("round_choice")), "#/rounds/x%2F1");
  assert.equal(inboxTarget(item("alert")), "#/alerts");
  assert.equal(inboxTarget(item("compute_stuck")), "#/compute");
  assert.equal(inboxTarget(item("task")), "#/projects/p1");
  assert.equal(inboxTarget(item("task", { project_id: null })), "#/projects");
  assert.equal(inboxTarget(item("something_new")), null);
});

test("inbox counts include what the server cut", () => {
  const data = {
    items: [
      { kind: "alert", id: "a1" },
      { kind: "stage_review", id: "s1" },
    ],
    truncated: { alert: 3, task: 2 },
  };
  assert.deepEqual(inboxCounts(data), { inbox: 7, alerts: 4 });
  assert.deepEqual(inboxCounts({}), { inbox: 0, alerts: 0 });
});

test("groups follow the urgency order and keep kinds that only have cut items", () => {
  const inbox = normalizeInbox({
    items: [
      { kind: "task", id: "t1" },
      { kind: "brand_new", id: "n1" },
      { kind: "stage_recovery", id: "s1" },
      { kind: "alert" },
      null,
    ],
    truncated: { compute_stuck: 4, alert: 0, stage_review: "2" },
  });
  const groups = groupByKind(inbox);
  assert.deepEqual(
    groups.map((group) => [group.kind, group.items.length, group.hidden]),
    [
      ["stage_recovery", 1, 0],
      ["compute_stuck", 0, 4],
      ["task", 1, 0],
      ["brand_new", 1, 0],
    ],
  );
  assert.equal(KIND_ORDER[0], "stage_recovery");
});
