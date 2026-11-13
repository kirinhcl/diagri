// Forms that put each refusal where it belongs: field errors beside the field, the rest above the button.
import { ApiError, singleFlight } from "../api.js";
import { describeDenial } from "../denials.js";
import { saveDraft, stripSecrets, takeDraft } from "../drafts.js";
import { formatTime, zonedToEpoch } from "../format.js";
import { clear, h } from "./dom.js";

// A datetime-local value may carry zero seconds ("…T16:00:00"); zonedToEpoch takes minutes only.
const ZERO_SECONDS = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}):00(?:\.0+)?$/;
let bound = { t: (key) => key, lang: "en", me: null, notify: () => {}, reload: () => {} };
let counter = 0;
const nextId = (prefix) => `${prefix}-${++counter}`;

// main.js binds each page's context, so forms translate, notify and reload like the page does.
export function bindFormContext(ctx) {
  bound = ctx;
}

export function minutePrecision(text) {
  return text.replace(ZERO_SECONDS, "$1");
}

// [explanation, advice] for a denial; the server's own message for a code without a translation.
export function errorLines(error, lang, t) {
  const code = error instanceof ApiError ? error.code : null;
  const known = code ? describeDenial(code, lang) : null;
  if (known) return [known.text, known.advice];
  const message = error && error.message ? String(error.message) : "";
  return message ? [t("error.title"), message] : [t("error.title")];
}

function showStatus(status, lines, kind) {
  clear(status);
  status.className = `form-status form-status-${kind}`;
  status.hidden = lines.length === 0;
  for (const line of lines) status.append(h("p", { text: line }));
}

// The form, its status line and its submit button; run() goes through singleFlight.
function formFrame(submitLabel, children, run) {
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
    guarded().catch((error) => showStatus(status, errorLines(error, bound.lang, bound.t), "error"));
  });
  return { form, status };
}

// What every form does with a failed submit; showValidation handles 422 field lists.
function handleFailure(error, { status, keepDraft, showValidation }) {
  const lines = errorLines(error, bound.lang, bound.t);
  if (error instanceof ApiError && error.code === "session") {
    keepDraft();
    showStatus(status, lines, "error");
    return;
  }
  if (error instanceof ApiError && error.code === "validation") {
    showStatus(status, [...lines, ...showValidation(error.fields)], "error");
    return;
  }
  if (error instanceof ApiError && error.code === "state") {
    bound.notify(lines.join(" "), "error");
    bound.reload();
    return;
  }
  showStatus(status, lines, "error");
}

