// Building blocks for forms beyond simpleForm's one-value fields: a list typed one item per line,
// rows the person can add and remove, and the closed "Advanced (JSON)" fold.
import { hasDraft } from "../drafts.js";
import { h } from "./dom.js";
import { convert, fieldRow, initialText, jsonEditor, placeFieldErrors, setFieldError } from "./forms.js";

// A field spec for simpleForm's `fields` (it is a plain field, not a part): a text area whose lines become a string[] (blank lines dropped, ends trimmed).
export function linesField({ name, label, hint, value, maxItems, maxItemLength, required }) {
  const parse = (text, t) => {
    const items = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (items.length === 0) return required ? { error: t("form.required") } : { value: [] };
    if (maxItems !== undefined && items.length > maxItems) return { error: t("form.tooManyLines", { max: maxItems }) };
    if (maxItemLength !== undefined && items.some((item) => item.length > maxItemLength)) {
      return { error: t("form.lineTooLong", { max: maxItemLength }) };
    }
    return { value: items };
  };
  return { name, label, hint, value, required, type: "textarea", parse };
}

// Rows of the same fields, usable as one of simpleForm's `parts`: values() gives {[name]: one object
// per row}, or null (errors shown beside the fields) when a row is not valid; rows() gives the
// bare array. onRow(entries) runs for each new row (to link its fields to each other); crossCheck(rows) may refuse rows by what the other rows hold. placeErrors(problems, ctx) puts the 422 problems under
// <name>.<row index>.<field> beside that row's field and returns the problems it did not place.
// onChange() runs after rows are added, removed or restored (also while the group is being built).
export function rowGroup({ ctx, name, label, fields, rows = [], addLabel, removeLabel, minRows = 0, maxRows = Infinity, onRow, crossCheck, onChange }) {
  const zone = (ctx.me && ctx.me.timezone) || "UTC";
  const holder = h("div", { class: "row-group-rows" });
  const addButton = h("button", { class: "button", attrs: { type: "button" }, text: addLabel, on: { click: () => addRow({}) } });
  const element = h("fieldset", { class: "row-group" }, h("legend", { text: label }), holder, addButton);
  let items = [];
  const sync = () => {
    addButton.toggleAttribute("disabled", items.length >= maxRows);
    for (const item of items) item.remove.toggleAttribute("disabled", items.length <= minRows);
  };
  function addRow(row, texts = {}) {
    const start = (field) => (Object.hasOwn(texts, field.name) ? texts[field.name] : initialText({ ...field, value: row[field.name] }, zone, ctx.lang));
    const entries = fields.map((field) => fieldRow(field, start(field), zone));
    if (onRow) onRow(entries);
    const remove = h("button", { class: "button", attrs: { type: "button" }, text: removeLabel });
    const el = h("div", { class: "row-group-row" }, entries.map((entry) => entry.row), remove);
    const item = { entries, el, remove };
    remove.addEventListener("click", () => {
      items = items.filter((other) => other !== item);
      el.remove();
      sync();
      if (onChange) onChange();
    });
    items = [...items, item];
    holder.append(el);
    sync();
    if (onChange) onChange();
  }
  const setRows = (next) => {
    for (const item of items) item.el.remove();
    items = [];
    for (const row of next) addRow(row);
    while (items.length < minRows) addRow({});
  };
  const rowValues = () => {
    const all = items.map((item) => {
      for (const entry of item.entries) setFieldError(entry, "");
      return convert(item.entries, zone, ctx.t);
    });
    if (!all.every(Boolean)) return null;
    // crossCheck(rows) -> [{row, field, error}]: refusals that depend on other rows, shown beside that row's field.
    const refused = (crossCheck ? crossCheck(all) : []).filter(({ row, field, error }) => {
      const entry = items[row]?.entries.find((candidate) => candidate.field.name === field);
      if (entry) setFieldError(entry, error);
      return Boolean(entry);
    });
    return refused.length ? null : all;
  };
  const placeErrors = (problems) => problems.filter((problem) => !placeInRow(problem));
  function placeInRow(problem) {
    const at = problem.loc.indexOf(name);
    const item = at < 0 ? undefined : items[problem.loc[at + 1]];
    if (!item) return false;
    const inner = { ...problem, loc: problem.loc.slice(at + 2) };
    return placeFieldErrors(item.entries, [inner], ctx).length === 0;
  }
  setRows(rows);
  const values = () => {
    const all = rowValues();
    return all && { [name]: all };
  };
  // The draft is what is typed, as text, so a half-filled row survives a lost session.
  const rawText = (entry) => (entry.field.type === "checkbox" ? String(entry.input.checked) : entry.input.value);
  const draft = () => items.map((item) => Object.fromEntries(item.entries.map((entry) => [entry.field.name, rawText(entry)])));
  const restore = (saved) => {
    for (const item of items) item.el.remove();
    items = [];
    for (const texts of saved) addRow({}, texts);
    sync();
    if (onChange) onChange();
  };
  return { name, element, values, rows: rowValues, setRows, placeErrors, draft, restore };
}

// The existing JSON editor, tucked under a closed fold (open only when it brings back a draft).
export function advancedJson({ ctx, label, value, onSubmit, draftKey, submitLabel }) {
  const open = Boolean(draftKey) && hasDraft(draftKey);
  const editor = jsonEditor({ label, value, submitLabel: submitLabel || ctx.t("forms.advancedSubmit"), onSubmit, draftKey, ctx });
  return h("details", { class: "edit-fold", attrs: { open } }, h("summary", { text: ctx.t("forms.advanced") }), editor);
}
