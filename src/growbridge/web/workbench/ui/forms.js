// Forms that put each refusal where it belongs: field errors beside the field, the rest above the button.
import { ApiError, singleFlight } from "../api.js";
import { describeDenial } from "../denials.js";
import { saveDraft, stripSecrets, takeDraft } from "../drafts.js";
import { formatTime, zonedToEpoch } from "../format.js";
import { messageParts } from "../messages.js";
import { locatedText, problemText } from "../validation.js";
import { confirmAction } from "./dialog.js";
import { clear, h } from "./dom.js";
import { techDetails } from "./section.js";

// A datetime-local value may carry zero seconds ("…T16:00:00"); zonedToEpoch takes minutes only.
const ZERO_SECONDS = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}):00(?:\.0+)?$/;
let bound = { t: (key) => key, lang: "en", me: null, notify: () => {}, reload: () => {} };
let counter = 0;
const nextId = (prefix) => `${prefix}-${++counter}`;

// main.js binds each page's context; a form uses it unless the page passed its own ctx.
export function bindFormContext(ctx) {
  bound = ctx;
}

function contextOf(own) {
  return own || bound;
}

export function minutePrecision(text) {
  return text.replace(ZERO_SECONDS, "$1");
}

// --- drafts on a lost session: every form with a draft key says how to save itself now ----------
// main.js calls saveAllDrafts() before it leaves for the sign-in page, whatever request found the
// session gone, and dropDetachedDraftSavers() after each page is shown. A form that left the
// document is dropped and never saved.
const draftSavers = new Set();

export function registerDraftSaver(form, save) {
  const entry = { form, save };
  draftSavers.add(entry);
  return () => draftSavers.delete(entry);
}

export function dropDetachedDraftSavers() {
  let dropped = 0;
  for (const entry of [...draftSavers]) {
    if (entry.form.isConnected) continue;
    draftSavers.delete(entry);
    dropped += 1;
  }
  return dropped;
}

export function saveAllDrafts() {
  dropDetachedDraftSavers();
  for (const entry of draftSavers) entry.save();
  return draftSavers.size;
}

// The console's own refusal (stage and safety approval): its message is catalog text, not the server's.
const OWN_REFUSAL = "not_approved";

// At most two plain lines; what the server said in its own words is in errorDetail. No answer at all
// is one line; a known code is [explanation, advice]; a 404 without a code is "not found".
export function errorLines(error, lang, t, ctx = { lang, t }) {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "network") return [t("error.network")];
  if (code === OWN_REFUSAL && error.message) return [t("error.title"), String(error.message)];
  const reasoned = error instanceof ApiError && error.reason ? messageParts(ctx, "denial", error.reason, error.params) : null;
  if (reasoned?.known) return reasoned.action ? [reasoned.text, reasoned.action] : [reasoned.text];
  const known = code ? describeDenial(code, lang) : null;
  if (known) return [known.text, known.advice];
  if (error instanceof ApiError && error.status === 404 && !code) return [t("error.notFound")];
  return [t("error.title")];
}

// What api.js writes itself when the server's answer had no words of its own ("HTTP 502: not JSON").
const CONSOLE_MESSAGE = /^HTTP \d+/;

// Pydantic's own words for each problem, with where it was found (for the technical details).
function validationLines(fields) {
  if (!Array.isArray(fields) || fields.length === 0) return null;
  return fields.map(({ loc, msg }) => `${(loc || []).join(" › ")}: ${msg}`).join("\n");
}

// [label, value] pairs for the technical details: HTTP status, code and the message as it came (a
// message that only repeats the code is left out). The labels use t, else the bound page's.
export function errorDetail(error, t = bound.t) {
  if (!error) return [];
  const isApi = error instanceof ApiError;
  const message = typeof error === "object" ? String(error.message || "") : String(error); // a thrown string too
  const answered = isApi && error.status > 0; // status 0: no answer, or the console's own refusal
  const fromServer = answered && !CONSOLE_MESSAGE.test(message);
  const entries = [
    [t("tech.httpStatus"), answered ? error.status : null],
    [t("tech.code"), isApi ? error.code : null],
    [t("tech.reason"), isApi ? error.reason : null],
    [t("tech.params"), isApi && error.reason && Object.keys(error.params || {}).length > 0 ? error.params : null],
    [t(fromServer ? "tech.serverMessage" : "tech.message"), isApi && message === error.code ? null : message],
    [t("tech.validation"), isApi ? validationLines(error.fields) : null],
  ];
  return entries.filter(([, value]) => value !== null && value !== undefined && value !== "");
}

