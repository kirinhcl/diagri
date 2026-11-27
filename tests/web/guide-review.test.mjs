// Step 7 of the guide: the composed protocol is shown in the normal protocol form, saved through POST /protocols,
// and then recorded on the guide. The guide never saves on its own.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { clearDrafts, saveDraft } from "../../src/growbridge/web/workbench/drafts.js";
import { protocolFormDraft } from "../../src/growbridge/web/workbench/guide-draft.js";
import { reviewStep } from "../../src/growbridge/web/workbench/pages/guide-review.js";
import { protocolForm } from "../../src/growbridge/web/workbench/pages/protocol-form.js";
import { bindFormContext } from "../../src/growbridge/web/workbench/ui/forms.js";
import { visibleText } from "./support/leaks.mjs";
import { FIXTURES, renderPage, testCtx } from "./support/render-page.mjs";

afterEach(() => clearDrafts());

const PROJECT = FIXTURES["project.json"];
const REVIEW = FIXTURES["guide-review.json"];
const SESSION = FIXTURES["guide-session.json"];
const SAVED_PATH = "/guide/sessions/guide-1/saved";
const settle = () => new Promise((resolve) => setImmediate(resolve));
const flush = async () => {
  for (let i = 0; i < 8; i += 1) await settle();
};
const find = (node, match) => [...(match(node) ? [node] : []), ...[...(node.children || [])].flatMap((child) => find(child, match))];
const byTag = (node, tag) => find(node, (el) => el.localName === tag);
const byClass = (node, name) => find(node, (el) => el.classList && el.classList.contains(name));
const named = (node, name) => find(node, (el) => el.getAttribute && el.getAttribute("name") === name);
const submit = async (root) => {
  byTag(root, "form")[0].dispatchEvent(new Event("submit", { cancelable: true }));
  await flush();
};

// What the server treats as the same as the form's output: an empty cultivar is left out of the review (the model
// drops empty optional fields) and a null script hash is the default. Nothing else is normalised.
function asFormSends(protocol) {
  const { script_sha256: hash, ...plan } = protocol.analysis;
  assert.equal(hash, null);
  return { ...protocol, cultivar: protocol.cultivar ?? "", analysis: plan };
}

async function open({ review = REVIEW, project = PROJECT, answers = {}, onSaved = () => {}, onOpenStep = () => {}, lang = "en" } = {}) {
  const ctx = testCtx({ lang, fixtures: { "guide-review.json": review }, answers });
  bindFormContext(ctx);
  const element = await reviewStep(ctx, { session: SESSION, project, onSaved, onOpenStep });
  return { ctx, element };
}

const posts = (ctx) => ctx.api.calls.filter((call) => call.method === "POST");

test("the form draft rebuilds exactly the reviewed protocol", async () => {
  const ctx = testCtx({ lang: "en" });
  bindFormContext(ctx);
  const sent = [];
  saveDraft(`protocol:${PROJECT.project_id}-form`, protocolFormDraft(REVIEW.protocol, { saveAs: "" }));
  const element = protocolForm(ctx, { project: PROJECT, onSubmit: async (value) => void sent.push(value) });
  await submit(element);
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].protocol, asFormSends(REVIEW.protocol));
});

test("saving posts the protocol, then tells the guide", async () => {
  const saved = [];
  const answers = {
    "/protocols": () => ({ protocol_id: REVIEW.protocol.id, version: 1 }),
    [SAVED_PATH]: () => ({ ...SESSION, saved: [{ protocol_id: REVIEW.protocol.id, version: 1, digest: "d", edited: [] }] }),
  };
  const { ctx, element } = await open({ answers, onSaved: (view) => saved.push(view) });
  await submit(element);
  const sent = posts(ctx);
  assert.deepEqual(sent.map((call) => call.path), ["/protocols", SAVED_PATH]);
  assert.deepEqual(sent[0].body, { protocol: asFormSends(REVIEW.protocol) });
  assert.equal(sent[0].options.action, "Save protocol");
  assert.deepEqual(sent[1].body, { protocol_id: REVIEW.protocol.id, version: 1 });
  assert.equal(saved.length, 1);
  assert.equal(saved[0].saved[0].edited.length, 0);
});

test("the guide is told the id and version the server saved", async () => {
  const answers = { "/protocols": () => ({ protocol_id: "protocol-9-x", version: 4 }), [SAVED_PATH]: () => SESSION };
  const { ctx, element } = await open({ answers });
  await submit(element);
  assert.deepEqual(posts(ctx)[1].body, { protocol_id: "protocol-9-x", version: 4 });
});

test("a protocol that is already saved is offered as the one to save the next version of", async () => {
  const carried = { ...REVIEW, protocol_id: "protocol-lettuce-light", version: 2, protocol: { ...REVIEW.protocol, id: "protocol-lettuce-light", version: 2 } };
  const answers = { "/protocols": () => ({ protocol_id: "protocol-lettuce-light", version: 2 }), [SAVED_PATH]: () => SESSION };
  const { ctx, element } = await open({ review: carried, answers });
  assert.equal(named(element, "save_as")[0].value, "protocol-lettuce-light");
  await submit(element);
  const body = posts(ctx)[0].body.protocol;
  assert.equal(body.id, "protocol-lettuce-light");
  assert.equal(body.version, 2);
  assert.deepEqual(body, asFormSends(carried.protocol));
});