function initialText(field, timeZone) {
  if (field.type === "password" || field.value === undefined || field.value === null) return "";
  if (field.type === "datetime" && typeof field.value === "number") {
    return formatTime(field.value, timeZone, bound.lang).replace(" ", "T");
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
  const types = { number: "number", datetime: "datetime-local", password: "password" };
  const type = types[field.type] || "text";
  const extra = { type, value: type === "password" ? null : value };
  if (type === "number") extra.step = field.step ?? "any";
  if (type === "password") extra.autocomplete = "current-password";
  return h("input", { class: "input", attrs: { ...attrs, ...extra } });
}

function fieldRow(field, value, timeZone) {
  const id = nextId("field");
  const errorId = `${id}-error`;
  const zoneId = `${id}-zone`;
  const isTime = field.type === "datetime";
  const describedBy = isTime ? `${zoneId} ${errorId}` : errorId;
  const attrs = { id, name: field.name, required: Boolean(field.required), "aria-describedby": describedBy };
  const input = control(field, attrs, value);
  const error = h("p", { class: "field-error", attrs: { id: errorId, hidden: true } });
  const zone = isTime ? h("span", { class: "field-zone", attrs: { id: zoneId }, text: timeZone }) : null;
  const row = h(
    "div",
    { class: "field" },
    h("label", { class: "field-label", attrs: { for: id }, text: field.label }),
    h("div", { class: "field-control" }, input, zone),
    error,
  );
  return { field, input, row, error };
}

function setFieldError(entry, message) {
  entry.error.textContent = message || "";
  entry.error.hidden = !message;
  if (message) entry.input.setAttribute("aria-invalid", "true");
  else entry.input.removeAttribute("aria-invalid");
}

function convertOne(field, text, timeZone) {
  const t = bound.t;
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
function convert(entries, timeZone) {
  const values = {};
  let valid = true;
  for (const entry of entries) {
    const text = entry.input.value;
    if (text === "") {
      if (entry.field.required) setFieldError(entry, bound.t("form.required"));
      valid = valid && !entry.field.required;
      continue;
    }
    const result = convertOne(entry.field, text, timeZone);
    setFieldError(entry, result.error);
    if (result.error) valid = false;
    else values[entry.field.name] = result.value;
  }
  return valid ? values : null;
}

// Puts each 422 error beside its field; returns the lines for errors that match no field.
function placeFieldErrors(entries, fieldErrors) {
  const byName = new Map(entries.map((entry) => [entry.field.name, entry]));
  const rest = [];
  for (const { loc, msg } of fieldErrors) {
    const name = loc.find((part) => byName.has(part));
    if (name) setFieldError(byName.get(name), msg);
    else rest.push(`${loc.filter((part) => part !== "body").join(" › ")}: ${msg}`);
  }
  return rest;
}

export function simpleForm({ fields, submitLabel, onSubmit, draftKey, timeZone }) {
  const zone = timeZone || (bound.me && bound.me.timezone) || "UTC";
  const draft = draftKey ? takeDraft(draftKey) : null;
  const entries = fields.map((field) => {
    const restored = draft && field.type !== "password" && Object.hasOwn(draft, field.name);
    return fieldRow(field, restored ? String(draft[field.name]) : initialText(field, zone), zone);
  });
  const secretNames = fields.filter((field) => field.type === "password").map((field) => field.name);
  const run = async () => {
    for (const entry of entries) setFieldError(entry, "");
    showStatus(status, [], "info");
    const values = convert(entries, zone);
    if (!values) return;
    const raw = Object.fromEntries(entries.map((entry) => [entry.field.name, entry.input.value]));
    try {
      await onSubmit(values);
      showStatus(status, [bound.t("form.done")], "ok");
    } catch (error) {
      handleFailure(error, {
        status,
        keepDraft: () => draftKey && saveDraft(draftKey, stripSecrets(raw, secretNames)),
        showValidation: (fieldErrors) => placeFieldErrors(entries, fieldErrors),
      });
    } finally {
      for (const entry of entries) if (entry.field.type === "password") entry.input.value = "";
    }
  };
  const { form, status } = formFrame(submitLabel, entries.map((entry) => entry.row), run);
  if (draft) showStatus(status, [bound.t("form.draftRestored")], "info");
  return form;
}

export function jsonEditor({ label, value, submitLabel, onSubmit, draftKey }) {
  const draft = draftKey ? takeDraft(draftKey) : null;
  const initial = draft ? String(draft.text) : typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
  const entry = fieldRow({ name: "json", label, type: "textarea" }, initial, "");
  entry.input.setAttribute("spellcheck", "false");
  entry.input.setAttribute("rows", String(Math.min(30, Math.max(8, initial.split("\n").length + 1))));
  entry.input.classList.add("input-code");
  const run = async () => {
    setFieldError(entry, "");
    showStatus(status, [], "info");
    const text = entry.input.value;
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      setFieldError(entry, bound.t("form.badJson", { error: error.message }));
      return;
    }
    try {
      await onSubmit(parsed);
      showStatus(status, [bound.t("form.done")], "ok");
    } catch (error) {
      handleFailure(error, {
        status,
        keepDraft: () => draftKey && saveDraft(draftKey, { text }),
        showValidation: (fieldErrors) => placeFieldErrors([], fieldErrors),
      });
    }
  };
  const { form, status } = formFrame(submitLabel, [entry.row], run);
  if (draft) showStatus(status, [bound.t("form.draftRestored")], "info");
  return form;
}
