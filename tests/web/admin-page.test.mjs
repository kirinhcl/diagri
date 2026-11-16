import assert from "node:assert/strict";
import test from "node:test";

import { navItems } from "../../src/growbridge/web/workbench/ui/layout.js";
import { homeFor, hrefFor, parseHash } from "../../src/growbridge/web/workbench/router.js";
import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { bindFormContext } from "../../src/growbridge/web/workbench/ui/forms.js";
import { renderPage, testCtx } from "./support/render-page.mjs";
import { visibleText } from "./support/leaks.mjs";

const pages = (me) => navItems(me).map((item) => item.page);

test("the administration page lists accounts, locks and their history", async () => {
  const { element } = await renderPage("admin", {}, { lang: "en" });
  const text = visibleText(element);

  for (const expected of ["alice", "Administrator", "Disabled", "Greenhouse 1", "Released by force", "bob left"]) {
    assert.match(text, new RegExp(expected));
  }
});

test("the sidebar offers greenhouses only with multi-user, and administration only to administrators", () => {
  assert.ok(!pages({ multi_user: false, role: "admin" }).includes("greenhouses"));
  assert.ok(!pages(null).includes("admin"));
  assert.ok(pages({ multi_user: true, role: "user" }).includes("greenhouses"));
  assert.ok(!pages({ multi_user: true, role: "user" }).includes("admin"));
  assert.ok(pages({ multi_user: true, role: "admin" }).includes("admin"));
});

test("the new pages round-trip through the router", () => {
  for (const page of ["greenhouses", "admin"]) assert.deepEqual(parseHash(hrefFor(page)), { page, params: {} });
});

test("a newly signed-in operator without a greenhouse starts at the greenhouses", () => {
  assert.equal(homeFor({ multi_user: true, greenhouses: [] }), "#/greenhouses");
  assert.equal(homeFor({ multi_user: true, greenhouses: ["gh-01"] }), "#/");
  assert.equal(homeFor({ multi_user: false }), "#/");
});

for (const page of ["environment", "safety"]) {
  test(`the ${page} page asks to lock the greenhouse first instead of failing`, async () => {
    const ctx = testCtx({ lang: "en" });
    bindFormContext(ctx);
    ctx.api.get = async () => {
      throw new ApiError(403, "not_lock_holder", "lock this greenhouse first");
    };
    const module = await import(`../../src/growbridge/web/workbench/pages/${page}.js`);

    const { element } = await module.render(ctx);

    assert.match(visibleText(element), /you do not hold this one/);
    assert.match(visibleText(element), /Lock a greenhouse/);
  });
}