// Thrown from a form's onSubmit when the person said no in a confirm dialog: nothing happened,
// so the form says nothing.
export class Cancelled extends Error {
  constructor() {
    super("cancelled");
    this.name = "Cancelled";
  }
}

// Asks the confirm dialog; returns when confirmed, throws Cancelled when not.
export async function confirmOrCancel(ctx, prompt) {
  if (!(await confirmAction(ctx.t, prompt))) throw new Cancelled();
}

// Plain lines, then (for a refusal) the folded technical details.
function showStatus(status, lines, kind, details = null) {
  clear(status);
  status.className = `form-status form-status-${kind}`;
  status.hidden = lines.length === 0 && !details;
  for (const line of lines) status.append(h("p", { text: line }));
  if (details) status.append(details);
}

function showRefusal(status, error, t, lines) {
  showStatus(status, lines, "error", techDetails(t, errorDetail(error, t)));
}

// The form, its status line and its submit button; run() goes through singleFlight.
function formFrame(submitLabel, children, run, getCtx) {
  const status = h("div", { class: "form-status", attrs: { role: "status", "aria-live": "polite", hidden: true } });
  const button = h("button", { class: "button button-primary", attrs: { type: "submit" }, text: submitLabel });
  const form = h("form", { class: "form" }, ...children, status, h("div", { class: "form-actions" }, button));
  const guarded = singleFlight(async () => {
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    try {
      await run();
    } finally {
      button.disabled = false;
      form.removeAttribute("aria-busy");
    }
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    guarded().catch((error) => {
      if (error instanceof Cancelled) return showStatus(status, [], "info");
      const ctx = getCtx();
      showRefusal(status, error, ctx.t, errorLines(error, ctx.lang, ctx.t, ctx));
    });
  });
  return { form, status };
}

// Every refusal is written to the form's own status line; some also keep a draft or reload the page.
function handleFailure(error, ctx, { status, keepDraft, showValidation }) {
  if (error instanceof Cancelled) {
    showStatus(status, [], "info");
    return;
  }
  const lines = errorLines(error, ctx.lang, ctx.t, ctx);
  const code = error instanceof ApiError ? error.code : null;
  if (code === "validation") {
    showRefusal(status, error, ctx.t, [...lines, ...showValidation(error.fields, ctx)]);
    return;
  }
  showRefusal(status, error, ctx.t, lines);
  if (code === "session") keepDraft();
  if (code === "state") {
    // The object may just have been changed by someone else: say so and read the page again.
    ctx.notify(lines.join(" "), "error");
    ctx.reload();
  }
}

export function initialText(field, timeZone, lang) {
  if (field.type === "password" || field.value === undefined || field.value === null) return "";
  if (Array.isArray(field.value)) return field.value.join("\n");
  if (field.type === "datetime" && typeof field.value === "number") {
    return formatTime(field.value, timeZone, lang).replace(" ", "T");
  }
  return String(field.value);
}

function optionList(field, value) {
  return (field.options || []).map((option) => {
    const isPair = option !== null && typeof option === "object";
    const { value: optionValue, label } = isPair ? option : { value: option, label: option };
    const attrs = { value: String(optionValue), selected: String(optionValue) === value };
    return h("option", { attrs, text: label ?? optionValue });
  });
}

function control(field, attrs, value) {
  const limits = { min: field.min, max: field.max, maxlength: field.maxlength };
  if (field.type === "checkbox") return h("input", { class: "input-check", attrs: { ...attrs, type: "checkbox", checked: value === "true" } });
  // `code` fields (a script) are monospace, tall, never spell-checked, and have no maxlength attribute: a browser would cut a long paste silently, so the length is checked (in code points) beside the field instead.
  if (field.type === "textarea" && field.code) return h("textarea", { class: "input input-area input-code", attrs: { ...attrs, rows: 10, spellcheck: "false" }, text: value });
  if (field.type === "textarea") return h("textarea", { class: "input input-area", attrs: { ...attrs, maxlength: limits.maxlength }, text: value });
  if (field.type === "select") return h("select", { class: "input", attrs }, optionList(field, value));
  const types = { number: "number", datetime: "datetime-local", password: "password", hidden: "hidden" };
  const type = types[field.type] || "text";
  const extra = { type, value: type === "password" ? null : value, maxlength: limits.maxlength };
  if (type === "number") Object.assign(extra, { step: field.step ?? "any", min: limits.min, max: limits.max });
  if (type === "password") extra.autocomplete = "current-password";
  return h("input", { class: "input", attrs: { ...attrs, ...extra } });
}