test("a script hash carried from an earlier version is kept, though the form has no field for it", async () => {
  const hash = "a".repeat(64);
  const carried = { ...REVIEW, protocol: { ...REVIEW.protocol, analysis: { ...REVIEW.protocol.analysis, script_sha256: hash } } };
  const answers = { "/protocols": () => ({ protocol_id: REVIEW.protocol.id, version: 1 }), [SAVED_PATH]: () => SESSION };
  const { ctx, element } = await open({ review: carried, answers });
  await submit(element);
  assert.equal(posts(ctx)[0].body.protocol.analysis.script_sha256, hash);
});

test("problems and blocking findings are listed before the form, hints under their own heading", async () => {
  const review = {
    ...REVIEW,
    ready: false,
    problems: ["Variable air_temperature is not in the catalog"],
    design: [
      { code: "missing_control", message: "no control", blocking: true, variant: "undefined", params: { control: "x" } },
      { code: "seed_mismatch", message: "differs", blocking: false, variant: "differs", params: {} },
    ],
  };
  const { element } = await open({ review });
  const all = visibleText(element);
  const problems = all.indexOf("Problems to solve before saving");
  assert.ok(problems >= 0, all);
  assert.ok(all.indexOf("Variable air_temperature is not in the catalog") > problems);
  assert.ok(all.indexOf("Blocking") > problems);
  assert.ok(all.indexOf("Hints") > problems);
  assert.ok(problems < all.indexOf("Save as"), "problems come before the form");
  assert.equal(byTag(element, "form").length, 1, "the form is still shown");
});

test("a missing step links back to it", async () => {
  const opened = [];
  const review = { ...REVIEW, protocol: null, ready: false, missing: ["scale"] };
  const { element } = await open({ review, onOpenStep: (step) => opened.push(step) });
  const buttons = byClass(element, "guide-missing-step");
  assert.equal(buttons.length, 1);
  assert.equal(buttons[0].textContent, "Scale");
  buttons[0].dispatchEvent(new Event("click"));
  assert.deepEqual(opened, ["scale"]);
  assert.equal(byTag(element, "form").length, 0, "no form without a protocol");
});

test("a draft that cannot be composed shows its problems and no form", async () => {
  const review = { ...REVIEW, protocol: null, ready: false, problems: ["choose the scale again"] };
  const { element } = await open({ review });
  assert.ok(visibleText(element).includes("choose the scale again"));
  assert.equal(byTag(element, "form").length, 0);
});

test("a refused save is shown and the guide is not told", async () => {
  const answers = {
    "/protocols": () => {
      throw new ApiError(422, null, "refused by the server");
    },
  };
  const saved = [];
  const { ctx, element } = await open({ answers, onSaved: () => saved.push(1) });
  await submit(element);
  assert.deepEqual(posts(ctx).map((call) => call.path), ["/protocols"]);
  assert.equal(saved.length, 0);
  assert.ok(byClass(element, "form-status-error").length > 0);
});

test("if the guide cannot be told, the saved protocol is not saved again", async () => {
  let tries = 0;
  const answers = {
    "/protocols": () => ({ protocol_id: REVIEW.protocol.id, version: 1 }),
    [SAVED_PATH]: () => {
      tries += 1;
      if (tries === 1) throw new ApiError(500, null, "down");
      return SESSION;
    },
  };
  const saved = [];
  const { ctx, element } = await open({ answers, onSaved: () => saved.push(1) });
  await submit(element);
  assert.equal(saved.length, 0);
  const retry = byClass(element, "guide-retry")[0];
  assert.ok(retry, "a retry button");
  retry.dispatchEvent(new Event("click"));
  await flush();
  assert.deepEqual(posts(ctx).map((call) => call.path), ["/protocols", SAVED_PATH, SAVED_PATH]);
  assert.equal(saved.length, 1);
});

test("on the guide page a saved review moves on to the round step", async () => {
  const done = { ...SESSION, steps: SESSION.steps.map((entry) => ({ ...entry, status: "done", chosen: { step: entry.step, answer: {}, source: "own", option_ids: [], seq: 2 } })) };
  const view = { ...done, saved: [{ protocol_id: REVIEW.protocol.id, version: 1, digest: "d", edited: [] }] };
  const answers = { "/protocols": () => ({ protocol_id: REVIEW.protocol.id, version: 1 }), [SAVED_PATH]: () => view };
  const { element, ctx } = await renderPage("guide", { sessionId: "guide-1" }, { lang: "en", fixtures: { "guide-session.json": done }, answers });
  await flush();
  assert.equal(byTag(element, "form").length, 1);
  await submit(element);
  const current = byClass(element, "guide-rail-item").find((item) => item.getAttribute("aria-current") === "step");
  assert.equal(byClass(current, "guide-rail-title")[0].textContent, "Round and goal");
  assert.deepEqual(posts(ctx).map((call) => call.path), ["/protocols", SAVED_PATH]);
});

test("the review page has no 'AI' text", async () => {
  const { element } = await open({ lang: "zh" });
  assert.ok(!/\bAI\b/.test(visibleText(element)));
});
