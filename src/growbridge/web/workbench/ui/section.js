// Building blocks shared by the project, round and stage pages.
import { formatAge, formatDateTime } from "../format.js";
import { confirmAction } from "./dialog.js";
import { clear, h } from "./dom.js";
import { errorDetail, errorLines } from "./forms.js";

let counter = 0;

export function timeText(ctx, epoch) {
  if (typeof epoch !== "number" || !Number.isFinite(epoch)) return "—";
  return formatDateTime(epoch, siteZone(ctx), ctx.lang, nowSeconds(ctx));
}

function siteZone(ctx) {
  return (ctx.me && ctx.me.timezone) || "UTC";
}

// The page's clock in epoch seconds: the ctx's `now` when one is given (tests pin it), else the browser's.
export function nowSeconds(ctx) {
  return ctx.now ?? Date.now() / 1000;
}

const SECONDS_PER_DAY = 86400;
const JUST_NOW_SECONDS = 60;

// A <time> for list cells: relative within the last day, the full time otherwise (also for the future).
export function timeCell(ctx, epoch) {
  if (typeof epoch !== "number" || !Number.isFinite(epoch)) return h("time", { text: "—" });
  const full = timeText(ctx, epoch);
  const age = nowSeconds(ctx) - epoch;
  let text = full;
  if (age >= 0 && age < SECONDS_PER_DAY) {
    text = age < JUST_NOW_SECONDS ? ctx.t("time.justNow") : ctx.t("time.ago", { duration: formatAge(ctx.t, age) });
  }
  return h("time", { text, attrs: { datetime: new Date(epoch * 1000).toISOString(), title: full } });
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

export const FOLDED_CHARS = 240; // a follow-up task's question carries the whole summary of the task before it

// A long text shows its start; the rest opens on request. A short one is the text itself.
export function foldedText(ctx, text, chars = FOLDED_CHARS) {
  const full = String(text || "");
  if (full.length <= chars) return full;
  return h(
    "details",
    { class: "folded-text" },
    h("summary", { text: `${full.slice(0, chars).trimEnd()}… ${ctx.t("common.showAll")}` }),
    h("p", { class: "folded-text-full", text: full }),
  );
}

// After a successful write: say so, then read the page again (nothing is shown before the server agrees).
export function afterWrite(ctx, message) {
  ctx.notify(message || ctx.t("form.done"), "ok");
  ctx.reload();
}

// --- technical details: ids, hashes and raw values, folded away and copyable ----------------------
const isEmpty = (value) => value === null || value === undefined || value === "";
const valueText = (value) => (typeof value === "object" ? JSON.stringify(value, null, 2) : String(value));

async function writeClipboard(text) {
  try {
    const clipboard = globalThis.navigator ? globalThis.navigator.clipboard : undefined;
    if (!clipboard || typeof clipboard.writeText !== "function") return false;
    await clipboard.writeText(String(text));
    return true;
  } catch {
    return false;
  }
}

// Selects what node shows and asks the browser to copy the selection: true only when it says it did.
// The selection is left in place either way, so Cmd/Ctrl+C still works by hand.
function copySelection(node) {
  try {
    const doc = node.ownerDocument || globalThis.document;
    if (!doc || typeof doc.getSelection !== "function" || typeof doc.createRange !== "function") return false;
    const selection = doc.getSelection();
    const range = doc.createRange();
    range.selectNodeContents(node);
    selection.removeAllRanges();
    selection.addRange(range);
    return typeof doc.execCommand === "function" && doc.execCommand("copy") === true;
  } catch {
    return false;
  }
}

// True once the text is on the clipboard. Where there is no Clipboard API (plain http on the site's
// LAN) or it refused, the node holding the text is selected and copied that way; when that fails too
// the text stays selected on the page for the person to copy. Never throws.
export async function copyText(text, node) {
  if (await writeClipboard(text)) return true;
  return node ? copySelection(node) : false;
}

function copyButton(t, text, label, node) {
  const button = h("button", { class: "button button-quiet tech-copy", attrs: { type: "button" }, text: label });
  button.addEventListener("click", async () => {
    button.textContent = t((await copyText(text, node)) ? "tech.copied" : "tech.copyFailed");
  });
  return button;
}

// Closed by default: one row per value (label, the value as code, a copy button), then "copy all"
// for every "label: value" line. Empty values are left out; null when nothing is left.
export function techDetails(t, entries, { summary } = {}) {
  const rows = (entries || []).filter(([, value]) => !isEmpty(value)).map(([label, value]) => [String(label), valueText(value)]);
  if (rows.length === 0) return null;
  const items = rows.map(([label, text]) => {
    const code = h("code", { text });
    return h("div", { class: "tech-row" }, h("dt", { text: label }), h("dd", {}, code, copyButton(t, text, t("tech.copy"), code)));
  });
  const all = rows.map(([label, text]) => `${label}: ${text}`).join("\n");
  const list = h("dl", { class: "tech-list" }, items);
  return h(
    "details",
    { class: "tech-details" },
    h("summary", { text: summary || t("tech.title") }),
    list,
    copyButton(t, all, t("tech.copyAll"), list),
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
  const lines = errorLines(error, ctx.lang, ctx.t, ctx).map((line) => h("p", { text: line }));
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