// The options a text field suggests; the values are attributes only, never page text.
function suggestionOptions(values) {
  return (values || []).map((value) => h("option", { attrs: { value: String(value) } }));
}

// The text a control holds; a check box holds "true" or "false".
const readText = (entry) => (entry.field.type === "checkbox" ? String(entry.input.checked) : entry.input.value);
function writeText(entry, text) {
  if (entry.field.type === "checkbox") entry.input.checked = text === "true";
  else entry.input.value = text;
}

export function fieldRow(field, value, timeZone) {
  const id = nextId("field");
  const errorId = `${id}-error`;
  const zoneId = `${id}-zone`;
  const hintId = `${id}-hint`;
  const isTime = field.type === "datetime";
  const describedBy = [isTime && zoneId, field.hint && hintId, errorId].filter(Boolean).join(" ");
  const list = Array.isArray(field.suggestions) ? h("datalist", { attrs: { id: `${id}-list` } }, suggestionOptions(field.suggestions)) : null;
  const attrs = { id, name: field.name, required: Boolean(field.required), "aria-describedby": describedBy, list: list && `${id}-list` };
  const input = control(field, attrs, value);
  const error = h("p", { class: "field-error", attrs: { id: errorId, hidden: true } });
  if (field.type === "hidden") return { field, input, row: h("div", { attrs: { hidden: true } }, input, error), error, list };
  const zone = isTime ? h("span", { class: "field-zone", attrs: { id: zoneId }, text: timeZone }) : null;
  const row = h(
    "div",
    { class: "field" },
    h("label", { class: "field-label", attrs: { for: id }, text: field.label }),
    h("div", { class: "field-control" }, input, field.unit !== undefined && h("span", { class: "field-unit", text: field.unit }), zone, list),
    field.hint && h("p", { class: "field-hint", attrs: { id: hintId }, text: field.hint }),
    error,
  );
  return { field, input, row, error, list };
}

export function setFieldError(entry, message) {
  entry.error.textContent = message || "";
  entry.error.hidden = !message;
  if (message) entry.input.setAttribute("aria-invalid", "true");
  else entry.input.removeAttribute("aria-invalid");
}

function limitError(field, value, t) {
  if (typeof value === "number") {
    if (field.min !== undefined && value < field.min) return t("form.tooSmall", { min: field.min });
    if (field.max !== undefined && value > field.max) return t("form.tooBig", { max: field.max });
  } else if (field.maxlength !== undefined && [...String(value)].length > field.maxlength) {
    return t("form.tooLong", { max: field.maxlength });
  }
  return null;
}

function convertOne(field, text, timeZone, t) {
  if (field.parse) return field.parse(text, t);
  if (field.type === "number") {
    const number = Number(text);
    if (!Number.isFinite(number)) return { error: t("form.badNumber") };
    const error = limitError(field, number, t);
    return error ? { error } : { value: number };
  }
  if (field.type === "datetime") {
    try {
      return { value: zonedToEpoch(minutePrecision(text), timeZone).epoch };
    } catch {
      return { error: t("form.badTime", { zone: timeZone }) };
    }
  }
  const error = limitError(field, text, t);
  return error ? { error } : { value: text };
}

// Empty optional fields are left out of the request so the server applies its defaults.
export function convert(entries, timeZone, t) {
  const values = {};
  let valid = true;
  for (const entry of entries) {
    const text = readText(entry);
    if (entry.field.type === "checkbox") {
      const unticked = entry.field.required && text !== "true";
      setFieldError(entry, unticked ? t("form.required") : "");
      valid = valid && !unticked;
      values[entry.field.name] = text === "true";
    } else if (text === "") {
      if (entry.field.required) setFieldError(entry, t("form.required"));
      valid = valid && !entry.field.required;
    } else {
      const result = convertOne(entry.field, text, timeZone, t);
      setFieldError(entry, result.error);
      if (result.error) valid = false;
      else values[entry.field.name] = result.value;
    }
  }
  return valid ? values : null;
}

