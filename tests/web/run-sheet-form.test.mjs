// The run-sheet form: what it shows, what it changes, and that everything else goes back as stored.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { clearDrafts } from "../../src/growbridge/web/workbench/drafts.js";
import { runSheetForm } from "../../src/growbridge/web/workbench/pages/run-sheet-form.js";
import { bindFormContext, saveAllDrafts } from "../../src/growbridge/web/workbench/ui/forms.js";
import { assertNoPendingDialogAnswers, resetDialogs } from "./support/dialogs.mjs";
import { FIXTURES, testCtx } from "./support/render-page.mjs";

afterEach(() => {
  assertNoPendingDialogAnswers();
  resetDialogs();
  clearDrafts();
});

const PENDING = FIXTURES["run-sheet-pending.json"];
const FULL = FIXTURES["run-sheet.json"];
const CAPS = FIXTURES["capabilities.json"];
const settle = () => new Promise((resolve) => setImmediate(resolve));
const find = (node, match) => [...(match(node) ? [node] : []), ...[...(node.children || [])].flatMap((child) => find(child, match))];
const byClass = (node, name) => find(node, (el) => el.classList && el.classList.contains(name));
const named = (node, name) => find(node, (el) => el.getAttribute && el.getAttribute("name") === name);
const change = (input, value) => {
  input.value = value;
  input.dispatchEvent(new Event("input"));
  input.dispatchEvent(new Event("change"));
};
const clone = (value) => JSON.parse(JSON.stringify(value));
const errorsIn = (node) => byClass(node, "field-error").map((error) => error.textContent).filter(Boolean);

function open({ review = PENDING, capabilities = CAPS, fail = null, draftKey } = {}) {
  const ctx = testCtx({ lang: "en" });
  bindFormContext(ctx);
  const sent = [];
  const onSubmit = async (body) => {
    sent.push(body);
    if (fail) throw fail;
  };
  const form = runSheetForm(ctx, { review, roundId: "round-1", capabilities, onSubmit, draftKey });
  return { ctx, form, sent };
}
const submit = async (form) => {
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  await settle();
};
// A group of the form, by the name its heading shows.
const section = (ctx, form, key) => find(form, (el) => el.localName === "fieldset" && find(el, (leg) => leg.localName === "legend" && leg.textContent === ctx.t(key)).length > 0)[0];
const rowsOf = (group) => byClass(group, "row-group-row");
const field = (node, name) => named(node, name)[0];
const reviewWith = (change) => {
  const review = clone(PENDING);
  change(review.run_sheet);
  return review;
};

test("an unchanged form sends the run sheet back byte for byte", async () => {
  for (const review of [PENDING, FULL]) {
    const { form, sent } = open({ review });
    await submit(form);
    assert.equal(sent.length, 1);
    assert.equal(sent[0].round_id, "round-1");
    assert.equal(JSON.stringify(sent[0].run_sheet), JSON.stringify(review.run_sheet));
  }
});

test("changing one timed action's level changes only that value", async () => {
  const { ctx, form, sent } = open();
  const rows = rowsOf(section(ctx, form, "runsheet.form.timed"));
  change(field(rows[0], "level"), "65");
  await submit(form);
  const expected = clone(PENDING.run_sheet);
  expected.timed_actions[0].level = 65;
  expected.version = PENDING.run_sheet.version + 1;
  assert.equal(JSON.stringify(sent[0].run_sheet), JSON.stringify(expected));
});

test("a changed form sends the next version, an unchanged one keeps the stored version and approval", async () => {
  const { ctx, form, sent } = open();
  await submit(form);
  assert.equal(sent[0].run_sheet.version, PENDING.run_sheet.version);
  const changed = open();
  change(field(rowsOf(section(changed.ctx, changed.form, "runsheet.form.timed"))[0], "level"), "65");
  await submit(changed.form);
  assert.equal(changed.sent[0].run_sheet.version, PENDING.run_sheet.version + 1);
  assert.ok(byClass(form, "run-sheet-version-note").length === 1);
  assert.match(byClass(form, "run-sheet-version-note")[0].textContent, new RegExp(String(PENDING.run_sheet.version + 1)));
  assert.ok(ctx);
});

