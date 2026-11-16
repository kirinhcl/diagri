import assert from "node:assert/strict";
import test from "node:test";

import { visibleText } from "./support/leaks.mjs";
import { renderPage } from "./support/render-page.mjs";
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

const walk = (node) => [node, ...[...(node.children || [])].flatMap(walk)];
const NOW = 1794821400;
const withAlerts = (rows) => ({ "alerts.json": { alerts: rows.map((row) => ({ ...alert({}), kind: "audit_finding", key: "k", message: "m", count: 3, first_at: NOW - 7200, last_at: NOW - 600, ...row })) } });

test("an alert row has a kind label and splits evidence lines", async () => {
  const fixtures = withAlerts([{ message: "Summary line\n- first item\n- second item" }]);
  const { element } = await renderPage("alerts", {}, { fixtures, now: NOW });
  const text = visibleText(element);
  assert.match(text, /审计备注/);
  const items = walk(element).filter((el) => el.localName === "li").map((el) => el.textContent);
  assert.deepEqual(items, ["first item", "second item"]);
  const summary = walk(element).filter((el) => el.localName === "p" && el.textContent === "Summary line");
  assert.equal(summary.length, 1);
  const single = await renderPage("alerts", {}, { fixtures: withAlerts([{ message: "One line only" }]), now: NOW });
  assert.equal(walk(single.element).filter((el) => el.localName === "li").length, 0);
  assert.match(visibleText(single.element), /One line only/);
  assert.match(visibleText(single.element), /出现次数/);
  assert.doesNotMatch(visibleText(single.element), /Times are in|按 Europe/);
});

test("the read column says one thing", async () => {
  const cases = [
    [{}, /未读/],
    [{ read_by: "alice", read_at: NOW - 300, read_severity: "warning" }, /alice .* 已读/],
    [{ severity: "critical", read_by: "alice", read_at: NOW - 300, read_severity: "warning" }, /已读，但情况变糟：请再读一次/],
  ];
  for (const [row, expected] of cases) {
    const { element } = await renderPage("alerts", {}, { fixtures: withAlerts([row]), now: NOW });
    assert.match(visibleText(element), expected);
    assert.doesNotMatch(visibleText(element), /asked about again|再问/);
  }
  const en = await renderPage("alerts", {}, { lang: "en", fixtures: withAlerts([{ severity: "critical", read_by: "alice", read_at: NOW - 300, read_severity: "warning" }]), now: NOW });
  assert.match(visibleText(en.element), /Read, but it got worse; please read again/);
});