// Puts each 422 error beside its field; returns the lines for errors that match no field. A hidden
// field's error could not be seen beside it, so it is one of those lines, under the field's label
// (never its name), or alone when the field has none.
export function placeFieldErrors(entries, fieldErrors, ctx) {
  const byName = (hidden) => new Map(entries.filter((entry) => (entry.field.type === "hidden") === hidden).map((entry) => [entry.field.name, entry]));
  const shown = byName(false);
  const unseen = byName(true);
  const rest = [];
  for (const problem of fieldErrors) {
    const { loc } = problem;
    const name = loc.find((part) => shown.has(part));
    const hidden = unseen.get(loc.find((part) => unseen.has(part)));
    const what = problemText(ctx, problem);
    if (name) setFieldError(shown.get(name), what);
    else if (hidden) rest.push(hidden.field.label ? `${hidden.field.label}${ctx.t("validation.sep")}${what}` : what);
    else rest.push(locatedText(ctx, problem));
  }
  return rest;
}

// One row per field, filled from the draft (never a password) or from the field's own value.
function formEntries(fields, draft, zone, lang) {
  return fields.map((field) => {
    const restored = draft && field.type !== "password" && Object.hasOwn(draft, field.name);
    return fieldRow(field, restored ? String(draft[field.name]) : initialText(field, zone, lang), zone);
  });
}

const rawValues = (entries) => Object.fromEntries(entries.map((entry) => [entry.field.name, readText(entry)]));

// On a lost session the form keeps its values (never a password) when they differ from what it
// started with, or when it started from a restored draft.
export function worthKeeping(start, now) {
  if (!start) return true;
  return Object.keys(now).some((name) => now[name] !== start[name]);
}

// A part may keep its own draft: draft() gives plain data, restore(data) takes it back. A form with
// such parts saves {fields, parts: {name: data}}; a draft of plain fields (older) restores as before.
const partDrafts = (parts) => Object.fromEntries(parts.filter((part) => part.draft).map((part) => [part.name, part.draft()]));
const packDraft = (parts, fields, partData) => (parts.some((part) => part.draft) ? { fields, parts: partData } : fields);
const isPackedDraft = (draft) => Boolean(draft) && Object.hasOwn(draft, "fields") && Object.hasOwn(draft, "parts");

function keepOnSessionLoss(form, draftKey, entries, restored, parts) {
  const secretNames = entries.filter((entry) => entry.field.type === "password").map((entry) => entry.field.name);
  const read = () => ({ fields: stripSecrets(rawValues(entries), secretNames), data: partDrafts(parts) });
  const start = restored ? null : read();
  registerDraftSaver(form, () => {
    const now = read();
    const same = start && JSON.stringify(start.data) === JSON.stringify(now.data);
    if (!same || worthKeeping(start && start.fields, now.fields)) saveDraft(draftKey, packDraft(parts, now.fields, now.data));
  });
}

// What the page that made a form may still do with it: read and fill fields in, change suggestions.
const formParts = new WeakMap();

function partOf(form, name) {
  const own = formParts.get(form);
  if (!own) throw new TypeError("not a form made by simpleForm");
  const entry = own.entries.find((item) => item.field.name === name);
  if (!entry) throw new RangeError(`no field ${name}`);
  return { entry, own };
}

// set({name: value}) writes values as the form would start with them (a datetime from epoch
// seconds; null empties the field); suggest(name, values) replaces a field's suggestions.
export function formControls(form) {
  const get = (name) => readText(partOf(form, name).entry);
  const set = (values) => {
    for (const [name, value] of Object.entries(values)) {
      const { entry, own } = partOf(form, name);
      writeText(entry, initialText({ ...entry.field, value }, own.zone, own.lang));
      setFieldError(entry, "");
    }
  };
  const suggest = (name, values) => {
    const { entry } = partOf(form, name);
    if (!entry.list) throw new RangeError(`field ${name} has no suggestions`);
    entry.list.replaceChildren(...suggestionOptions(values));
  };
  const focus = (name) => partOf(form, name).entry.input.focus();
  return { get, set, suggest, focus };
}

