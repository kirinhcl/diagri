import assert from "node:assert/strict";
import test from "node:test";

import { alertWaiting, REASK_SECONDS } from "../../src/growbridge/web/workbench/pages/alerts.js";

const alert = (fields) => ({ event_id: "a1", severity: "warning", read_by: null, read_at: null, read_severity: null, ...fields });

test("an unread alert waits", () => {
  assert.equal(alertWaiting(alert({}), 10), true);
});

test("a read alert raised again at the same or a milder severity stays read", () => {
  assert.equal(alertWaiting(alert({ read_by: "alice", read_at: 5, read_severity: "warning" }), 10), false);
  assert.equal(alertWaiting(alert({ severity: "info", read_by: "alice", read_at: 5, read_severity: "warning" }), 10), false);
});

test("a read alert that got worse waits again", () => {
  assert.equal(alertWaiting(alert({ severity: "critical", read_by: "alice", read_at: 5, read_severity: "warning" }), 10), true);
  assert.equal(alertWaiting(alert({ severity: "warning", read_by: "alice", read_at: 5, read_severity: "info" }), 10), true);
});

test("a read recorded without its severity waits once more, as on the server", () => {
  assert.equal(alertWaiting(alert({ read_by: "alice", read_at: 5, read_severity: null }), 10), true);
});

test("a read alert is asked about again by the clock, and a clock that went back counts as unread", () => {
  const read = alert({ read_by: "alice", read_at: 1000, read_severity: "warning" });
  assert.equal(REASK_SECONDS, 24 * 3600);
  assert.equal(alertWaiting(read, 1000 + 23 * 3600), false);
  assert.equal(alertWaiting(read, 1000 + 25 * 3600), true); // never raised again, still asked
  assert.equal(alertWaiting(read, 1000 - 60), true);
});

test("a future-dated last raise leaves a read alert waiting, as on the server", () => {
  const read = alert({ read_by: "alice", read_at: 1000, read_severity: "warning" });
  assert.equal(alertWaiting({ ...read, last_at: 1000 }, 1060), false);
  assert.equal(alertWaiting({ ...read, last_at: 5000 }, 1060), true); // last_at is after now
  assert.equal(alertWaiting({ ...read, last_at: 1000 }, 999), true); // now before the reading
});
