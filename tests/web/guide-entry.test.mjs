// The ways into the guide (project list form, project page button) and its last step: the round and the goal.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { clearDrafts } from "../../src/growbridge/web/workbench/drafts.js";
import { roundStep } from "../../src/growbridge/web/workbench/pages/guide-review.js";
import { bindFormContext } from "../../src/growbridge/web/workbench/ui/forms.js";
import { visibleText } from "./support/leaks.mjs";
import { FIXTURES, renderPage, testCtx } from "./support/render-page.mjs";

afterEach(() => clearDrafts());

const PROJECT = FIXTURES["project.json"];
const BASE_SESSION = FIXTURES["guide-session.json"];
const settle = () => new Promise((resolve) => setImmediate(resolve));
const flush = async () => {
  for (let i = 0; i < 8; i += 1) await settle();
};
const find = (node, match) => [...(match(node) ? [node] : []), ...[...(node.children || [])].flatMap((child) => find(child, match))];
const byTag = (node, tag) => find(node, (el) => el.localName === tag);
const byClass = (node, name) => find(node, (el) => el.classList && el.classList.contains(name));
const named = (node, name) => find(node, (el) => el.getAttribute && el.getAttribute("name") === name);
const formWith = (root, name) => byTag(root, "form").find((form) => named(form, name).length > 0);
const submit = async (form) => {
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await flush();
};
const click = async (button) => {
  button.dispatchEvent(new Event("click", { cancelable: true }));
  await flush();
};
const posts = (ctx) => ctx.api.calls.filter((call) => call.method === "POST");

const SAVED = { protocol_id: "protocol-2-55fbcb", version: 3, digest: "abc", edited: null };
const QUESTION = "Does more light speed up growth?";
const SESSION = {
  ...BASE_SESSION,
  steps: BASE_SESSION.steps.map((entry) => (entry.step === "question" ? { ...entry, status: "done", chosen: { source: "own", answer: { question: QUESTION, hypothesis: "" } } } : entry)),
};

async function newProject({ answers = {}, lang = "en" } = {}) {
  const page = await renderPage("projects", {}, { lang, answers });
  const went = [];
  const noticed = [];
  page.ctx.navigate = (href) => went.push(href);
  page.ctx.notify = (message, kind) => noticed.push({ message, kind });
  return { ...page, went, noticed, form: formWith(page.element, "max_calls") };
}

test("the guided new-project form creates project, budget and session, then opens the guide", async () => {
  const answers = {
    "/projects": () => ({ project_id: "project-9" }),
    "/projects/project-9/budget": () => ({}),
    "/guide/sessions": () => ({ session_id: "guide-9" }),
  };
  const { ctx, form, went } = await newProject({ answers });
  assert.equal(named(form, "max_calls")[0].value, "100");
  assert.equal(named(form, "max_cost")[0].value, "10");
  named(form, "name")[0].value = "Lettuce light";
  await submit(form);
  assert.deepEqual(posts(ctx).map((call) => call.path), ["/projects", "/projects/project-9/budget", "/guide/sessions"]);
  assert.deepEqual(posts(ctx)[0].body, { name: "Lettuce light" });
  assert.deepEqual(posts(ctx)[1].body, { max_calls: 100, max_cost: 10 });
  assert.deepEqual(posts(ctx)[2].body, { project_id: "project-9", lang: "en" });
  assert.deepEqual(went, ["#/guide/guide-9"]);
});

test("a deployment without a budget route skips the budget, says so and still opens the guide", async () => {
  const answers = {
    "/projects": () => ({ project_id: "project-9" }),
    "/projects/project-9/budget": () => {
      throw new ApiError(404, null, "HTTP 404");
    },
    "/guide/sessions": () => ({ session_id: "guide-9" }),
  };
  const { ctx, form, went, noticed } = await newProject({ answers });
  named(form, "name")[0].value = "Lettuce light";
  await submit(form);
  assert.deepEqual(went, ["#/guide/guide-9"]);
  assert.equal(posts(ctx).length, 3);
  assert.ok(noticed.some((item) => /budget/i.test(item.message)));
});

test("the project page opens a guide for that project", async () => {
  const answers = { "/guide/sessions": () => ({ session_id: "guide-7" }) };
  const page = await renderPage("project", { projectId: PROJECT.project_id }, { lang: "zh", answers });
  const went = [];
  page.ctx.navigate = (href) => went.push(href);
  const button = byClass(page.element, "guide-start")[0];
  assert.ok(button);
  await click(button);
  assert.deepEqual(posts(page.ctx).map((call) => [call.path, call.body]), [["/guide/sessions", { project_id: PROJECT.project_id, lang: "zh" }]]);
  assert.deepEqual(went, ["#/guide/guide-7"]);
});

function openRound({ saved = SAVED, answers = {}, onOpenStep } = {}) {
  const ctx = testCtx({ lang: "zh", answers });
  bindFormContext(ctx);
  const element = roundStep(ctx, { session: SESSION, saved, onOpenStep });
  return { ctx, element };
}

test("the round step creates the round, then sends the goal in the page language", async () => {
  const answers = { "/rounds": () => ({ round_id: "round-5", state: "designing" }), "/goals": () => ({ task_id: "t1" }) };
  const { ctx, element } = openRound({ answers });
  await click(byClass(element, "guide-make-round")[0]);
  assert.equal(posts(ctx)[0].path, "/rounds");
  assert.deepEqual(posts(ctx)[0].body, { project_id: SESSION.session.project_id, protocol_id: SAVED.protocol_id });
  const form = formWith(element, "goal");
  assert.equal(named(form, "goal")[0].value, QUESTION);
  named(form, "goal")[0].value = "Compare light 40 and 70";
  await submit(form);
  assert.equal(posts(ctx)[1].path, "/goals");
  assert.deepEqual(posts(ctx)[1].body, { project_id: SESSION.session.project_id, round_id: "round-5", goal: "Compare light 40 and 70", language: "zh" });
  const links = find(element, (el) => el.localName === "a").map((el) => el.getAttribute("href"));
  assert.ok(links.includes("#/rounds/round-5"));
});

test("the round step says a round uses the protocol's latest version, not the saved one by number", async () => {
  const zh = visibleText(openRound().element);
  assert.match(zh, /协议 2，第 3 版 已保存/);
  assert.match(zh, /轮次用协议 2 的最新版本/);
  const ctx = testCtx({ lang: "en" });
  bindFormContext(ctx);
  const en = visibleText(roundStep(ctx, { session: SESSION, saved: SAVED }));
  assert.match(en, /uses the latest version of Protocol 2/);
});

test("the round step without a saved protocol points back to the review and posts nothing", async () => {
  const opened = [];
  const { ctx, element } = openRound({ saved: null, onOpenStep: (step) => opened.push(step) });
  assert.equal(byClass(element, "guide-make-round").length, 0);
  assert.ok(visibleText(element).length > 0);
  await click(byClass(element, "guide-back-review")[0]);
  assert.deepEqual(opened, ["review"]);
  assert.equal(posts(ctx).length, 0);
});
