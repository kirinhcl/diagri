import assert from "node:assert/strict";
import test from "node:test";

import { blocks } from "../../src/growbridge/web/workbench/ui/rich-text.js";

test("paragraphs, lists and headings are told apart; wrapped lines stay together", () => {
  const text = "## Data check\n**Coverage:** 100%\nno gaps\n\n- one\n- two\n  continued\n\n1. first\n2. second";
  assert.deepEqual(blocks(text), [
    { kind: "h", lines: ["Data check"] },
    { kind: "p", lines: ["**Coverage:** 100%\nno gaps"] },
    { kind: "ul", lines: ["one", "two\ncontinued"] },
    { kind: "ol", lines: ["first", "second"] },
  ]);
});

test("a blank line ends a list, and plain text stays one paragraph", () => {
  assert.deepEqual(blocks("- a\n\n- b"), [
    { kind: "ul", lines: ["a"] },
    { kind: "ul", lines: ["b"] },
  ]);
  assert.deepEqual(blocks("just text"), [{ kind: "p", lines: ["just text"] }]);
  assert.deepEqual(blocks(""), []);
});
