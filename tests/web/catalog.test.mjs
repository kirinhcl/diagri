// Every code the server can send has text in both catalogs, and no page turns a server value into a
// catalog key by hand: those go through labelOr, which never shows a key or the raw code.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import en from "../../src/growbridge/web/workbench/i18n/en.js";
import zh from "../../src/growbridge/web/workbench/i18n/zh.js";
import { labelOr, makeT } from "../../src/growbridge/web/workbench/i18n.js";
import { severityPill, stateGroup, statePill } from "../../src/growbridge/web/workbench/ui/status.js";
import { installFakeDom } from "./support/render-page.mjs";
import { visibleText } from "./support/leaks.mjs";

const KNOWN = JSON.parse(readFileSync(new URL("./fixtures/known-codes.json", import.meta.url), "utf8"));
const ROOT = fileURLToPath(new URL("../../src/growbridge/web/workbench", import.meta.url));
// Prefixes whose dynamic part is always a constant of the console itself, never a server value.
const KEY_BUILDERS_ALLOWED = new Set(["nav", "stage", "measure", "metric", "env.channel", "env.window", "round.choice"]);
const TEMPLATE_KEY = /\bt\(\s*`([^`$]*)\$\{/g; // t(`prefix.${value}`)
const JOINED_KEY = /\bt\(\s*(["'])([^"']*)\1\s*\+/g; // t("prefix." + value)

function jsFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return jsFiles(path);
    return entry.name.endsWith(".js") ? [path] : [];
  });
}

function keyPrefixes(text) {
  const built = [...text.matchAll(TEMPLATE_KEY)].map((match) => match[1]);
  const joined = [...text.matchAll(JOINED_KEY)].map((match) => match[2]);
  return [...built, ...joined].map((prefix) => prefix.replace(/\.$/, ""));
}

// "file:line prefix" for each catalog key built from a value under a prefix outside the allowed list.
function hiddenKeyBuilders(file) {
  const name = relative(ROOT, file);
  return readFileSync(file, "utf8")
    .split("\n")
    .flatMap((line, index) =>
      keyPrefixes(line)
        .filter((prefix) => !KEY_BUILDERS_ALLOWED.has(prefix))
        .map((prefix) => `${name}:${index + 1} ${prefix || "(no prefix)"}`),
    );
}

test("every console-known code has text in both catalogs", () => {
  const missing = [];
  for (const [prefix, codes] of Object.entries(KNOWN)) {
    if (prefix.startsWith("_")) continue;
    assert.ok(KNOWN._sources[prefix], `known-codes.json says where ${prefix} codes come from`);
    for (const code of codes) {
      for (const [lang, table] of [["en", en], ["zh", zh]]) {
        if (!table[`${prefix}.${code}`]) missing.push(`${lang} ${prefix}.${code}`);
      }
    }
  }
  assert.deepEqual(missing, []);
});

test("labelOr never prints a key", () => {
  const t = makeT("zh");
  assert.equal(labelOr(t, "state", "running"), "运行中");
  assert.equal(labelOr(t, "state", "brand_new_state"), "未知（技术详情）");
  assert.equal(labelOr(t, "state", null), "—");
  assert.equal(labelOr(t, "state", undefined), "—");
  assert.equal(labelOr(t, "state", ""), "—");
  assert.equal(labelOr(t, "safety.op", ">="), "不低于");
  const tEn = makeT("en");
  assert.equal(labelOr(tEn, "alert.kind", "brand_new_kind"), "Unknown (technical details)");
  assert.equal(labelOr(tEn, "severity", "critical"), "Critical");
});

test("texts that later pages are tested against", () => {
  assert.equal(zh["history.event.end_condition_met"], "结束条件已满足");
  assert.equal(zh["alert.kind.audit_finding"], "审计备注");
  assert.equal(zh["diff.field.level"], "档位");
  assert.deepEqual(
    [">", "<", ">=", "<="].map((op) => [zh[`safety.op.${op}`], en[`safety.op.${op}`]]),
    [["高于", "above"], ["低于", "below"], ["不低于", "at or above"], ["不高于", "at or below"]],
  );
});

test("compute phases have labels and colour groups", () => {
  assert.equal(stateGroup("failed"), "onsite");
  assert.equal(stateGroup("cancelled"), "done");
  assert.equal(stateGroup("queued"), "active");
  assert.equal(stateGroup("prepared"), "waiting");
  for (const phase of ["failed", "cancelled", "queued", "prepared"]) {
    assert.notEqual(labelOr(makeT("en"), "state", phase), "Unknown (technical details)", phase);
  }
});

test("a pill for a state or severity the catalog lacks says unknown, not the code", () => {
  const dom = installFakeDom();
  try {
    const t = makeT("zh");
    assert.equal(visibleText(statePill(t, "brand_new_state")), "未知（技术详情）");
    assert.equal(statePill(t, "failed").textContent, "失败");
    assert.equal(visibleText(severityPill(t, "fatal")), "未知（技术详情）");
  } finally {
    dom.restore();
  }
});

test("no page builds a catalog key from a server value without labelOr", () => {
  const files = jsFiles(ROOT).filter((file) => !relative(ROOT, file).startsWith("i18n"));
  assert.ok(files.some((file) => file.includes("pages")), "no console pages found");
  assert.deepEqual(files.flatMap(hiddenKeyBuilders), []);
});

test("the key scan sees both ways of building a key", () => {
  const sample = 'ctx.t(`state.${x}`); t("severity." + y); t(`nav.${page}`); t(`stage.${name}.title`); split(`a.${b}`)';
  assert.deepEqual(keyPrefixes(sample), ["state", "nav", "stage", "severity"]);
});
