// Building blocks shared by the project, round and stage pages.
import { formatTime } from "../format.js";
import { confirmAction } from "./dialog.js";
import { clear, h } from "./dom.js";
import { errorDetail, errorLines } from "./forms.js";

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

// --- technical details: ids, hashes and raw values, folded away and copyable ----------------------
const isEmpty = (value) => value === null || value === undefined || value === "";
const valueText = (value) => (typeof value === "object" ? JSON.stringify(value, null, 2) : String(value));

// True once the text is on the clipboard; false when there is no clipboard or it refused (the text
// stays on the page to be selected by hand). Never throws.
export async function copyText(text) {
  try {
    const clipboard = globalThis.navigator ? globalThis.navigator.clipboard : undefined;
    if (!clipboard || typeof clipboard.writeText !== "function") return false;
    await clipboard.writeText(String(text));
    return true;
  } catch {
    return false;
  }
}

function copyButton(t, text, label) {
  const button = h("button", { class: "button button-quiet tech-copy", attrs: { type: "button" }, text: label });
  button.addEventListener("click", async () => {
    button.textContent = t((await copyText(text)) ? "tech.copied" : "tech.copyFailed");
  });
  return button;
}

// Closed by default: one row per value (label, the value as code, a copy button), then "copy all"
// for every "label: value" line. Empty values are left out; null when nothing is left.
export function techDetails(t, entries) {
  const rows = (entries || []).filter(([, value]) => !isEmpty(value)).map(([label, value]) => [String(label), valueText(value)]);
  if (rows.length === 0) return null;
  const items = rows.map(([label, text]) =>
    h("div", { class: "tech-row" }, h("dt", { text: label }), h("dd", {}, h("code", { text }), copyButton(t, text, t("tech.copy")))),
  );
  const all = rows.map(([label, text]) => `${label}: ${text}`).join("\n");
  return h(
    "details",
    { class: "tech-details" },
    h("summary", { text: t("tech.title") }),
    h("dl", { class: "tech-list" }, items),
    copyButton(t, all, t("tech.copyAll")),
  );
}

export function errorBox() {
  return h("div", { class: "form-status form-status-error", attrs: { role: "status", hidden: true } });
}

// An error's status, code and own words in the technical details; null when it has none.
export function errorFold(ctx, error) {
  return techDetails(ctx.t, errorDetail(error, ctx.t));
}

// The plain lines of an error as paragraphs, then its fold: what every error box that stays on a
// page shows.
export function errorParts(ctx, error) {
  const lines = errorLines(error, ctx.lang, ctx.t).map((line) => h("p", { text: line }));
  const fold = errorFold(ctx, error);
  return fold ? [...lines, fold] : lines;
}

// For a box a poll fills again and again: the same text as last time leaves it as it is, so a fold
// someone opened stays open (and its copy buttons where they were).
const shownText = new WeakMap();

export function replaceParts(box, nodes) {
  const text = nodes.map((node) => node.textContent).join("\n");
  if (box.childNodes.length > 0 && shownText.get(box) === text) return;
  shownText.set(box, text);
  box.replaceChildren(...nodes);
}

export function showErrors(box, error, ctx) {
  clear(box).append(...errorParts(ctx, error));
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
