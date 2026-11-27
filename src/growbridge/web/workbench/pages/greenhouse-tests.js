// Device tests on the Greenhouses page (design 2026-11-27): before a round, the holder runs each
// device briefly; the server keeps time and puts the device's settings back.
import { h } from "../ui/dom.js";
import { confirmedButton, errorBox, note, showErrors, timeText } from "../ui/section.js";
import { labelOr } from "../i18n.js";

const CHANNELS = ["light", "exhaust", "fan", "pump"];
const TICK_MS = 1000;
// Catalog keys by server value, written out so every key is a literal.
const BUTTON_KEYS = {
  light: "greenhouses.tests.light",
  exhaust: "greenhouses.tests.exhaust",
  fan: "greenhouses.tests.fan",
  pump: "greenhouses.tests.pump",
};
const RESULT_KEYS = {
  restored: "greenhouses.tests.result.restored",
  restore_failed: "greenhouses.tests.result.restoreFailed",
  protected: "greenhouses.tests.result.protected",
  not_run: "greenhouses.tests.result.notRun",
};
const SHORT_KEYS = {
  restored: "greenhouses.tests.short.restored",
  restore_failed: "greenhouses.tests.short.restoreFailed",
  protected: "greenhouses.tests.short.protected",
  not_run: "greenhouses.tests.short.notRun",
};

const base = (row) => `/greenhouses/${encodeURIComponent(row.id)}`;

// What one finished test shows: the state when settled on site, else its result.
function outcome(ctx, record) {
  if (record.state === "settled_onsite") return ctx.t("greenhouses.tests.short.settled");
  return ctx.t(SHORT_KEYS[record.result] || "greenhouses.tests.short.running");
}

function historyList(ctx, history) {
  if (!history.length) return note(ctx.t("greenhouses.tests.none"));
  const items = history.map((record) => {
    const parts = [timeText(ctx, record.started_at), record.operator, labelOr(ctx.t, "channel", record.channel), outcome(ctx, record)];
    return h("li", { text: parts.join(" · ") });
  });
  return h("div", {}, h("h4", { text: ctx.t("greenhouses.tests.history") }), h("ul", { class: "test-history" }, ...items));
}

// A countdown on the status line while the server runs the test.
function countdown(ctx, status, seconds) {
  let left = seconds;
  const show = () => (status.textContent = ctx.t("greenhouses.tests.running", { seconds: Math.max(left, 0) }));
  show();
  const timer = setInterval(() => {
    left -= 1;
    show();
  }, TICK_MS);
  return () => clearInterval(timer);
}

function testButtons(ctx, row) {
  const status = h("p", { class: "cell-sub", attrs: { role: "status" } });
  const box = errorBox();
  const all = [];
  const run = async (channel) => {
    box.hidden = true;
    all.forEach((button) => (button.disabled = true));
    const stop = countdown(ctx, status, row.test_seconds[channel]);
    try {
      const reply = await ctx.api.post(`${base(row)}/test/${channel}`, {}, { action: ctx.t(BUTTON_KEYS[channel], { seconds: row.test_seconds[channel] }) });
      status.textContent = ctx.t(RESULT_KEYS[reply.result] || RESULT_KEYS.restore_failed);
      if (reply.result === "restore_failed") ctx.reload();
    } catch (error) {
      status.textContent = "";
      showErrors(box, error, ctx);
    } finally {
      stop();
      all.forEach((button) => (button.disabled = false));
    }
  };
  const blocks = CHANNELS.map((channel) => testButton(ctx, row, channel, run, all));
  return [h("div", { class: "test-buttons" }, ...blocks), note(ctx.t("greenhouses.tests.pumpWarn")), status, box];
}

function testButton(ctx, row, channel, run, all) {
  const label = ctx.t(BUTTON_KEYS[channel], { seconds: row.test_seconds[channel] });
  if (channel === "pump") {
    const title = ctx.t("greenhouses.tests.pumpTitle", { seconds: row.test_seconds.pump });
    const block = confirmedButton(ctx, { label, title, lines: [ctx.t("greenhouses.tests.pumpWarn")], tone: "primary", run: () => run(channel) });
    all.push(block.firstChild); // confirmedButton: the button, then its error box
    return block;
  }
  const button = h("button", { class: "button button-primary", attrs: { type: "button" }, text: label });
  button.addEventListener("click", () => run(channel));
  all.push(button);
  return button;
}

function settleForm(ctx, row, testId) {
  const box = errorBox();
  const hint = h("p", { class: "cell-sub", attrs: { role: "status" } });
  const input = h("input", { attrs: { type: "text", name: "note", maxlength: "500", "aria-label": ctx.t("greenhouses.tests.settleNote"), placeholder: ctx.t("greenhouses.tests.settleNote") } });
  const label = ctx.t("greenhouses.tests.settle");
  const button = h("button", { class: "button button-quiet", attrs: { type: "submit" }, text: label });
  const form = h("form", { class: "settle-form" }, input, button, hint, box);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = String(input.value || "").trim();
    hint.textContent = text ? "" : ctx.t("greenhouses.tests.noteFirst");
    if (!text) return;
    try {
      await ctx.api.post(`${base(row)}/tests/${encodeURIComponent(testId)}/settle`, { note: text }, { action: label });
      ctx.reload();
    } catch (error) {
      showErrors(box, error, ctx);
    }
  });
  return form;
}

function unsettledBlock(ctx, row) {
  const { test_id: testId, channel } = row.test_unsettled;
  const label = ctx.t("greenhouses.tests.retry");
  const box = errorBox();
  const retry = h("button", { class: "button button-primary", attrs: { type: "button" }, text: label });
  retry.addEventListener("click", async () => {
    retry.disabled = true;
    try {
      await ctx.api.post(`${base(row)}/tests/${encodeURIComponent(testId)}/retry`, {}, { action: label });
      ctx.reload();
    } catch (error) {
      showErrors(box, error, ctx);
    } finally {
      retry.disabled = false;
    }
  });
  const warning = ctx.t("greenhouses.tests.unsettled", { device: labelOr(ctx.t, "channel", channel) });
  return [h("p", { class: "block-note warn", text: warning }), retry, box, settleForm(ctx, row, testId)];
}

function body(ctx, row) {
  if (row.test_unsettled) return unsettledBlock(ctx, row);
  if (!row.testable) return [note(ctx.t("greenhouses.tests.busy"))];
  return [note(ctx.t("greenhouses.tests.lead")), ...testButtons(ctx, row)];
}

// The device test block of one greenhouse the caller holds and this installation drives.
export function testSection(ctx, row, history) {
  const title = h("h3", { text: ctx.t("greenhouses.tests.title", { name: row.name }) });
  return h("div", { class: "device-tests" }, title, ...body(ctx, row), historyList(ctx, history));
}

// Whether a row gets the block: the caller's own, driven by this installation.
export function hasTests(row) {
  return row.state === "mine" && row.controlled === true && row.test_seconds;
}
