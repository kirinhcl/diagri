import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../../src/growbridge/web/workbench", import.meta.url));
const FORBIDDEN = /innerHTML|outerHTML|insertAdjacentHTML|document\.write/;

function jsFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return jsFiles(path);
    return entry.name.endsWith(".js") ? [path] : [];
  });
}

const files = jsFiles(ROOT);
const source = (file) => readFileSync(file, "utf8");

test("console scripts never inject HTML", () => {
  assert.ok(files.length > 0, "no console scripts found");
  for (const file of files) {
    assert.doesNotMatch(source(file), FORBIDDEN, relative(ROOT, file));
  }
});
