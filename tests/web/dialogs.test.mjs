import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { askSecret, confirmAction, confirmWithTick } from "../../src/growbridge/web/workbench/ui/dialog.js";
import { takeDraft } from "../../src/growbridge/web/workbench/drafts.js";
import { Cancelled, confirmOrCancel, jsonEditor, simpleForm } from "../../src/growbridge/web/workbench/ui/forms.js";
import { answerNextDialog, assertNoPendingDialogAnswers, openDialogs, resetDialogs } from "./support/dialogs.mjs";
import { testCtx } from "./support/render-page.mjs";

const PROMPT = { title: "Stop the round?", lines: ["It ends now.", "Nothing is lost."] };

afterEach(() => {
  try {
    assertNoPendingDialogAnswers();
  } finally {
    resetDialogs();
  }
});

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("a confirm dialog can be answered yes or no in tests", async () => {
  const ctx = testCtx({ lang: "en" });
  for (const answer of [true, false]) {
    const pending = confirmAction(ctx.t, PROMPT);
    await tick();
    const [dialog] = openDialogs();
    assert.ok(dialog.textContent.includes(PROMPT.title));
    for (const line of PROMPT.lines) assert.ok(dialog.textContent.includes(line));
    answerNextDialog(answer);
    assert.equal(await pending, answer);
    assert.equal(openDialogs().length, 0);
  }
});

test("an answer given before the dialog opens, or a text answer, is applied when it does", async () => {
  const ctx = testCtx({ lang: "en" });
  answerNextDialog(false);
  answerNextDialog(true);
  assert.equal(await confirmAction(ctx.t, PROMPT), false);
  assert.equal(await confirmAction(ctx.t, PROMPT), true);
  answerNextDialog("because");
  assert.equal(await confirmAction(ctx.t, PROMPT), true);
});

test("a string answer is typed into the dialog's text box and confirmed", async () => {
  const ctx = testCtx({ lang: "en" });
  answerNextDialog("pw");
  assert.equal(await askSecret(ctx.t, "Stop"), "pw");
  const pending = askSecret(ctx.t);
  await tick();
  answerNextDialog(null);
  assert.equal(await pending, null);
});

function confirmingForm(ctx, onSubmit) {
  return simpleForm({ fields: [], submitLabel: "Go", onSubmit, ctx });
}

function status(form) {
  return form.kidList().find((node) => node.className.startsWith("form-status"));
}

function submitButton(form) {
  const walk = (node) => (node.localName === "button" && node.getAttribute("type") === "submit" ? node : node.kidList().map(walk).find(Boolean));
  return walk(form);
}

async function submit(form) {
  form.dispatchEvent(new Event("submit"));
  for (let i = 0; i < 5; i += 1) await tick();
}

test("a cancelled confirm inside a form shows nothing and keeps the button usable", async () => {
  const ctx = testCtx({ lang: "en" });
  let sent = 0;
  const form = confirmingForm(ctx, async () => {
    await confirmOrCancel(ctx, PROMPT);
    sent += 1;
  });
  answerNextDialog(false);
  await submit(form);
  assert.equal(sent, 0);
  assert.equal(status(form).hidden, true);
  assert.equal(status(form).textContent, "");
  assert.equal(submitButton(form).disabled, false);
  assert.ok(new Cancelled() instanceof Error);
});

test("a confirmed form still says done", async () => {
  const ctx = testCtx({ lang: "en" });
  const form = confirmingForm(ctx, async () => confirmOrCancel(ctx, PROMPT));
  answerNextDialog(true);
  await submit(form);
  assert.equal(status(form).hidden, false);
  assert.equal(status(form).textContent, ctx.t("form.done"));
});

test("a cancelled confirm keeps no draft and says nothing, in a simple form and a JSON editor", async () => {
  const ctx = testCtx({ lang: "en" });
  const cancelled = async () => {
    throw new Cancelled();
  };
  const simple = simpleForm({ fields: [{ name: "note", label: "Note", type: "text" }], submitLabel: "Go", onSubmit: cancelled, draftKey: "cancel-simple", ctx });
  const editor = jsonEditor({ label: "Body", value: {}, submitLabel: "Go", onSubmit: cancelled, draftKey: "cancel-json", ctx });
  for (const form of [simple, editor]) {
    await submit(form);
    assert.equal(status(form).hidden, true);
    assert.equal(status(form).textContent, "");
    assert.equal(submitButton(form).disabled, false);
  }
  assert.equal(takeDraft("cancel-simple"), null);
  assert.equal(takeDraft("cancel-json"), null);
});

const TICKED = { ...PROMPT, tickLabel: "My plants are gone.", confirmLabel: "Release" };
const nodesOf = (node) => [...(node.children || [])].flatMap((child) => [child, ...nodesOf(child)]);
const tickBox = (dialog) => nodesOf(dialog).find((el) => el.getAttribute("type") === "checkbox");
const confirmButton = (dialog) => nodesOf(dialog).find((el) => el.getAttribute("type") === "submit");

test("a ticked confirmation confirms only once its box is ticked", async () => {
  const ctx = testCtx({ lang: "en" });
  const pending = confirmWithTick(ctx.t, TICKED);
  await tick();
  const [dialog] = openDialogs();
  assert.ok(dialog.textContent.includes(TICKED.tickLabel));
  assert.equal(confirmButton(dialog).disabled, true);

  answerNextDialog(true); // confirming without the tick does nothing
  assert.equal(openDialogs().length, 1);

  const box = tickBox(dialog);
  box.checked = true;
  box.dispatchEvent(new Event("change"));
  assert.equal(confirmButton(dialog).disabled, false);
  answerNextDialog(true);
  assert.equal(await pending, true);
});

test("a ticked confirmation can be cancelled", async () => {
  const ctx = testCtx({ lang: "en" });
  const pending = confirmWithTick(ctx.t, TICKED);
  await tick();
  tickBox(openDialogs()[0]).checked = true;
  answerNextDialog(false);
  assert.equal(await pending, false);
});