test("keys the form does not show (feedback rules, care rules, ownership, ids, timezone) are sent back unchanged", async () => {
  const review = reviewWith((sheet) => {
    sheet.feedback_rules = [{ id: "fb-1", sensor: "temp", note: "keep" }];
    sheet.care_rules = [{ id: "care-1", anything: [1, 2.0, { deep: true }] }];
    sheet.channels[0].ownership = "device";
    sheet.channels[0].onsite_handling = "Check the light by hand.";
    sheet.timed_actions[0].evidence = "card-7";
    sheet.timed_actions[0].extra_flag = "kept";
    sheet.timezone = "Asia/Tokyo";
  });
  const { ctx, form, sent } = open({ review });
  change(field(section(ctx, form, "runsheet.form.duration"), "duration_days"), "9");
  change(field(rowsOf(section(ctx, form, "runsheet.form.timed"))[1], "level"), "5");
  await submit(form);
  const expected = clone(review.run_sheet);
  expected.version += 1;
  expected.duration_seconds = 9 * 86400;
  expected.timed_actions[1].level = 5;
  assert.equal(JSON.stringify(sent[0].run_sheet), JSON.stringify(expected));
});

test("a level outside the channel's range is refused beside its row", async () => {
  const { ctx, form, sent } = open();
  const timed = section(ctx, form, "runsheet.form.timed");
  const rows = rowsOf(timed);
  change(field(rows[0], "level"), "150");
  await submit(form);
  assert.equal(sent.length, 0);
  assert.equal(errorsIn(rows[0]).length, 1);
  assert.equal(errorsIn(rows[1]).length, 0);
  // the channel's own retained level follows its channel's range (the fan stops at 10)
  change(field(rows[0], "level"), "60");
  const channels = rowsOf(section(ctx, form, "runsheet.form.channels"));
  change(field(channels[2], "retained_level"), "11");
  await submit(form);
  assert.equal(sent.length, 0);
  assert.equal(errorsIn(channels[2]).length, 1);
});

test("without level ranges no range is checked in the browser (the server judges)", async () => {
  const { ctx, form, sent } = open({ capabilities: null });
  change(field(rowsOf(section(ctx, form, "runsheet.form.timed"))[0], "level"), "150");
  await submit(form);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].run_sheet.timed_actions[0].level, 150);
});

test("durations are entered in days, hours and minutes and sent in seconds", async () => {
  const { ctx, form, sent } = open();
  const duration = section(ctx, form, "runsheet.form.duration");
  assert.equal(field(duration, "duration_days").value, "7");
  assert.equal(field(duration, "duration_hours").value, "0");
  const wait = section(ctx, form, "runsheet.form.wait");
  assert.equal(field(wait, "max_wait_hours").value, "6");
  change(field(duration, "duration_days"), "2");
  change(field(duration, "duration_hours"), "3");
  change(field(duration, "duration_minutes"), "4");
  change(field(wait, "max_wait_hours"), "0");
  change(field(wait, "max_wait_minutes"), "90");
  await submit(form);
  assert.equal(sent[0].run_sheet.duration_seconds, 2 * 86400 + 3 * 3600 + 4 * 60);
  assert.equal(sent[0].run_sheet.max_wait_seconds, 5400);
});

test("a stored length that is not a whole number of minutes keeps its seconds", async () => {
  const review = reviewWith((sheet) => {
    sheet.duration_seconds = 90.5;
  });
  const { ctx, form, sent } = open({ review });
  const duration = section(ctx, form, "runsheet.form.duration");
  assert.equal(field(duration, "duration_minutes").value, "1");
  assert.equal(field(duration, "duration_rest").value, "30.5");
  await submit(form);
  assert.equal(sent[0].run_sheet.duration_seconds, 90.5);
  change(field(duration, "duration_minutes"), "2");
  await submit(form);
  assert.equal(sent[1].run_sheet.duration_seconds, 150.5);
});

test("sampling and what happens when the wait runs out are changed in place", async () => {
  const { form, sent } = open();
  change(field(form, "interval_seconds"), "30");
  change(field(form, "on_expiry"), "stop");
  await submit(form);
  const expected = clone(PENDING.run_sheet);
  expected.version += 1;
  expected.sampling.interval_seconds = 30;
  expected.on_expiry = "stop";
  assert.equal(JSON.stringify(sent[0].run_sheet), JSON.stringify(expected));
});

