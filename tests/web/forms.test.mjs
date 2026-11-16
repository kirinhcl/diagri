import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { describeDenial } from "../../src/growbridge/web/workbench/denials.js";
import {
  dropDetachedDraftSavers,
  errorDetail,
  errorLines,
  registerDraftSaver,
  saveAllDrafts,
  worthKeeping,
} from "../../src/growbridge/web/workbench/ui/forms.js";

const t = (key) => `t:${key}`;

test("a known refusal shows its explanation and advice; the server's own words go to the details", () => {
  const error = new ApiError(409, "state", "stage stage-1 is paused; nothing to approve");
  const { text, advice } = describeDenial("state", "en");
  assert.deepEqual(errorLines(error, "en", t), [text, advice]);
  assert.deepEqual(errorDetail(error, t), [
    ["t:tech.httpStatus", 409],
    ["t:tech.code", "state"],
    ["t:tech.serverMessage", "stage stage-1 is paused; nothing to approve"],
  ]);
});

test("the same two lines when the message only repeats the code or is missing", () => {
  const { text, advice } = describeDenial("validation", "zh");
  assert.deepEqual(errorLines(new ApiError(422, "validation", "validation"), "zh", t), [text, advice]);
  assert.deepEqual(errorLines(new ApiError(403, "scope", ""), "zh", t).length, 2);
});

test("an unknown code or a plain error shows only the title; its message is a detail", () => {
  assert.deepEqual(errorLines(new ApiError(409, "brand_new", "changed"), "en", t), ["t:error.title"]);
  assert.deepEqual(errorLines(new Error("boom"), "en", t), ["t:error.title"]);
  assert.deepEqual(errorDetail(new Error("boom"), t), [["t:tech.message", "boom"]]);
  assert.deepEqual(errorDetail("thrown as text", t), [["t:tech.message", "thrown as text"]]);
  assert.deepEqual(errorLines(null, "en", t), ["t:error.title"]);
});

test("the console's own refusal keeps its catalog line as the second line", () => {
  assert.deepEqual(errorLines(new ApiError(0, "not_approved", "changed"), "en", t), ["t:error.title", "changed"]);
});

test("a lost session saves the draft of every form still on the page", () => {
  const saved = [];
  const shown = { isConnected: true };
  const other = { isConnected: true };
  const off = registerDraftSaver(shown, () => saved.push("shown"));
  const offOther = registerDraftSaver(other, () => saved.push("other"));
  assert.equal(saveAllDrafts(), 2);
  assert.deepEqual(saved, ["shown", "other"]);
  off();
  offOther();
});

test("a form that left the document is dropped, not saved", () => {
  const saved = [];
  const gone = { isConnected: true };
  registerDraftSaver(gone, () => saved.push("gone"));
  gone.isConnected = false;
  assert.equal(saveAllDrafts(), 0);
  gone.isConnected = true; // even if put back, it was dropped
  assert.equal(saveAllDrafts(), 0);
  assert.deepEqual(saved, []);
});

test("after a page is shown, the forms of the page before are dropped", () => {
  const saved = [];
  const old = { isConnected: false };
  const current = { isConnected: true };
  registerDraftSaver(old, () => saved.push("old"));
  const off = registerDraftSaver(current, () => saved.push("current"));
  assert.equal(dropDetachedDraftSavers(), 1);
  old.isConnected = true;
  assert.equal(saveAllDrafts(), 1);
  assert.deepEqual(saved, ["current"]);
  off();
});

test("an unregistered form is not saved", () => {
  const saved = [];
  const form = { isConnected: true };
  registerDraftSaver(form, () => saved.push("form"))();
  assert.equal(saveAllDrafts(), 0);
});

test("a form started from a restored draft keeps its values on a lost session", () => {
  assert.equal(worthKeeping(null, { a: "x" }), true);
});

test("a form started fresh keeps its values only when they changed", () => {
  assert.equal(worthKeeping({ a: "x" }, { a: "x" }), false);
  assert.equal(worthKeeping({ a: "x" }, { a: "y" }), true);
});
