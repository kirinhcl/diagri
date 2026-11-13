import assert from "node:assert/strict";
import test from "node:test";

import { alertWaiting, REASK_SECONDS } from "../../src/growbridge/web/workbench/pages/alerts.js";

const alert = (fields) => ({ event_id: "a1", severity: "warning", read_by: null, read_at: null, read_severity: null, ...fields });

test("an unread alert waits", () => {
  assert.equal(alertWaiting(alert({})), true);
});

test("a read alert raised again at the same or a milder severity stays read", () => {
  assert.equal(alertWaiting(alert({ read_by: "alice", read_at: 5, read_severity: "warning" })), false);
  assert.equal(alertWaiting(alert({ severity: "info", read_by: "alice", read_at: 5, read_severity: "warning" })), false);
});

test("a read alert that got worse waits again", () => {
  assert.equal(alertWaiting(alert({ severity: "critical", read_by: "alice", read_at: 5, read_severity: "warning" })), true);
  assert.equal(alertWaiting(alert({ severity: "warning", read_by: "alice", read_at: 5, read_severity: "info" })), true);
});

test("a read recorded without its severity waits once more, as on the server", () => {
  assert.equal(alertWaiting(alert({ read_by: "alice", read_at: 5, read_severity: null })), true);
});

test("a persistent alert read earlier is asked about again after a day, as on the server", () => {
  const read = { read_by: "alice", read_at: 1000, read_severity: "warning" };
  assert.equal(REASK_SECONDS, 24 * 3600);
  assert.equal(alertWaiting(alert({ ...read, last_at: 1000 + REASK_SECONDS })), false);
  assert.equal(alertWaiting(alert({ ...read, last_at: 1000 + REASK_SECONDS + 1 })), true);
});
