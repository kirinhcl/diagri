// Console pages rendered from the captured fixtures, scanned for internal text (ids, codes, epochs,
// raw payloads, catalog keys) that a person should never have to read.
import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { PAGES } from "../../src/growbridge/web/workbench/router.js";
import { h } from "../../src/growbridge/web/workbench/ui/dom.js";
import { assertNoLeaks, exemptStrings, findLeaks, visibleText } from "./support/leaks.mjs";
import { EXEMPTIONS } from "./support/leak-exemptions.mjs";
import { FIXTURES, installFakeDom, renderPage, testCtx } from "./support/render-page.mjs";

// A stage read from before the server named stages: no number, phase, round number or project name.
const NAMES = new Set(["stage_index", "round_number", "project_name", "phase"]);
const OLD_STAGE = Object.fromEntries(Object.entries(FIXTURES["stage.json"]).filter(([key]) => !NAMES.has(key)));

// The project pages in states the captured reads lack: rounds from before rounds had numbers, one of
// them waiting for a choice, and a registered holdout that was read once.
const unnumbered = (round) => Object.fromEntries(Object.entries(round).filter(([key]) => key !== "round_number"));
const PROJECT = FIXTURES["project.json"];
const OLD_PROJECTS = { projects: FIXTURES["projects.json"].projects.map((row) => ({ ...row, latest_round: unnumbered(row.latest_round) })) };
const WAITING_ROUND = { ...unnumbered(PROJECT.rounds[0]), state: "running", awaiting_choice: `stage-${PROJECT.rounds[0].round_id}-1` };
const READ_ONCE = { reader: "dev", at: 1796594710, label: "confirmatory", model_sha: "" };
const HOLDOUT = {
  holdout_id: "holdout_5c987768a8b544ad80c4af4c0af9a962",
  project_id: PROJECT.project_id,
  batch_ids: ["batch-3"],
  development_batch_ids: ["batch-1", "batch-2"],
  outcome_fields: ["canopy_area_growth"],
  registered_at: 1796594700,
  registered_by: "dev",
  reads: [READ_ONCE],
};
const BUSY_PROJECT = { "project.json": { ...PROJECT, rounds: [WAITING_ROUND] }, "holdouts.json": { holdouts: [HOLDOUT] } };

// Inbox items of the kinds the captured read lacks: a stage waiting for review, a round waiting for a
// choice, a stuck compute attempt and a research task, plus a kind this console does not know.
const INBOX = FIXTURES["inbox.json"];
const MORE_ITEMS = [
  { kind: "round_choice", id: "round_9d38ffa4ca3049948194e0b60315c650", project_id: PROJECT.project_id, project_name: "dev light stage", round_number: 2, since: 1794821386, detail: { awaiting_choice: "stage-round_9d38ffa4ca3049948194e0b60315c650-1", since_from: "round_created" } },
  { kind: "compute_stuck", id: "attempt_9d38ffa4ca3049948194e0b60315c650", project_id: null, round_id: null, since: 1794821386, detail: { phase: "running", reason: "No result after 2 h on the cluster", task_id: "task_9d38ffa4ca3049948194e0b60315c650" } },
  { kind: "task", id: "task_9d38ffa4ca3049948194e0b60315c650", project_id: PROJECT.project_id, project_name: "dev light stage", since: 1794821386, detail: { question: "Which light level keeps the lettuce compact?", state: "needs_review", owner_role: "researcher" } },
  { kind: "brand_new_kind", id: "thing_1", project_id: null, round_id: null, since: 1794821386, detail: {} },
];
const BUSY_INBOX = { "inbox.json": { ...INBOX, items: [...INBOX.items, ...MORE_ITEMS], truncated: { alert: 12, task: 3 } } };
const OLD_INBOX = { "inbox.json": { items: INBOX.items.filter((item) => item.kind === "stage_review").map((item) => Object.fromEntries(Object.entries(item).filter(([key]) => !NAMES.has(key)))), truncated: {} } };

const RUNNING_STAGE = {
  stage_id: FIXTURES["stage.json"].stage_id,
  state: "running",
  sampling_seconds: 300,
  project_name: "dev light stage",
  round_number: 2,
  stage_index: 1,
  phase: "vegetative",
  channels: { fan: { ownership: "host", expected: 1 }, pump: { ownership: "host", expected: null } },
};

