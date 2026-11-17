import assert from "node:assert/strict";
import test from "node:test";

import { loadCapabilities } from "../../src/growbridge/web/workbench/capabilities.js";
import { FIXTURES, testCtx } from "./support/render-page.mjs";

test("capabilities are read once per page and a failed read gives null", async () => {
  const ctx = testCtx();
  const first = await loadCapabilities(ctx);
  const second = await loadCapabilities(ctx);

  assert.deepEqual(first, FIXTURES["capabilities.json"]);
  assert.equal(second, first);
  assert.equal(ctx.api.calls.filter((call) => call.path === "/capabilities").length, 1);

  const broken = testCtx();
  broken.api.get = async () => {
    throw new Error("down");
  };
  assert.equal(await loadCapabilities(broken), null);
  assert.equal(await loadCapabilities(testCtx({ fixtures: { "capabilities.json": null } })), null);

  const nextPage = testCtx();
  await loadCapabilities(nextPage);
  assert.equal(nextPage.api.calls.length, 1, "a new page load reads again");
});
