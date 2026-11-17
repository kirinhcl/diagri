import test from "node:test";
import assert from "node:assert/strict";
import { VALIDATION_TYPES, positionText, problemText } from "../../src/growbridge/web/workbench/validation.js";
import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { errorDetail, simpleForm } from "../../src/growbridge/web/workbench/ui/forms.js";
import { makeT } from "../../src/growbridge/web/workbench/i18n.js";
import { findLeaks, visibleText } from "./support/leaks.mjs";
import { installFakeDom, testCtx } from "./support/render-page.mjs";

const settle = () => new Promise((resolve) => setImmediate(resolve));

const LANGS = ["zh", "en"];

test("a missing field next to its input says it is required, in the reader's language", async () => {
  installFakeDom();
  const fields = [{ name: "id", label: "Id" }];
  const refusal = new ApiError(422, "validation", "validation", [{ loc: ["body", "id"], msg: "Field required", type: "missing", limits: {} }]);
  for (const [lang, expected] of [["zh", "必须填写"], ["en", "This is required."]]) {
    const form = simpleForm({ fields, submitLabel: "Save", onSubmit: async () => { throw refusal; }, ctx: testCtx({ lang }) });
    form.dispatchEvent(new Event("submit"));
    await settle();
    const text = visibleText(form);
    assert.ok(text.includes(expected), text);
    assert.ok(!text.includes("Field required"), text);
  }
});

test("a too-long text says the maximum length", () => {
  const info = { type: "string_too_long", limits: { max_length: 1200 }, msg: "String should have at most 1200 characters" };
  assert.ok(problemText(testCtx({ lang: "zh" }), info).includes("1,200"));
  assert.match(problemText(testCtx({ lang: "en" }), info), /at most 1,200 characters/);
});

test("a number bound says the bound as written", () => {
  const en = testCtx({ lang: "en" });
  assert.equal(problemText(en, { type: "greater_than", limits: { gt: 0.5 } }), "Must be greater than 0.5.");
  assert.equal(problemText(en, { type: "less_than_equal", limits: { le: 10 } }), "Must be at most 10.");
  assert.equal(problemText(testCtx({ lang: "zh" }), { type: "greater_than_equal", limits: { ge: 2 } }), "至少 2");
  assert.ok(!problemText(en, { type: "greater_than", limits: {} }).includes("{"));
});

test("a path in the JSON editor reads as positions: item numbers count from 1, keys stay as typed", () => {
  assert.equal(positionText(testCtx({ lang: "zh" }), ["body", "treatments", 0, "id"]), "「treatments」 › 第 1 项 › 「id」");
  assert.equal(positionText(testCtx({ lang: "en" }), ["body", "treatments", 2, "id"]), "“treatments” › item 3 › “id”");
  assert.equal(positionText(testCtx({ lang: "en" }), []), "");
});

test("an unknown validation type falls back to a general sentence and keeps Pydantic's words in the details", () => {
  const ctx = testCtx({ lang: "en" });
  const text = problemText(ctx, { type: "something_new", limits: {}, msg: "Weird thing" });
  assert.ok(!text.includes("Weird") && !text.includes("something_new"), text);
  assert.equal(text, makeT("en")("msg.validation.other"));
  const error = new ApiError(422, "validation", "validation", [{ loc: ["body", "x"], msg: "Weird thing", type: "something_new", limits: {} }]);
  assert.ok(JSON.stringify(errorDetail(error, ctx.t)).includes("Weird thing"));
});

test("every validation type has a text in both languages", () => {
  for (const lang of LANGS) {
    const t = makeT(lang);
    for (const type of VALIDATION_TYPES) {
      const key = `msg.validation.${type}`;
      assert.notEqual(t(key), key, `${lang} ${type}`);
      const text = problemText(testCtx({ lang }), { type, limits: { min_length: 1, max_length: 2, gt: 1, ge: 1, lt: 1, le: 1 } });
      assert.ok(text.trim() && !text.includes("{"), `${lang} ${type}: ${text}`);
      assert.deepEqual(findLeaks(text), [], `${lang} ${type}`);
    }
    assert.notEqual(t("msg.validation.other"), "msg.validation.other");
  }
});