test("an irrigation task's seconds must be above 0 and at most 60; other kinds have no seconds", async () => {
  const { ctx, form, sent } = open({ review: FULL });
  const rows = rowsOf(section(ctx, form, "runsheet.form.tasks"));
  assert.equal(field(rows[0], "seconds").value, "20");
  for (const bad of ["0", "-5", "61"]) {
    change(field(rows[0], "seconds"), bad);
    await submit(form);
    assert.equal(sent.length, 0, bad);
    assert.equal(errorsIn(rows[0]).length, 1, bad);
  }
  change(field(rows[0], "seconds"), "60");
  // a photo task may not carry seconds
  change(field(rows[2], "seconds"), "5");
  await submit(form);
  assert.equal(sent.length, 0);
  assert.equal(errorsIn(rows[2]).length, 1);
  change(field(rows[2], "seconds"), "");
  await submit(form);
  assert.equal(sent.length, 1);
  const tasks = sent[0].run_sheet.manual_tasks;
  assert.equal(tasks[0].seconds, 60);
  assert.equal(Object.hasOwn(tasks[1], "seconds"), false);
  assert.equal(Object.hasOwn(tasks[2], "seconds"), false);
});

test("rows can be added, and removing one keeps the others exactly as stored", async () => {
  const { ctx, form, sent } = open({ review: FULL });
  const tasks = section(ctx, form, "runsheet.form.tasks");
  [...tasks.children].at(-1).dispatchEvent(new Event("click"));
  const rows = rowsOf(tasks);
  assert.equal(rows.length, 4);
  assert.equal(field(rows[3], "kind").value, "", "a new select starts on the prompt");
  change(field(rows[3], "id"), "photo-2");
  change(field(rows[3], "kind"), "photo");
  change(field(rows[3], "at"), "12:30");
  change(field(rows[0], "id"), "irrigate-daily");
  find(rows[1], (el) => el.localName === "button")[0].dispatchEvent(new Event("click"));
  await submit(form);
  const expected = clone(FULL.run_sheet);
  expected.version += 1;
  expected.manual_tasks = [expected.manual_tasks[0], expected.manual_tasks[2], { id: "photo-2", kind: "photo", at: "12:30", make_up_allowed: false }];
  assert.equal(JSON.stringify(sent[0].run_sheet), JSON.stringify(expected));
});

const REPEATS = [
  // the row, its list's heading, the row made to repeat an earlier one, the field and the text beside it
  ["timed action", "runsheet.form.timed", 1, "id", "light-on", "Another row in this list already has this name."],
  ["manual task", "runsheet.form.tasks", 2, "id", "irrigate-daily", "Another row in this list already has this name."],
  ["end action", "runsheet.form.end", 1, "channel", "light", "Another end action already sets this channel."],
];

for (const [row, heading, at, name, value, text] of REPEATS) {
  test(`a ${row} that repeats an earlier row's ${name} is refused beside the repeat, and nothing is sent`, async () => {
    const { ctx, form, sent } = open({ review: FULL });
    const rows = rowsOf(section(ctx, form, heading));
    change(field(rows[at], name), value);
    await submit(form);
    assert.equal(sent.length, 0);
    assert.deepEqual(errorsIn(rows[0]), []);
    assert.deepEqual(errorsIn(rows[at]), [text]);
  });
}

test("a repeated name is judged with the trimmed text, and the same name in another list is no repeat", async () => {
  const { ctx, form, sent } = open({ review: FULL });
  const timed = rowsOf(section(ctx, form, "runsheet.form.timed"));
  const tasks = rowsOf(section(ctx, form, "runsheet.form.tasks"));
  change(field(timed[1], "id"), "  light-on ");
  await submit(form);
  assert.equal(sent.length, 0);
  assert.equal(errorsIn(timed[1]).length, 1);
  change(field(timed[1], "id"), "light-off");
  change(field(tasks[0], "id"), "light-on"); // a task may share a timed action's name
  await submit(form);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].run_sheet.manual_tasks[0].id, "light-on");
});

test("end action rows follow their channel's range, and a row's 422 lands on that row", async () => {
  const fail = new ApiError(422, "validation", "invalid", [{ loc: ["body", "run_sheet", "end_actions", 1], msg: "bad level", type: "value_error", limits: {} }]);
  const { ctx, form, sent } = open({ review: FULL, fail });
  const rows = rowsOf(section(ctx, form, "runsheet.form.end"));
  await submit(form);
  assert.equal(sent.length, 1);
  assert.equal(errorsIn(rows[0]).length, 0);
  assert.equal(errorsIn(rows[1]).length, 1);
});

