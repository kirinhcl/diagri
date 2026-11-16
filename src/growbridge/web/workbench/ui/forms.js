// Forms that put each refusal where it belongs: field errors beside the field, the rest above the button.
import { ApiError, singleFlight } from "../api.js";
import { describeDenial } from "../denials.js";
import { saveDraft, stripSecrets, takeDraft } from "../drafts.js";
import { formatTime, zonedToEpoch } from "../format.js";
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
export function errorLines(error, lang, t) {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "network") return [t("error.network")];
  if (code === OWN_REFUSAL && error.message) return [t("error.title"), String(error.message)];
  const known = code ? describeDenial(code, lang) : null;
  if (known) return [known.text, known.advice];
  if (error instanceof ApiError && error.status === 404 && !code) return [t("error.notFound")];
  return [t("error.title")];
}

// [label, value] pairs for the technical details: HTTP status, code and the message as it came (a
// message that only repeats the code is left out). The labels use t, else the bound page's.
export function errorDetail(error, t = bound.t) {
  if (!error) return [];
  const isApi = error instanceof ApiError;
  const message = typeof error === "object" ? String(error.message || "") : String(error); // a thrown string too
  const fromServer = isApi && error.status > 0;
  const entries = [
    [t("tech.httpStatus"), isApi ? error.status : null],
    [t("tech.code"), isApi ? error.code : null],
    [t(fromServer ? "tech.serverMessage" : "tech.message"), isApi && message === error.code ? null : message],
  ];
  return entries.filter(([, value]) => value !== null && value !== undefined && value !== "");
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
      const { lang, t } = getCtx();
      showRefusal(status, error, t, errorLines(error, lang, t));
    });
  });
  return { form, status };
}

