// The views main.js shows instead of a page (FRM-03): what went wrong in plain words, the error itself only in
// the technical details, and a retry. main.js starts the console when it is imported, so the views live in
// ui/problem.js where a test can reach them.
import assert from "node:assert/strict";
import test from "node:test";

import { makeT } from "../../src/growbridge/web/workbench/i18n.js";
import { loadFailedView, problemView } from "../../src/growbridge/web/workbench/ui/problem.js";
import { assertNoLeaks, visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { installFakeDom } from "./support/render-page.mjs";

const IMPORT_ERROR = "Failed to fetch dynamically imported module: https://lab.example/workbench/pages/round.js";
const buttonsOf = (node) => [...(node.localName === "button" ? [node] : []), ...[...(node.children || [])].flatMap(buttonsOf)];
// The technical details have a copy button of their own, so the retry is found by its text.
const retryOf = (view, t) => buttonsOf(view).filter((button) => button.textContent === t("common.retry"));

test("a page that failed to load says so in plain words; the browser's error is only in the details", () => {
  for (const lang of ["zh", "en"]) {
    installFakeDom();
    const t = makeT(lang);
    let retried = 0;
    const view = loadFailedView(t, new TypeError(IMPORT_ERROR), () => {
      retried += 1;
    });
    const text = visibleText(view);
    assert.ok(text.includes(t("error.title")) && text.includes(t("page.loadFailed")), text);
    assert.ok(!text.includes("Failed to fetch"), `${lang}: the raw error stays folded: ${text}`);
    assert.ok(visibleTextIncludingDetails(view).includes(IMPORT_ERROR));
    assert.equal(view.getAttribute("role"), "alert");
    assertNoLeaks(view);
    const [retry] = retryOf(view, t);
    retry.dispatchEvent(new Event("click"));
    assert.equal(retried, 1);
  }
});

test("a page that rendered nothing shows the same sentence with no details", () => {
  installFakeDom();
  const t = makeT("en");
  const view = loadFailedView(t, null, () => {});
  assert.equal(visibleText(view), visibleTextIncludingDetails(view));
  assert.ok(visibleText(view).includes(t("page.loadFailed")));
});

test("a refusal while a page loads shows its lines under one title, and no retry unless asked", () => {
  installFakeDom();
  const t = makeT("en");
  const view = problemView(t, [t("error.title"), "Sign in again."], { details: [[t("tech.reason"), "session"]] });
  assert.equal(visibleText(view).split(t("error.title")).length - 1, 1, "the title is the heading, not a line again");
  assert.ok(visibleText(view).includes("Sign in again."));
  assert.equal(retryOf(view, t).length, 0);
  assert.ok(!visibleText(view).includes("session") && visibleTextIncludingDetails(view).includes("session"));
});
