import test from "node:test";
import assert from "node:assert/strict";
import en from "../../src/growbridge/web/workbench/i18n/en.js";
import zh from "../../src/growbridge/web/workbench/i18n/zh.js";
import { LANGS, initialLang, makeT } from "../../src/growbridge/web/workbench/i18n.js";

test("zh and en have the same keys and no empty text", () => {
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort());
  for (const [k, v] of [...Object.entries(zh), ...Object.entries(en)]) {
    assert.equal(typeof v, "string", k);
    assert.ok(v.trim().length > 0, k);
  }
});

test("makeT fills placeholders and falls back to the key", () => {
  assert.deepEqual(LANGS, ["zh", "en"]);
  const t = makeT("en");
  assert.equal(t("inbox.empty"), en["inbox.empty"]);
  assert.equal(t("no.such.key"), "no.such.key");
  assert.equal(t("common.hello", { name: "Ann" }), "Hello, Ann");
  assert.equal(makeT("zh")("common.hello", { name: "小李" }), "你好，小李");
});

test("initialLang prefers stored value then browser language", () => {
  assert.equal(initialLang("en", "zh-CN"), "en");
  assert.equal(initialLang("zh", "en-US"), "zh");
  assert.equal(initialLang(null, "zh-TW"), "zh");
  assert.equal(initialLang(null, "fi"), "en");
  assert.equal(initialLang("fr", "fi"), "en");
});

test("textOr fills a known key and never returns a key", async () => {
  const { textOr } = await import("../../src/growbridge/web/workbench/i18n.js");
  const t = makeT("en");
  assert.equal(textOr(t, "common", "hello", { name: "Ann" }), "Hello, Ann");
  assert.equal(textOr(t, ["common"], "hello", { name: "Bo" }), "Hello, Bo");
  assert.equal(textOr(t, "common", "no.such"), null);
  assert.equal(textOr(t, "common", null), null);
  assert.equal(textOr(t, "common", ""), null);
});
