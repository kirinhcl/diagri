import assert from "node:assert/strict";
import test, { afterEach } from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { takenIds } from "../../src/growbridge/web/workbench/pages/greenhouses.js";
import { answerNextDialog, assertNoPendingDialogAnswers, openDialogs, resetDialogs } from "./support/dialogs.mjs";
import { renderPage } from "./support/render-page.mjs";
import { visibleText } from "./support/leaks.mjs";

const descendants = (node) => [...(node.children || [])].flatMap((child) => [child, ...descendants(child)]);
const boxes = (element) => descendants(element).filter((el) => el.getAttribute("type") === "checkbox");
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

async function submit(element) {
  const form = descendants(element).find((el) => el.nodeName === "FORM");
  form.dispatchEvent(Object.assign(new Event("submit"), { preventDefault() {} }));
  await flush();
}

test("each greenhouse shows as yours, taken or free, and only free ones can be ticked", async () => {
  const { element } = await renderPage("greenhouses", {}, { lang: "en" });
  const text = visibleText(element);

  for (const word of ["Yours", "Taken", "Free"]) assert.match(text, new RegExp(word));
  assert.deepEqual(boxes(element).map((box) => box.disabled), [true, true, false]);
  assert.match(text, /Release/); // gh-01 is yours
});

test("locking sends the ticked greenhouses", async () => {
  const { element, ctx } = await renderPage("greenhouses", {}, { lang: "en" });
  boxes(element)[2].checked = true;

  await submit(element);

  const call = ctx.api.calls.find((c) => c.method === "POST");
  assert.deepEqual(call, { method: "POST", path: "/greenhouses/lock", body: { greenhouse_ids: ["gh-03"] }, options: call.options });
});

test("a lock refused because one was taken meanwhile names it and keeps the ticks", async () => {
  const refuse = () => {
    throw new ApiError(409, "lock_taken", "already locked: gh-03");
  };
  const { element } = await renderPage("greenhouses", {}, { lang: "en", answers: { "/greenhouses/lock": refuse } });
  boxes(element)[2].checked = true;

  await submit(element);

  assert.match(visibleText(element), /Someone just locked these: gh-03/);
  assert.equal(boxes(element)[2].checked, true);
});

test("nothing ticked: nothing is sent", async () => {
  const { element, ctx } = await renderPage("greenhouses", {}, { lang: "en" });

  await submit(element);

  assert.equal(ctx.api.calls.filter((c) => c.method === "POST").length, 0);
  assert.match(visibleText(element), /Tick at least one free greenhouse first/);
});

test("the ids of a lock refusal", () => {
  assert.deepEqual(takenIds(new ApiError(409, "lock_taken", "already locked: gh-02, gh-03")), ["gh-02", "gh-03"]);
  assert.deepEqual(takenIds(new ApiError(409, "state", "x: y")), []);
});

test("an administrator also sees who holds each greenhouse", async () => {
  const admin = { kind: "operator", id: "dev", operator: "dev", entry: "lan", multi_user: true, role: "admin", greenhouses: [] };
  const fixtures = { "me.json": admin, "greenhouses.json": { greenhouses: [{ id: "gh-02", name: "Greenhouse 2", state: "taken", locked_at: 1, holder: "alice" }] } };
  const { element } = await renderPage("greenhouses", {}, { lang: "en", fixtures });

  assert.match(visibleText(element), /alice/);
});

afterEach(() => {
  try {
    assertNoPendingDialogAnswers();
  } finally {
    resetDialogs();
  }
});

test("releasing asks to confirm the plants are gone and sends that confirmation", async () => {
  const { element, ctx } = await renderPage("greenhouses", {}, { lang: "en" });
  const release = descendants(element).find((el) => el.nodeName === "BUTTON" && el.textContent === "Release");

  release.dispatchEvent(new Event("click"));
  await flush();
  const [dialog] = openDialogs();
  assert.match(dialog.textContent, /My plants have been taken out and the chamber is empty/);
  // with no idle levels configured the device keeps its settings: the dialog must not promise idle
  assert.match(dialog.textContent, /idle settings if an administrator set them; otherwise it keeps its current settings/);
  const box = descendants(dialog).find((el) => el.getAttribute("type") === "checkbox");
  box.checked = true;
  box.dispatchEvent(new Event("change"));
  answerNextDialog(true);
  await flush();

  const call = ctx.api.calls.find((c) => c.method === "POST");
  assert.equal(call.path, "/greenhouses/gh-01/release");
  assert.deepEqual(call.body, { plants_removed: true });
});

