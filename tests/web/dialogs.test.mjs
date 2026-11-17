import assert from "node:assert/strict";
import test from "node:test";

import { confirmAction } from "../../src/growbridge/web/workbench/ui/dialog.js";
import { Cancelled, confirmOrCancel, simpleForm } from "../../src/growbridge/web/workbench/ui/forms.js";
import { answerNextDialog, openDialogs } from "./support/dialogs.mjs";
import { testCtx } from "./support/render-page.mjs";

const PROMPT = { title: "Stop the round?", lines: ["It ends now.", "Nothing is lost."] };

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
