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

// --- device tests (design 2026-11-27) ---------------------------------------------------------

const buttons = (element) => descendants(element).filter((el) => el.nodeName === "BUTTON");
const testButtons = (element) => buttons(element).filter((el) => /^Test /.test(el.textContent || ""));
const ROW = { id: "gh-01", name: "Greenhouse 1", state: "mine", locked_at: 1, controlled: true, testable: true,
  test_running: null, test_unsettled: null, test_seconds: { light: 10, exhaust: 10, fan: 10, pump: 3 } };
const withRow = (row) => ({ "greenhouses.json": { greenhouses: [{ ...ROW, ...row }] } });

test("own testable row shows four test buttons with their durations", async () => {
  const { element } = await renderPage("greenhouses", {}, { lang: "en" });
  const labels = testButtons(element).map((b) => b.textContent);

  assert.equal(labels.length, 4);
  assert.match(labels.find((l) => /pump/.test(l)), /3 s/);
  assert.match(labels.find((l) => /light/.test(l)), /10 s/);
  assert.match(visibleText(element), /Have something to catch it/);
});

test("a running test disables every button until the reply, then shows the result", async () => {
  let reply;
  const answers = { "/greenhouses/gh-01/test/light": () => new Promise((resolve) => (reply = resolve)) };
  const { element, ctx } = await renderPage("greenhouses", {}, { lang: "en", answers });
  const light = testButtons(element).find((b) => /light/.test(b.textContent));

  light.dispatchEvent(new Event("click"));
  await flush();

  assert.ok(testButtons(element).every((b) => b.disabled));
  assert.match(visibleText(element), /Testing/);
  reply({ test_id: "t", channel: "light", test_level: 100, seconds: 10, result: "restored", actions: [] });
  await flush();
  assert.ok(testButtons(element).every((b) => !b.disabled));
  assert.match(visibleText(element), /settings were put back/);
  assert.ok(ctx.api.calls.some((c) => c.method === "POST" && c.path === "/greenhouses/gh-01/test/light"));
});

test("the pump asks for confirmation first", async () => {
  const { element, ctx } = await renderPage("greenhouses", {}, { lang: "en" });
  const pump = testButtons(element).find((b) => /pump/.test(b.textContent));

  answerNextDialog(false);
  pump.dispatchEvent(new Event("click"));
  await flush();

  assert.equal(ctx.api.calls.filter((c) => c.method === "POST").length, 0);
});

test("unsettled test shows retry and settle instead of the test buttons", async () => {
  const fixtures = withRow({ testable: false, test_unsettled: { test_id: "devtest_9", channel: "light", state: "restore_failed" } });
  const { element, ctx } = await renderPage("greenhouses", {}, { lang: "en", fixtures });

  assert.equal(testButtons(element).length, 0);
  const retry = buttons(element).find((b) => /Retry restore/.test(b.textContent));
  retry.dispatchEvent(new Event("click"));
  await flush();
  assert.ok(ctx.api.calls.some((c) => c.method === "POST" && c.path === "/greenhouses/gh-01/tests/devtest_9/retry"));
});

test("settle needs a note", async () => {
  const fixtures = withRow({ testable: false, test_unsettled: { test_id: "devtest_9", channel: "light", state: "restore_failed" } });
  const { element, ctx } = await renderPage("greenhouses", {}, { lang: "en", fixtures });
  const form = descendants(element).find((el) => el.nodeName === "FORM" && el.classList.contains("settle-form"));
  const input = descendants(form).find((el) => el.nodeName === "INPUT");

  form.dispatchEvent(Object.assign(new Event("submit"), { preventDefault() {} }));
  await flush();
  assert.equal(ctx.api.calls.filter((c) => c.method === "POST").length, 0);
  assert.match(visibleText(element), /Write a short note first/);

  input.value = "light back on its timer";
  form.dispatchEvent(Object.assign(new Event("submit"), { preventDefault() {} }));
  await flush();
  const call = ctx.api.calls.find((c) => c.method === "POST");
  assert.deepEqual([call.path, call.body], ["/greenhouses/gh-01/tests/devtest_9/settle", { note: "light back on its timer" }]);
});

test("a round in progress shows that tests are unavailable", async () => {
  const { element } = await renderPage("greenhouses", {}, { lang: "en", fixtures: withRow({ testable: false }) });

  assert.equal(testButtons(element).length, 0);
  assert.match(visibleText(element), /tests are unavailable/);
});

test("recent tests are listed with their outcome", async () => {
  const { element } = await renderPage("greenhouses", {}, { lang: "en" });
  const text = visibleText(element);

  assert.match(text, /Recent tests/);
  assert.match(text, /Restored/);
  assert.match(text, /Handled on site/);
});

test("rows not held show no test section", async () => {
  const fixtures = withRow({ state: "taken", testable: false, test_seconds: null });
  const { element, ctx } = await renderPage("greenhouses", {}, { lang: "en", fixtures });

  assert.equal(testButtons(element).length, 0);
  assert.doesNotMatch(visibleText(element), /Device test/);
  assert.ok(!ctx.api.calls.some((c) => /\/tests$/.test(c.path)));
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

test("each greenhouse says whether this installation drives its device", async () => {
  const { element } = await renderPage("greenhouses", {}, { lang: "en" });
  const text = visibleText(element);

  assert.match(text, /Only a connected greenhouse can run stages/);
  assert.equal((text.match(/Not connected to this installation/g) || []).length, 2);
  assert.match(text, /Connected/);
});

