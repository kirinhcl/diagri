// Building blocks shared by the project, round and stage pages.
import { formatTime } from "../format.js";
import { confirmAction } from "./dialog.js";
import { clear, h } from "./dom.js";
import { errorLines } from "./forms.js";

let counter = 0;

export function timeText(ctx, epoch) {
  if (typeof epoch !== "number" || !Number.isFinite(epoch)) return "—";
  const zone = (ctx.me && ctx.me.timezone) || "UTC";
  return `${formatTime(epoch, zone, ctx.lang)} ${zone}`;
}

export function pageHead(title, lead) {
  const text = h("div", {}, h("h1", { text: title }), lead ? h("p", { class: "page-lead", text: lead }) : null);
  return h("header", { class: "page-head" }, text);
}

// A titled block of a page; the heading names the section for assistive technology.
export function section(title, ...children) {
  const id = `section-${++counter}`;
  return h(
    "section",
    { class: "block", attrs: { "aria-labelledby": id } },
    h("header", { class: "block-head" }, h("h2", { attrs: { id }, text: title })),
    ...children,
  );
}

export function note(text) {
  return h("p", { class: "block-note", text });
}

// Label and value pairs; a missing value is shown as a dash.
export function keyValues(pairs) {
  const empty = (value) => value === null || value === undefined || value === "";
  const rows = pairs.map(([label, value]) =>
    h("div", { class: "kv-row" }, h("dt", { text: label }), h("dd", {}, empty(value) ? "—" : value)),
  );
  return h("dl", { class: "kv" }, rows);
}

export function codeBlock(text) {
  return h("pre", { class: "code-block", text });
}

// After a successful write: say so, then read the page again (nothing is shown before the server agrees).
export function afterWrite(ctx, message) {
  ctx.notify(message || ctx.t("form.done"), "ok");
  ctx.reload();
}

export function errorBox() {
  return h("div", { class: "form-status form-status-error", attrs: { role: "status", hidden: true } });
}

export function showErrors(box, error, ctx) {
  clear(box).append(...errorLines(error, ctx.lang, ctx.t).map((line) => h("p", { text: line })));
  box.hidden = false;
}

// A button that asks first. run() does the write; a refusal is written under the button.
export function confirmedButton(ctx, { label, title, lines = [], tone = "quiet", run }) {
  const box = errorBox();
  const button = h("button", { class: ["button", `button-${tone}`], attrs: { type: "button" }, text: label });
  button.addEventListener("click", async () => {
    box.hidden = true;
    if (!(await confirmAction(ctx.t, { title, lines, confirmLabel: label }))) return;
    button.disabled = true;
    try {
      await run();
    } catch (error) {
      showErrors(box, error, ctx);
    } finally {
      button.disabled = false;
    }
  });
  return h("div", { class: "action" }, button, box);
}
