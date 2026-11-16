import assert from "node:assert/strict";
import test from "node:test";

import en from "../../src/growbridge/web/workbench/i18n/en.js";
import zh from "../../src/growbridge/web/workbench/i18n/zh.js";
import { openRounds, statusText } from "../../src/growbridge/web/workbench/pages/conversation.js";

const ctx = { t: (key, vars) => (vars ? `${key}${JSON.stringify(vars)}` : key) };

test("a message can only be about an open round, newest first as listed", () => {
  const project = {
    rounds: [
      { round_id: "r3", state: "stage_review" },
      { round_id: "r2", state: "delivered" },
      { round_id: "r1", state: "aborted" },
      { round_id: "r0", state: "designing" },
    ],
  };
  assert.deepEqual(
    openRounds(project).map((r) => r.round_id),
    ["r3", "r0"],
  );
  assert.deepEqual(openRounds({}), []);
});

test("a handed-back task shows its reason; a finished one does not repeat 'run finished'", () => {
  const back = { role: "planner", text: "needs_attention", detail: { reason: "ended without saving" } };
  const done = { role: "orchestrator", text: "done", detail: { reason: "run finished" } };
  assert.match(statusText(ctx, back), /: ended without saving$/);
  assert.doesNotMatch(statusText(ctx, done), /run finished/);
  assert.match(statusText(ctx, { role: "planner", text: "follow_up", detail: {} }), /^chat.followUp/);
});

test("every conversation string exists in both languages", () => {
  const keys = (table) => Object.keys(table).filter((key) => key.startsWith("chat."));
  assert.deepEqual(keys(zh).sort(), keys(en).sort());
  assert.ok(keys(en).length > 10);
});

// Fills {placeholders} the way the console's translator does, so labels can be read in each language.
const tFor = (table) => (key, vars) => (table[key] ?? key).replace(/\{(\w+)\}/g, (_, name) => vars[name]);

test("an auditor entry is labelled as the auditor in both languages, not as system", () => {
  const followUp = { role: "auditor", text: "follow_up", detail: {} };
  assert.match(statusText({ t: tFor(en) }, followUp), /^Auditor /);
  assert.match(statusText({ t: tFor(zh) }, followUp), /^监察 Agent/);
  assert.doesNotMatch(statusText({ t: tFor(zh) }, followUp), /系统/);
});
