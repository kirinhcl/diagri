import assert from "node:assert/strict";
import test from "node:test";

import { visibleText } from "./support/leaks.mjs";
import { FIXTURES, renderPage } from "./support/render-page.mjs";
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

test("an alert row has a kind label and the column headings; a coded row's message is not split by lines", async () => {
  const fixtures = withAlerts([{ code: "audit_finding", params: { stage_id: "s1", summary: "S", evidence: [] }, message: "Summary line\n- first item" }]);
  const { element } = await renderPage("alerts", {}, { fixtures, now: NOW });
  const text = visibleText(element);
  assert.match(text, /审计备注/);
  assert.match(text, /出现次数/);
  assert.doesNotMatch(text, /Summary line|first item/);
  assert.doesNotMatch(text, /Times are in|按 Europe/);
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

test("a read without a recorded severity is not called worse; a day-old read says why it asks again", async () => {
  const legacy = await renderPage("alerts", {}, { fixtures: withAlerts([{ read_by: "alice", read_at: NOW - 300, read_severity: null }]), now: NOW });
  assert.match(visibleText(legacy.element), /alice .* 已读/);
  assert.doesNotMatch(visibleText(legacy.element), /情况变糟/);
  const old = await renderPage("alerts", {}, { fixtures: withAlerts([{ read_by: "alice", read_at: NOW - 30 * 3600, read_severity: "warning", last_at: NOW - 40 * 3600 }]), now: NOW });
  assert.match(visibleText(old.element), /已读超过一天，请再确认一次。/);
  const fresh = await renderPage("alerts", {}, { fixtures: withAlerts([{ read_by: "alice", read_at: NOW - 300, read_severity: "warning" }]), now: NOW });
  assert.doesNotMatch(visibleText(fresh.element), /超过一天/);
});

// Alerts that carry a code and params (Task 7): sentences, a next step, a link, the server's words in the details.
const fixtureAlert = (kind) => FIXTURES["alerts.json"].alerts.find((row) => row.kind === kind);
const rowsOf = (element) => walk(element).filter((el) => el.localName === "tr");
const details = (node) => walk(node).filter((el) => el.localName === "details" && el.getAttribute("class") === "tech-details");
const outsideDetails = (node) => visibleText(node);

test("an alert row says what happened and what to do; the server's words are in the details", async () => {
  const row = fixtureAlert("threshold");
  const { element } = await renderPage("alerts", {}, { fixtures: { "alerts.json": { alerts: [row] } }, now: NOW });
  const text = outsideDetails(element);
  assert.match(text, /温度/);
  assert.match(text, /temp-high/);
  assert.doesNotMatch(text, /temperature above 30/);
  assert.equal(walk(element).filter((el) => el.getAttribute?.("class") === "message-action").length, 1);
  const folds = details(rowsOf(element)[1]);
  assert.equal(folds.length, 1);
  const raw = folds[0].textContent;
  assert.match(raw, /temperature above 30 for 600 s/);
  assert.match(raw, /服务器原文/);
  assert.match(raw, /rule-temp-high/);
  assert.match(raw, /threshold/);
});

test("a waiting stage's alert lists its reasons as sentences and links to the stage even when its id has a colon", async () => {
  const row = fixtureAlert("stage_waiting");
  const { element } = await renderPage("alerts", {}, { fixtures: { "alerts.json": { alerts: [row] } }, now: NOW });
  const links = walk(element).filter((el) => el.localName === "a");
  assert.deepEqual(links.map((el) => el.getAttribute("href")), ["#/stages/stage%3Aa-1"]);
  assert.equal(links[0].textContent, "打开阶段");
  const lines = walk(element).filter((el) => el.getAttribute?.("class") === "message-detail").map((el) => el.textContent);
  assert.ok(lines.length >= 1);
  assert.ok(lines.some((line) => /10 分钟|600/.test(line)));
  assert.doesNotMatch(outsideDetails(element), /stage:a-1|disconnect_affects|pump_off/);
  assert.equal(details(rowsOf(element)[1]).length, 1);
});

test("an alert with a project id links to the project", async () => {
  const row = { ...fixtureAlert("stage_waiting"), params: { project_id: "project_x/1" } };
  const { element } = await renderPage("alerts", {}, { fixtures: { "alerts.json": { alerts: [row] } }, now: NOW });
  const hrefs = walk(element).filter((el) => el.localName === "a").map((el) => el.getAttribute("href"));
  assert.deepEqual(hrefs, ["#/projects/project_x%2F1"]);
});

test("an auditor's note is quoted under a fixed sentence", async () => {
  const row = fixtureAlert("audit_finding");
  const { element } = await renderPage("alerts", {}, { fixtures: { "alerts.json": { alerts: [row] } }, now: NOW });
  const quotes = walk(element).filter((el) => el.localName === "blockquote");
  assert.equal(quotes.length, 1);
  assert.equal(quotes[0].getAttribute("class"), "model-note");
  assert.match(quotes[0].textContent, /The light stayed off during the day\./);
  assert.deepEqual(walk(quotes[0]).filter((el) => el.localName === "li").map((el) => el.textContent), ["light off 09:00-11:00", "no operator note"]);
  assert.match(outsideDetails(element), /监察 Agent 对这个阶段有一条备注/);
});

test("an alert from before codes shows its kind and keeps the message in the details", async () => {
  const row = fixtureAlert("data_gap");
  assert.equal(row.code, undefined);
  const { element } = await renderPage("alerts", {}, { fixtures: { "alerts.json": { alerts: [row] } }, now: NOW });
  const text = outsideDetails(element);
  assert.match(text, /数据空档/);
  assert.match(text, /这条告警来自更新之前，服务器原文在技术详情里。/);
  assert.doesNotMatch(text, /No readings for 20 min/);
  assert.match(details(rowsOf(element)[1])[0].textContent, /No readings for 20 min/);
});

test("an alert with an unknown code says unknown and keeps the code in the details", async () => {
  const row = { ...fixtureAlert("threshold"), code: "brand_new_code" };
  const { element } = await renderPage("alerts", {}, { fixtures: { "alerts.json": { alerts: [row] } }, now: NOW });
  assert.match(outsideDetails(element), /未知（技术详情）/);
  assert.doesNotMatch(outsideDetails(element), /brand_new_code/);
  assert.match(details(rowsOf(element)[1])[0].textContent, /brand_new_code/);
});
