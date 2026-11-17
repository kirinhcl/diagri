import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DENIALS, describeDenial } from "../../src/growbridge/web/workbench/denials.js";

// Codes the console makes itself: a 422 body, no answer, an unreadable answer, a wrong secret.
const CLIENT_CODES = ["validation", "network", "server_error", "reauth_failed"];

function wikiCodes() {
  const src = readFileSync(new URL("../../docs/wiki/en/Denial-Codes-and-Events.md", import.meta.url), "utf8");
  const section = src.split(/^## Denial codes\s*$/m)[1].split(/^## /m)[0];
  return [...section.matchAll(/^\| `([a-z_]+)` \|/gm)].map((m) => m[1]);
}

test("every wiki denial code is described in both languages", () => {
  const codes = wikiCodes();
  assert.equal(codes.length, 38);
  for (const code of [...codes, ...CLIENT_CODES]) {
    for (const lang of ["zh", "en"]) {
      const d = describeDenial(code, lang);
      assert.ok(d, `${code}/${lang}`);
      assert.ok(d.text.trim() && d.advice.trim(), `${code}/${lang}`);
    }
  }
  assert.deepEqual(Object.keys(DENIALS).sort(), [...codes, ...CLIENT_CODES].sort());
});

test("a server error does not claim the server was unreachable, and says the action may have run", () => {
  assert.notEqual(describeDenial("server_error", "en").text, describeDenial("network", "en").text);
  assert.match(describeDenial("server_error", "en").text, /may or may not have been carried out/);
  assert.match(describeDenial("server_error", "zh").text, /可能已经执行，也可能没有/);
});

test("an unknown code is null", () => {
  assert.equal(describeDenial("nope", "en"), null);
  assert.equal(describeDenial(null, "zh"), null);
});

test("the re-authentication and lock-out denials say password, and a lock-out says how long", () => {
  for (const code of ["reauth_required", "reauth_failed", "locked"]) {
    const zh = describeDenial(code, "zh");
    const en = describeDenial(code, "en");
    assert.doesNotMatch(`${zh.text}${zh.advice}`, /口令/, code);
    assert.doesNotMatch(`${en.text}${en.advice}`, /secret/i, code);
  }
  assert.match(describeDenial("locked", "zh").text, /已锁定 15 分钟/);
  assert.match(describeDenial("locked", "en").text, /locked for 15 minutes/);
});