test("a timed action removed before one with its own evidence leaves that evidence on the later row", async () => {
  const review = reviewWith((sheet) => {
    sheet.timed_actions[1].evidence = "card-off";
  });
  const { ctx, form, sent } = open({ review });
  find(rowsOf(section(ctx, form, "runsheet.form.timed"))[0], (el) => el.localName === "button")[0].dispatchEvent(new Event("click"));
  await submit(form);
  const expected = clone(review.run_sheet);
  expected.version += 1;
  expected.timed_actions = expected.timed_actions.slice(1);
  assert.equal(JSON.stringify(sent[0].run_sheet), JSON.stringify(expected));
  assert.equal(sent[0].run_sheet.timed_actions[0].evidence, "card-off");
});

test("a row's own check (no field in the place) lands on that row's main field", async () => {
  const fail = new ApiError(422, "validation", "invalid", [
    { loc: ["body", "run_sheet", "timed_actions", 0], msg: "level out of range", type: "value_error", limits: {} },
    { loc: ["body", "run_sheet", "manual_tasks", 2], msg: "only irrigation", type: "value_error", limits: {} },
  ]);
  const { ctx, form } = open({ review: FULL, fail });
  await submit(form);
  const timed = rowsOf(section(ctx, form, "runsheet.form.timed"));
  const tasks = rowsOf(section(ctx, form, "runsheet.form.tasks"));
  assert.equal(errorsIn(timed[0]).length, 1);
  assert.equal(errorsIn(timed[1]).length, 0);
  assert.equal(errorsIn(tasks[2]).length, 1);
  assert.equal(errorsIn(field(tasks[2], "seconds").parentNode.parentNode).length, 1);
});

test("a 422 on a rule's duration does not land on the run length", async () => {
  const fail = new ApiError(422, "validation", "invalid", [{ loc: ["body", "run_sheet", "feedback_rules", 0, "duration_seconds"], msg: "bad", type: "value_error", limits: {} }]);
  const { ctx, form } = open({ fail });
  await submit(form);
  assert.equal(errorsIn(section(ctx, form, "runsheet.form.duration")).length, 0);
});

test("a stored retained level out of range is refused before sending, changed or not, as the server refuses it", async () => {
  const review = reviewWith((sheet) => {
    sheet.channels[2].retained_level = 40; // the fan stops at 10
  });
  const { ctx, form, sent } = open({ review });
  const channels = rowsOf(section(ctx, form, "runsheet.form.channels"));
  await submit(form);
  assert.equal(sent.length, 0);
  assert.equal(errorsIn(channels[2]).length, 1);
  change(field(channels[2], "retained_level"), "10");
  await submit(form);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].run_sheet.channels[2].retained_level, 10);
});

test("a draft kept on another run sheet is dropped with a note, never put on the new one", async () => {
  const first = open({ draftKey: "run-sheet:test-form" });
  change(field(first.form, "interval_seconds"), "99");
  change(field(rowsOf(section(first.ctx, first.form, "runsheet.form.timed"))[0], "level"), "11");
  document.body.append(first.form); // only a form on the page is kept
  saveAllDrafts();
  first.form.remove();
  const next = reviewWith((sheet) => {
    sheet.timed_actions = [{ id: "fan-low", channel: "fan", at: "03:00", level: 1, evidence: "card-FAN" }, ...sheet.timed_actions];
    sheet.channels = [...sheet.channels].reverse();
    sheet.duration_seconds = 14 * 86400;
  });
  next.run_sheet_digest = "other-digest";
  const second = open({ review: next, draftKey: "run-sheet:test-form" });
  const notes = find(second.form, (el) => el.localName === "p").map((p) => p.textContent);
  assert.ok(notes.includes(second.ctx.t("runsheet.form.draftStale")));
  assert.ok(!notes.includes(second.ctx.t("form.draftRestored")));
  await submit(second.form);
  assert.equal(JSON.stringify(second.sent[0].run_sheet), JSON.stringify(next.run_sheet));
});

test("a draft on the same run sheet is restored, and channels come back by name", async () => {
  const first = open({ draftKey: "run-sheet:test-form" });
  const channels = rowsOf(section(first.ctx, first.form, "runsheet.form.channels"));
  change(field(channels[0], "retained_level"), "5"); // light
  document.body.append(first.form); // only a form on the page is kept
  saveAllDrafts();
  first.form.remove();
  const same = reviewWith((sheet) => {
    sheet.channels = [...sheet.channels].reverse(); // same digest, other order
  });
  const second = open({ review: same, draftKey: "run-sheet:test-form" });
  await submit(second.form);
  const sent = second.sent[0].run_sheet.channels;
  assert.equal(sent.find((plan) => plan.channel === "light").retained_level, 5);
  assert.equal(sent.find((plan) => plan.channel === "pump").retained_level, 0);
});
