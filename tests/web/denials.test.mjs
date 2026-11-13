import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DENIALS, describeDenial } from "../../src/growbridge/web/workbench/denials.js";

function wikiCodes() {
  const src = readFileSync(new URL("../../docs/wiki/en/Denial-Codes-and-Events.md", import.meta.url), "utf8");
  const section = src.split(/^## Denial codes\s*$/m)[1].split(/^## /m)[0];
  return [...section.matchAll(/^\| `([a-z_]+)` \|/gm)].map((m) => m[1]);
}

test("every wiki denial code is described in both languages", () => {
  const codes = wikiCodes();
  assert.equal(codes.length, 33);
  for (const code of [...codes, "validation", "network", "reauth_failed"]) {
    for (const lang of ["zh", "en"]) {
      const d = describeDenial(code, lang);
      assert.ok(d, `${code}/${lang}`);
      assert.ok(d.text.trim() && d.advice.trim(), `${code}/${lang}`);
    }
  }
  assert.deepEqual(Object.keys(DENIALS).sort(), [...codes, "validation", "network", "reauth_failed"].sort());
});

test("an unknown code is null", () => {
  assert.equal(describeDenial("nope", "en"), null);
  assert.equal(describeDenial(null, "zh"), null);
});