// Every refusal is written to the form's own status line; some also keep a draft or reload the page.
function handleFailure(error, ctx, { status, keepDraft, showValidation }) {
  const lines = errorLines(error, ctx.lang, ctx.t);
  const code = error instanceof ApiError ? error.code : null;
  if (code === "validation") {
    showRefusal(status, error, ctx.t, [...lines, ...showValidation(error.fields)]);
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

function initialText(field, timeZone, lang) {
  if (field.type === "password" || field.value === undefined || field.value === null) return "";
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
  if (field.type === "textarea") return h("textarea", { class: "input input-area", attrs, text: value });
  if (field.type === "select") return h("select", { class: "input", attrs }, optionList(field, value));
  const types = { number: "number", datetime: "datetime-local", password: "password", hidden: "hidden" };
  const type = types[field.type] || "text";
  const extra = { type, value: type === "password" ? null : value };
  if (type === "number") extra.step = field.step ?? "any";
  if (type === "password") extra.autocomplete = "current-password";
  return h("input", { class: "input", attrs: { ...attrs, ...extra } });
}

// The options a text field suggests; the values are attributes only, never page text.
function suggestionOptions(values) {
  return (values || []).map((value) => h("option", { attrs: { value: String(value) } }));
}

function fieldRow(field, value, timeZone) {
  const id = nextId("field");
  const errorId = `${id}-error`;
  const zoneId = `${id}-zone`;
  const isTime = field.type === "datetime";
  const describedBy = isTime ? `${zoneId} ${errorId}` : errorId;
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
    h("div", { class: "field-control" }, input, zone, list),
    error,
  );
  return { field, input, row, error, list };
}

function setFieldError(entry, message) {
  entry.error.textContent = message || "";
  entry.error.hidden = !message;
  if (message) entry.input.setAttribute("aria-invalid", "true");
  else entry.input.removeAttribute("aria-invalid");
}

function convertOne(field, text, timeZone, t) {
  if (field.type === "number") {
    const number = Number(text);
    return Number.isFinite(number) ? { value: number } : { error: t("form.badNumber") };
  }
  if (field.type === "datetime") {
    try {
      return { value: zonedToEpoch(minutePrecision(text), timeZone).epoch };
    } catch {
      return { error: t("form.badTime", { zone: timeZone }) };
    }
  }
  return { value: text };
}

// Empty optional fields are left out of the request so the server applies its defaults.
function convert(entries, timeZone, t) {
  const values = {};
  let valid = true;
  for (const entry of entries) {
    const text = entry.input.value;
    if (text === "") {
      if (entry.field.required) setFieldError(entry, t("form.required"));
      valid = valid && !entry.field.required;
      continue;
    }
    const result = convertOne(entry.field, text, timeZone, t);
    setFieldError(entry, result.error);
    if (result.error) valid = false;
    else values[entry.field.name] = result.value;
  }
  return valid ? values : null;
}

// Puts each 422 error beside its field; returns the lines for errors that match no field. A hidden
// field's error could not be seen beside it, so it is one of those lines, under the field's label
// (never its name), or alone when the field has none.
function placeFieldErrors(entries, fieldErrors) {
  const byName = (hidden) => new Map(entries.filter((entry) => (entry.field.type === "hidden") === hidden).map((entry) => [entry.field.name, entry]));
  const shown = byName(false);
  const unseen = byName(true);
  const rest = [];
  for (const { loc, msg } of fieldErrors) {
    const name = loc.find((part) => shown.has(part));
    const hidden = unseen.get(loc.find((part) => unseen.has(part)));
    if (name) setFieldError(shown.get(name), msg);
    else if (hidden) rest.push(hidden.field.label ? `${hidden.field.label}: ${msg}` : msg);
    else rest.push(`${loc.filter((part) => part !== "body").join(" › ")}: ${msg}`);
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

const rawValues = (entries) => Object.fromEntries(entries.map((entry) => [entry.field.name, entry.input.value]));

// On a lost session the form keeps its values (never a password) when they differ from what it
// started with, or when it started from a restored draft.
export function worthKeeping(start, now) {
  if (!start) return true;
  return Object.keys(now).some((name) => now[name] !== start[name]);
}

function keepOnSessionLoss(form, draftKey, entries, restored) {
  const secretNames = entries.filter((entry) => entry.field.type === "password").map((entry) => entry.field.name);
  const start = restored ? null : stripSecrets(rawValues(entries), secretNames);
  registerDraftSaver(form, () => {
    const now = stripSecrets(rawValues(entries), secretNames);
    if (worthKeeping(start, now)) saveDraft(draftKey, now);
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
  const get = (name) => partOf(form, name).entry.input.value;
  const set = (values) => {
    for (const [name, value] of Object.entries(values)) {
      const { entry, own } = partOf(form, name);
      entry.input.value = initialText({ ...entry.field, value }, own.zone, own.lang);
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

export function simpleForm({ fields, submitLabel, onSubmit, draftKey, timeZone, ctx: own }) {
  const getCtx = () => contextOf(own);
  const me = getCtx().me;
  const zone = timeZone || (me && me.timezone) || "UTC";
  const draft = draftKey ? takeDraft(draftKey) : null;
  const entries = formEntries(fields, draft, zone, getCtx().lang);
  const secrets = entries.filter((entry) => entry.field.type === "password");
  const attempt = async () => {
    const ctx = getCtx();
    for (const entry of entries) setFieldError(entry, "");
    showStatus(status, [], "info");
    const values = convert(entries, zone, ctx.t);
    if (!values) return;
    const raw = rawValues(entries);
    const secretNames = secrets.map((entry) => entry.field.name);
    try {
      await onSubmit(values);
      showStatus(status, [ctx.t("form.done")], "ok");
    } catch (error) {
      handleFailure(error, ctx, {
        status,
        keepDraft: () => draftKey && saveDraft(draftKey, stripSecrets(raw, secretNames)),
        showValidation: (fieldErrors) => placeFieldErrors(entries, fieldErrors),
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
  const { form, status } = formFrame(submitLabel, entries.map((entry) => entry.row), run, getCtx);
  formParts.set(form, { entries, zone, lang: getCtx().lang });
  if (draftKey) keepOnSessionLoss(form, draftKey, entries, Boolean(draft));
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
        showValidation: (fieldErrors) => placeFieldErrors([], fieldErrors),
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