// parts: [{name, element, values(): object | null, placeErrors(problems): problems, draft?(), restore?(data)}] (a rowGroup is one).
// Their elements follow the fields; their values merge into the submitted object (null blocks the
// send); on a 422 each part places its own problems first, the form's fields get the rest.
export function simpleForm({ fields, submitLabel, onSubmit, draftKey, timeZone, ctx: own, parts = [] }) {
  const getCtx = () => contextOf(own);
  const me = getCtx().me;
  const zone = timeZone || (me && me.timezone) || "UTC";
  const draft = draftKey ? takeDraft(draftKey) : null;
  const packed = isPackedDraft(draft);
  const entries = formEntries(fields, packed ? draft.fields : draft, zone, getCtx().lang);
  for (const part of parts) if (packed && part.restore && draft.parts[part.name]) part.restore(draft.parts[part.name]);
  const secrets = entries.filter((entry) => entry.field.type === "password");
  const attempt = async () => {
    const ctx = getCtx();
    for (const entry of entries) setFieldError(entry, "");
    showStatus(status, [], "info");
    const own = convert(entries, zone, ctx.t);
    const given = parts.map((part) => part.values());
    if (!own || given.some((value) => value === null)) return;
    const values = Object.assign({}, own, ...given);
    const raw = rawValues(entries);
    const rowsNow = partDrafts(parts);
    const secretNames = secrets.map((entry) => entry.field.name);
    try {
      await onSubmit(values);
      showStatus(status, [ctx.t("form.done")], "ok");
    } catch (error) {
      handleFailure(error, ctx, {
        status,
        keepDraft: () => draftKey && saveDraft(draftKey, packDraft(parts, stripSecrets(raw, secretNames), rowsNow)),
        showValidation: (fieldErrors, ctx) => placeFieldErrors(entries, parts.reduce((left, part) => part.placeErrors(left), fieldErrors), ctx),
      });
    }
  };
  // Password fields are emptied after every attempt, whether it was sent, refused or never left.
  const run = async () => {
    try {
      await attempt();
    } finally {
      for (const entry of secrets) entry.input.value = "";
    }
  };
  const { form, status } = formFrame(submitLabel, [...entries.map((entry) => entry.row), ...parts.map((part) => part.element)], run, getCtx);
  formParts.set(form, { entries, zone, lang: getCtx().lang });
  if (draftKey) keepOnSessionLoss(form, draftKey, entries, Boolean(draft), parts);
  if (draft) showStatus(status, [getCtx().t("form.draftRestored")], "info");
  return form;
}

export function jsonEditor({ label, value, submitLabel, onSubmit, draftKey, ctx: own }) {
  const getCtx = () => contextOf(own);
  const draft = draftKey ? takeDraft(draftKey) : null;
  const original = typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
  const initial = draft ? String(draft.text) : original;
  const entry = fieldRow({ name: "json", label, type: "textarea" }, initial, "");
  entry.input.setAttribute("spellcheck", "false");
  entry.input.setAttribute("rows", String(Math.min(30, Math.max(8, initial.split("\n").length + 1))));
  entry.input.classList.add("input-code");
  const run = async () => {
    const ctx = getCtx();
    setFieldError(entry, "");
    showStatus(status, [], "info");
    const text = entry.input.value;
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      setFieldError(entry, ctx.t("form.badJson", { error: error.message }));
      return;
    }
    try {
      await onSubmit(parsed);
      showStatus(status, [ctx.t("form.done")], "ok");
    } catch (error) {
      handleFailure(error, ctx, {
        status,
        keepDraft: () => draftKey && saveDraft(draftKey, { text }),
        showValidation: (fieldErrors, ctx) => placeFieldErrors([], fieldErrors, ctx),
      });
    }
  };
  const { form, status } = formFrame(submitLabel, [entry.row], run, getCtx);
  if (draftKey) {
    registerDraftSaver(form, () => entry.input.value !== original && saveDraft(draftKey, { text: entry.input.value }));
  }
  if (draft) showStatus(status, [getCtx().t("form.draftRestored")], "info");
  return form;
}
