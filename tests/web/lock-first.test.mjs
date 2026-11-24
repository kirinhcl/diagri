import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { renderPage } from "./support/render-page.mjs";
import { visibleText } from "./support/leaks.mjs";

const notHeld = () => {
  throw new ApiError(403, "not_lock_holder", "lock this greenhouse to see its environment");
};
const house = (state, extra = {}) => ({ greenhouses: [{ id: "gh-01", name: "Chamber 1", state, locked_at: null, controlled: true }, { id: "gh-03", name: "Chamber 3", state: "mine", locked_at: 1, controlled: false, ...extra }] });

for (const [page, path] of [["environment", "GET /environment"], ["safety", "GET /safety"]]) {
  test(`${page}: a page of a greenhouse held by someone else names it`, async () => {
    const options = { lang: "en", answers: { [path]: notHeld }, fixtures: { "greenhouses.json": house("taken") } };
    const { element } = await renderPage(page, {}, options);
    const text = visibleText(element);

    assert.match(text, /This page shows Chamber 1, the greenhouse this installation controls, and you do not hold it\./);
    assert.match(text, /Chamber 1 is held by someone else right now\./);
  });
}

test("a free greenhouse the page belongs to is offered to lock", async () => {
  const options = { lang: "en", answers: { "GET /environment": notHeld }, fixtures: { "greenhouses.json": house("free") } };
  const { element } = await renderPage("environment", {}, options);

  assert.match(visibleText(element), /Lock Chamber 1/);
});

test("without the greenhouse list the note stays general", async () => {
  const options = { lang: "en", answers: { "GET /environment": notHeld }, fixtures: { "greenhouses.json": null } };
  const { element } = await renderPage("environment", {}, options);

  assert.match(visibleText(element), /you do not hold this one/);
});