// Each page task adds its pages here: { page, params, fixtures? }; `fixtures` overrides files by name.
// Two evidence cards: one entered by an operator and verified, one by an agent and not yet verified.
const CARD = { source_class: "paper", citation: "Smith 2020, table 2", claim: "Blue light shortens lettuce", value: 12.5, unit: "cm", calibrated: false, added_at: 1796594000 };
const EVIDENCE_CARDS = [
  { ...CARD, id: "card_5c987768a8b544ad80c4af4c0af9a962", source: "dev", calibrated: true, verified_by: "dev", verified_at: 1796594100, note: "checked" },
  { ...CARD, id: "card_6d098879b9c655be91d5b0d1b0ba0a073", source: "model:planner", value: null, unit: null, verified_by: null, verified_at: null, note: null },
];

const PAGES_CHECKED = [
  { page: "inbox" },
  { page: "inbox", fixtures: BUSY_INBOX },
  { page: "inbox", fixtures: OLD_INBOX },
  { page: "stage", params: { stageId: FIXTURES["stage.json"].stage_id } },
  { page: "stage", params: { stageId: FIXTURES["stage-pending.json"].stage_id } },
  { page: "stage", params: { stageId: FIXTURES["stage.json"].stage_id }, fixtures: { "stage.json": OLD_STAGE } },
  { page: "round", params: { roundId: FIXTURES["round.json"].round_id } },
  { page: "projects" },
  { page: "projects", fixtures: { "projects.json": OLD_PROJECTS } },
  { page: "project", params: { projectId: PROJECT.project_id } },
  { page: "project", params: { projectId: PROJECT.project_id }, fixtures: BUSY_PROJECT },
  { page: "environment" },
  { page: "safety" },
  { page: "environment", fixtures: { "environment.json": { ...FIXTURES["environment.json"], stage: RUNNING_STAGE } } },
  { page: "alerts" },
  { page: "evidence" },
  { page: "evidence", fixtures: { "evidence.json": { cards: EVIDENCE_CARDS } } },
  { page: "compute" },
  { page: "login" },
];

const BATCH_1_PAGES = ["inbox", "projects", "project", "round", "stage", "environment", "safety", "alerts", "evidence", "compute"];
const PARAMS = {
  project: { projectId: FIXTURES["project.json"].project_id },
  round: { roundId: FIXTURES["round.json"].round_id },
  stage: { stageId: FIXTURES["stage.json"].stage_id },
};

const unanswered = (ctx) => ctx.api.calls.filter((call) => call.method === "GET" && !call.fixture).map((call) => call.path);

test("findLeaks names each kind of internal text", () => {
  assert.deepEqual(findLeaks("阶段 stage-round_9d38ffa4ca3049948194e0b60315c650-1").map((l) => l.kind), ["snake", "hexId"]);
  assert.deepEqual(findLeaks("ends at 1796594627").map((l) => l.kind), ["epoch"]);
  assert.deepEqual(findLeaks('detail {"seconds": 412.6}').map((l) => l.kind), ["payload"]);
  assert.deepEqual(findLeaks("请求 wb-3f2a9c1e-0b4d-4e1a-9f2c-1a2b3c4d5e6f").map((l) => l.kind), ["uuid"]);
  assert.deepEqual(findLeaks("显示 report.labels.undefined").map((l) => l.kind), ["i18nKey"]);
  assert.deepEqual(findLeaks("第 1 轮 · 已结束，共 21 天"), []);
  assert.deepEqual(findLeaks("message: data_gap seen", ["message: data_gap seen"]), []);
});

test("findLeaks lists every match of each kind in pattern order", () => {
  assert.deepEqual(findLeaks("at 1796594627 a_b then c_d see my.csc.fi"), [
    { kind: "snake", match: "a_b" },
    { kind: "snake", match: "c_d" },
    { kind: "epoch", match: "1796594627" },
  ]);
});

