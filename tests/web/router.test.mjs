import test from "node:test";
import assert from "node:assert/strict";
import { hrefFor, parseHash } from "../../src/growbridge/web/workbench/router.js";

test("parseHash reads pages and decodes ids", () => {
  assert.deepEqual(parseHash(""), { page: "inbox", params: {} });
  assert.deepEqual(parseHash("#/"), { page: "inbox", params: {} });
  assert.deepEqual(parseHash("#/login"), { page: "login", params: {} });
  assert.deepEqual(parseHash("#/projects"), { page: "projects", params: {} });
  assert.deepEqual(parseHash("#/projects/p1"), { page: "project", params: { projectId: "p1" } });
  assert.deepEqual(parseHash("#/rounds/r1"), { page: "round", params: { roundId: "r1" } });
  assert.deepEqual(parseHash("#/stages/s%201"), { page: "stage", params: { stageId: "s 1" } });
  for (const p of ["alerts", "evidence", "compute", "safety"]) {
    assert.deepEqual(parseHash(`#/${p}`), { page: p, params: {} });
  }
});

test("unknown hashes are not_found", () => {
  for (const h of ["#/nope", "#/stages", "#/stages/a/b", "#/projects/p/x", "#/alerts/1"]) {
    assert.equal(parseHash(h).page, "not_found", h);
  }
});

test("hrefFor and parseHash round-trip", () => {
  const cases = [
    ["inbox", {}],
    ["login", {}],
    ["projects", {}],
    ["project", { projectId: "a/b c" }],
    ["round", { roundId: "r#1" }],
    ["stage", { stageId: "s 1?" }],
    ["safety", {}],
  ];
  for (const [page, params] of cases) {
    assert.deepEqual(parseHash(hrefFor(page, params)), { page, params });
  }
});
