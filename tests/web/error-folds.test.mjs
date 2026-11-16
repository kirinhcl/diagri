// Wherever an error stays on a page, its plain lines are in view and the server's own words are one
// click away in the technical details, never in the page text itself.
import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { checkParts } from "../../src/growbridge/web/workbench/pages/stage-actions.js";
import { bindFormContext } from "../../src/growbridge/web/workbench/ui/forms.js";
import { visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { FIXTURES, installFakeDom, testCtx } from "./support/render-page.mjs";

const WORDS = "call budget exhausted for this project; 120 of 120 calls used";

// Every pending promise job, then one turn of the event loop.
const settle = () => new Promise((resolve) => setImmediate(resolve));

function elements(node, name) {
  const own = node.localName === name ? [node] : [];
  return [...own, ...(node.children || []).flatMap((child) => elements(child, name))];
}

const hasClass = (node, name) => (node.getAttribute("class") || "").split(/\s+/).includes(name);

// The error boxes of a page: every element of class form-status-error that holds a fold.
const foldedBoxes = (root) => elements(root, "div").filter((div) => hasClass(div, "form-status-error") && elements(div, "details").length);

// Renders a page as main.js does; a GET whose path `control.fail` answers with an error throws it.
async function renderWith(page, params, fail = () => null) {
  installFakeDom();
  const ctx = testCtx({ lang: "en" });
  const control = { fail };
  const get = ctx.api.get;
  ctx.api.get = async (path) => {
    const error = control.fail(path);
    if (error) throw error;
    return get(path);
  };
  bindFormContext(ctx);
  const module = await import(`../../src/growbridge/web/workbench/pages/${page}.js`);
  const result = await module.render(ctx, params);
  return { ...result, ctx, control };
}

function assertFolded(box, words) {
  assert.ok(box, "an error box with a fold");
  assert.ok(!visibleText(box).includes(words), "the server's words are not page text");
  assert.ok(visibleTextIncludingDetails(box).includes(words), "the server's words are in the fold");
}

test("a refused chat message keeps the server's words in the fold under the plain lines", async () => {
  const { element, ctx } = await renderWith("project", { projectId: FIXTURES["project.json"].project_id });
  ctx.api.post = async () => {
    throw new ApiError(409, "budget", WORDS);
  };
  const [form] = elements(element, "form").filter((node) => hasClass(node, "chat-form"));
  elements(form, "textarea")[0].value = "Compare the two light levels";
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  const [chat] = elements(element, "div").filter((node) => hasClass(node, "chat"));
  assertFolded(foldedBoxes(chat)[0], WORDS);
});

test("a stage part that could not be read folds the server's words under its plain lines", async () => {
  const stageId = FIXTURES["stage.json"].stage_id;
  const refused = new ApiError(403, "scope", WORDS);
  const { element } = await renderWith("stage", { stageId }, (path) => (path.endsWith("/history") ? refused : null));
  assertFolded(foldedBoxes(element)[0], WORDS);
  assert.ok(!visibleText(element).includes(WORDS));
});

test("a stale stage or inbox keeps its stale line, the plain lines and the fold", async () => {
  const stageId = FIXTURES["stage.json"].stage_id;
  for (const [page, params, staleKey] of [["stage", { stageId }, "stage.stale"], ["inbox", {}, "inbox.stale"]]) {
    const { element, refresh, ctx, control } = await renderWith(page, params);
    control.fail = () => new ApiError(409, "state", WORDS);
    await refresh();
    const box = foldedBoxes(element)[0];
    assertFolded(box, WORDS);
    assert.equal(elements(box, "p")[0].textContent, ctx.t(staleKey), page);
    const [fold] = elements(box, "details");
    fold.setAttribute("open", "");
    await refresh();
    assert.equal(elements(box, "details")[0], fold, `${page}: the same failure again leaves the opened fold as it is`);
  }
});

test("a side read that failed (holdouts, analysis) keeps the server's words in the fold", async () => {
  const cases = [
    ["project", { projectId: FIXTURES["project.json"].project_id }, "/holdouts"],
    ["round", { roundId: FIXTURES["round.json"].round_id }, "/analysis"],
  ];
  for (const [page, params, part] of cases) {
    const refused = new ApiError(403, "member", WORDS);
    const { element } = await renderWith(page, params, (path) => (path.split("?")[0].endsWith(part) ? refused : null));
    assertFolded(foldedBoxes(element)[0], WORDS);
  }
});

test("a receipt that could not be checked says so and folds the error's words", () => {
  installFakeDom();
  const ctx = testCtx({ lang: "en" });
  const [line, fold] = checkParts(ctx, new ApiError(409, "state", WORDS));
  assert.match(line, /^Could not check the result: /);
  assert.ok(!line.includes(WORDS));
  assert.ok(visibleTextIncludingDetails(fold).includes(WORDS));
  assert.deepEqual(checkParts(ctx, new ApiError(404, null, "HTTP 404")), [ctx.t("receipt.noRecord")]);
});