test("visibleText skips technical details but keeps aria-label", () => {
  const dom = installFakeDom();
  try {
    const node = h(
      "div",
      { attrs: { "aria-label": "x" } },
      h("p", { attrs: { title: "title_text" }, text: "a" }),
      h("details", { class: "tech-details" }, h("summary", { text: "技术详情" }), h("code", { text: "round_1" })),
    );
    assert.equal(visibleText(node), "x a");
    assert.equal(visibleText(h("div", {}, h("p", { text: "a" }), h("details", {}, h("summary", { text: "更多" })))), "a 更多");
  } finally {
    dom.restore();
  }
});

test("visibleText skips what a textarea holds, like any other input value", () => {
  const dom = installFakeDom();
  try {
    const node = h("div", {}, h("label", { text: "草稿" }), h("textarea", { text: '{ "round_id": "round_1" }' }), h("p", { text: "b" }));
    assert.equal(visibleText(node), "草稿 b");
  } finally {
    dom.restore();
  }
});

test("exemptStrings reads strings at a fixture path", () => {
  assert.deepEqual(exemptStrings("p", { "a.json": { rows: [{ m: "x_y" }, { m: "z" }] } }, [{ page: "p", fixture: "a.json", path: "rows[*].m" }]), ["x_y", "z"]);
  assert.deepEqual(exemptStrings("q", { "a.json": { rows: [{ m: "x_y" }] } }, [{ page: "p", fixture: "a.json", path: "rows[*].m" }]), []);
});

test("exemptStrings picks items by a field and gives each value as the page shows it", () => {
  const dom = installFakeDom();
  try {
    const conversation = { entries: [{ kind: "reply", text: "See `a_b`\n\n- **x_y** here" }, { kind: "tool", text: "c_d" }] };
    const replies = [{ page: "p", fixture: "c.json", path: "entries[kind=reply].text", shown: "richText" }];
    assert.deepEqual(exemptStrings("p", { "c.json": conversation }, replies), ["See a_b x_y here"]);
    const long = `${"word ".repeat(60)}x_y`;
    const folded = [{ page: "p", fixture: "t.json", path: "tasks[*].question", shown: "folded" }];
    assert.deepEqual(exemptStrings("p", { "t.json": { tasks: [{ question: long }] } }, folded), [long, long.slice(0, 240).trimEnd()]);
    assert.deepEqual(exemptStrings("p", { "a.json": { m: "a\n\n  b_c " } }, [{ page: "p", fixture: "a.json", path: "m" }]), ["a b_c"]);
    assert.throws(() => exemptStrings("p", { "a.json": { m: "x" } }, [{ page: "p", fixture: "a.json", path: "m", shown: "nope" }]), /shown/);
  } finally {
    dom.restore();
  }
});

test("assertNoLeaks names every leak it finds", () => {
  const dom = installFakeDom();
  try {
    const node = h("div", {}, h("p", { text: "round_1" }), h("p", { text: "1796594627" }));
    assert.throws(() => assertNoLeaks(node), (error) => /snake: round_1/.test(error.message) && /epoch: 1796594627/.test(error.message));
    assert.doesNotThrow(() => assertNoLeaks(node, ["round_1", "1796594627"]));
  } finally {
    dom.restore();
  }
});

test("the fake api answers by path from copies of the fixtures", async () => {
  const ctx = testCtx({ fixtures: { "alerts.json": { alerts: [] } } });
  const pendingRound = FIXTURES["round-pending.json"].round_id;
  assert.deepEqual(await ctx.api.get("/environment?window=3600&points=360"), FIXTURES["environment.json"]);
  assert.deepEqual(await ctx.api.get(`/rounds/${pendingRound}`), FIXTURES["round-pending.json"]);
  assert.deepEqual(await ctx.api.get(`/rounds/${PARAMS.round.roundId}/report`), FIXTURES["report.json"]);
  assert.deepEqual(await ctx.api.get("/stages/stage-dev/history"), FIXTURES["history-pending.json"]);
  assert.deepEqual(await ctx.api.get(`/stages/${PARAMS.stage.stageId}/readings?points=600`), FIXTURES["readings.json"]);
  assert.deepEqual(await ctx.api.get("/alerts"), { alerts: [] });
  const copy = await ctx.api.get("/inbox");
  assert.notEqual(copy, FIXTURES["inbox.json"]);
  assert.equal(Object.isFrozen(copy), false);
  await assert.rejects(ctx.api.get("/receipts/wb-1"), (e) => e instanceof ApiError && e.status === 404 && e.code === null && e.message === "HTTP 404");
  assert.deepEqual(await ctx.api.post("/alerts/a1/read", { x: 1 }, { action: "Read" }), {});
  assert.deepEqual(ctx.api.calls.at(-1), { method: "POST", path: "/alerts/a1/read", body: { x: 1 }, options: { action: "Read" } });
});

test("testCtx keeps an explicitly missing time zone", () => {
  assert.equal(testCtx().me.timezone, "Europe/Helsinki");
  assert.equal(testCtx().lang, "zh");
  assert.equal(testCtx({ lang: "en" }).t("nav.inbox"), "My inbox");
  const ctx = testCtx({ timezone: undefined, now: 1796594627 });
  assert.equal(Object.hasOwn(ctx.me, "timezone"), false);
  assert.equal(ctx.now, 1796594627);
  assert.equal(testCtx().now, undefined);
});

test("every Batch 1 page renders from its fixtures", async () => {
  for (const page of BATCH_1_PAGES) {
    const { element, ctx } = await renderPage(page, PARAMS[page]);
    assert.ok(visibleText(element).length > 20, page);
    assert.deepEqual(unanswered(ctx), [], page);
  }
});

test("the stage waiting for review renders from the -pending fixtures", async () => {
  const { element, ctx } = await renderPage("stage", { stageId: FIXTURES["stage-pending.json"].stage_id });
  assert.ok(visibleText(element).length > 20);
  const files = ctx.api.calls.map((call) => call.fixture);
  assert.ok(files.length > 0 && files.every((file) => /-pending\.json$/.test(String(file))), files.join(", "));
});

test("no exemption is left for the second batch", () => {
  assert.ok(EXEMPTIONS.every((exemption) => exemption.batch !== 2));
});

test("no page leaks internal text", async (t) => {
  for (const { page, params, fixtures } of PAGES_CHECKED) {
    for (const lang of ["zh", "en"]) {
      await t.test(`${page} ${JSON.stringify(params || {})} (${lang})`, async () => {
        const { element } = await renderPage(page, params, { lang, fixtures });
        assertNoLeaks(element, exemptStrings(page, { ...FIXTURES, ...fixtures }));
      });
    }
  }
});

test("a stage read from before stages had names is called an unnamed stage", async () => {
  const { element, ctx } = await renderPage("stage", PARAMS.stage, { fixtures: { "stage.json": OLD_STAGE } });
  const headings = (node) => [...(node.localName === "h1" ? [node] : []), ...[...node.children].flatMap(headings)];
  assert.deepEqual(headings(element).map((h1) => h1.textContent), ["未命名阶段"]);
  assert.deepEqual(ctx.crumbs.map((crumb) => crumb.label), ["项目", "未命名项目", "未命名轮次", "未命名阶段"]);
});

test("the fake DOM's children and childNodes behave like the browser's collections", () => {
  const parent = document.createElement("div");
  parent.append(document.createElement("a"), "text", document.createElement("b"));
  assert.equal(parent.children.find, undefined);
  assert.equal(parent.children.map, undefined);
  assert.equal(parent.childNodes.find, undefined);
  assert.equal(typeof parent.childNodes.forEach, "function");
  assert.equal(parent.children.length, 2);
  assert.equal(parent.children.item(1).localName, "b");
  assert.equal(parent.children[0].localName, "a");
  assert.deepEqual([...parent.children].map((el) => el.localName), ["a", "b"]);
  assert.equal([...parent.childNodes].length, 3);
});

test("every console page is checked for leaks", () => {
  const checked = new Set(PAGES_CHECKED.map((entry) => entry.page));
  for (const page of [...PAGES, "login"]) assert.ok(checked.has(page), page);
});

test("every exemption names its batch and reason", () => {
  for (const entry of EXEMPTIONS) {
    assert.ok([2, 3, "keep"].includes(entry.batch), entry.path);
    assert.ok(typeof entry.why === "string" && entry.why.trim(), entry.path);
  }
});

test("the sign-in page and its denials call the secret a password", async () => {
  const forbidden = { zh: /口令/, en: /secret/i };
  for (const lang of ["zh", "en"]) {
    const { element } = await renderPage("login", {}, { lang });
    assert.doesNotMatch(visibleText(element), forbidden[lang], lang);
  }
});
