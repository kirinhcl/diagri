// The run sheet as a form for its common settings: the lengths, the sampling, each channel's levels, the timed actions,
// the manual tasks and the end actions. It never rebuilds the sheet: the body starts from a deep copy of the stored
// sheet and only the values the operator changed are written back, so whatever the form does not show (rules, ids,
// ownership, evidence, the number formats and key order of untouched values) goes back exactly as it was read.
import { labelOr } from "../i18n.js";
import { saveDraft, takeDraft } from "../drafts.js";
import { h } from "../ui/dom.js";
import { fieldsPart, rowGroup } from "../ui/field-forms.js";
import { convert, fieldRow, initialText, placeFieldErrors, simpleForm } from "../ui/forms.js";

const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const MINUTES_PER_DAY = 1440;
const MAX_IRRIGATION_SECONDS = 60; // the server's MAX_PLANNED_IRRIGATION_SECONDS
const TIME_OF_DAY = /^([01]\d|2[0-3]):[0-5]\d$/;
const TASK_KINDS = ["irrigation", "measurement", "photo"];
const EXPIRIES = ["stay_paused", "stop"];
const DELETE = Symbol("delete the key");
const REST_DIGITS = 6;

const clone = (value) => structuredClone(value);
const array = (value) => (Array.isArray(value) ? value : []);
const unique = (values) => [...new Set(values.filter((value) => typeof value === "string" && value !== ""))];
const zoneOf = (ctx) => (ctx.me && ctx.me.timezone) || "UTC";

// --- writing back only what changed --------------------------------------------------------------------

// `cleared` is what an emptied optional value becomes: a stored null, or the key left out (DELETE).
function write(target, name, value, cleared = null) {
  if (value === undefined) {
    if (!Object.hasOwn(target, name) || target[name] === cleared) return;
    if (cleared === DELETE) delete target[name];
    else target[name] = cleared;
  } else if (!Object.is(target[name], value)) {
    target[name] = value;
  }
}

// The rows as the form now has them: a row that came from the stored sheet starts from its stored copy.
function mergeRows(stored, rows, { names, fresh, cleared = {} }) {
  return rows.map((row) => {
    const base = stored[Number(row.origin)];
    if (row.origin === undefined || base === undefined) return fresh(row);
    const next = clone(base);
    for (const name of names) write(next, name, row[name], cleared[name]);
    return next;
  });
}

const ROW_KINDS = {
  timed_actions: {
    names: ["id", "channel", "at", "level"],
    fresh: (row) => ({ id: row.id, channel: row.channel, at: row.at, level: row.level, evidence: null }),
  },
  manual_tasks: {
    names: ["id", "kind", "at", "make_up_allowed", "seconds"],
    cleared: { seconds: DELETE },
    fresh: (row) => ({ id: row.id, kind: row.kind, at: row.at, make_up_allowed: row.make_up_allowed, ...(row.seconds === undefined ? {} : { seconds: row.seconds }) }),
  },
  end_actions: { names: ["channel", "level"], fresh: (row) => ({ channel: row.channel, level: row.level }) },
};

// Exactly the stored run sheet, with the changes the form reports written onto a copy.
export function buildRunSheet(stored, values) {
  const next = clone(stored);
  for (const name of ["duration_seconds", "max_wait_seconds"]) if (values[name] !== undefined) next[name] = values[name];
  write(next, "on_expiry", values.on_expiry);
  next.sampling = next.sampling || {};
  write(next.sampling, "interval_seconds", values.interval_seconds);
  write(next.sampling, "max_gap_seconds", values.max_gap_seconds);
  array(values.channels).forEach((changes, index) => Object.assign(next.channels[index], changes));
  for (const [name, kind] of Object.entries(ROW_KINDS)) {
    const rows = values[name];
    if (rows && (Object.hasOwn(next, name) || rows.length > 0)) next[name] = mergeRows(array(stored[name]), rows, kind);
  }
  return next;
}

// --- parsing -------------------------------------------------------------------------------------------

const wholeNumber = (text, t) => {
  const number = Number(text);
  return Number.isInteger(number) && number >= 0 ? { value: number } : { error: t("runsheet.form.whole") };
};
const plainNumber = (text, t) => {
  const number = Number(text);
  return Number.isFinite(number) && number >= 0 ? { value: number } : { error: t("runsheet.form.number") };
};
const timeOfDay = (text, t) => (TIME_OF_DAY.test(text.trim()) ? { value: text.trim() } : { error: t("runsheet.form.badTime") });
const trimmed = (text, t) => (text.trim() ? { value: text.trim() } : { error: t("form.required") });
const pumpSeconds = (text, t) => {
  const number = Number(text);
  return Number.isFinite(number) && number > 0 && number <= MAX_IRRIGATION_SECONDS ? { value: number } : { error: t("runsheet.form.pumpRange", { max: MAX_IRRIGATION_SECONDS }) };
};
// A level is a whole number inside the channel's range, when the device told the range; else the server judges.
const levelParse = (range) => (text, t) => {
  const number = Number(text);
  if (!Number.isInteger(number)) return { error: t("runsheet.form.levelWhole") };
  if (range && number < range[0]) return { error: t("form.tooSmall", { min: range[0] }) };
  if (range && number > range[1]) return { error: t("form.tooBig", { max: range[1] }) };
  return { value: number };
};

// --- lengths: days, hours and minutes, and the seconds that do not fill a minute -------------------------

function splitSeconds(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return { days: 0, hours: 0, minutes: 0, rest: 0 };
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  const rest = Number((seconds - minutes * SECONDS_PER_MINUTE).toFixed(REST_DIGITS));
  return { days: Math.floor(minutes / MINUTES_PER_DAY), hours: Math.floor((minutes % MINUTES_PER_DAY) / MINUTES_PER_HOUR), minutes: minutes % MINUTES_PER_HOUR, rest };
}

const bind = (entries) => Object.fromEntries(entries.map((entry) => [entry.field.name, entry.input.value]));

// A part for one stored length. It reports the new seconds only when a box was changed, so an unchanged
// length is never recomputed (a stored 604800.0 or 90.5 goes back as it was).
function lengthPart({ ctx, key, prefix, label, hint, stored }) {
  const parts = splitSeconds(stored);
  const labels = { days: ctx.t("runsheet.form.days"), hours: ctx.t("runsheet.form.hours"), minutes: ctx.t("runsheet.form.minutes"), rest: ctx.t("runsheet.form.rest") };
  const spec = (name) => ({ name: `${prefix}_${name}`, label: labels[name], type: "number", step: name === "rest" ? "any" : 1, min: 0, required: true, parse: name === "rest" ? plainNumber : wholeNumber, value: parts[name] });
  const fields = ["days", "hours", "minutes", ...(parts.rest ? ["rest"] : [])].map(spec);
  const zone = zoneOf(ctx);
  const entries = fields.map((field) => fieldRow(field, initialText(field, zone, ctx.lang), zone));
  const element = h("fieldset", { class: "field-group" }, h("legend", { text: label }), h("p", { class: "note", text: hint }), entries.map((entry) => entry.row));
  const start = bind(entries);
  const part = (name) => entries.find((entry) => entry.field.name === `${prefix}_${name}`);
  const values = () => {
    const found = convert(entries, zone, ctx.t);
    if (!found) return null;
    if (entries.every((entry) => entry.input.value === start[entry.field.name])) return {};
    const number = (name) => (part(name) ? found[`${prefix}_${name}`] : 0);
    const minutes = number("days") * MINUTES_PER_DAY + number("hours") * MINUTES_PER_HOUR + number("minutes");
    return { [key]: minutes * SECONDS_PER_MINUTE + number("rest") };
  };
  const placeErrors = (problems) => {
    const mine = problems.filter((problem) => problem.loc[problem.loc.indexOf("run_sheet") + 1] === key);
    const target = part("minutes");
    placeFieldErrors([target], mine.map((problem) => ({ ...problem, loc: [target.field.name] })), ctx);
    return problems.filter((problem) => !mine.includes(problem));
  };
  const restore = (saved) => entries.forEach((entry) => Object.hasOwn(saved, entry.field.name) && (entry.input.value = saved[entry.field.name]));
  return { name: key, element, values, placeErrors, draft: () => bind(entries), restore };
}

// --- channels: one row per stored channel, the plan's own values only -----------------------------------

function channelFields(ctx, plan, range) {
  const { t } = ctx;
  // The server has no range check on a channel plan, so the range is checked only for a value the operator changed.
  const stored = String(plan.retained_level);
  const parse = (text, translate) => levelParse(text === stored ? null : range)(text, translate);
  const level = { name: "retained_level", label: t("runsheet.form.retained"), hint: t("runsheet.form.retainedHint"), type: "number", step: 1, parse, value: plan.retained_level };
  const tolerance = { name: "max_tolerance_seconds", label: t("runsheet.form.tolerance"), unit: t("runsheet.form.seconds"), type: "number", min: 0, parse: plainNumber, value: plan.max_tolerance_seconds };
  return [level, tolerance];
}

const PLAN_VALUES = ["retained_level", "max_tolerance_seconds"];

// What changed in a channel's plan; an emptied value that was stored becomes null.
function changesOf(plan, value) {
  const changes = {};
  for (const name of PLAN_VALUES) {
    if (value[name] === undefined) {
      if (plan[name] !== null && plan[name] !== undefined) changes[name] = null;
    } else if (!Object.is(plan[name], value[name])) {
      changes[name] = value[name];
    }
  }
  return changes;
}

// Both values may be empty (stored null). Only changed ones are reported, per channel in stored order.
function channelsPart({ ctx, stored, capabilities }) {
  const zone = zoneOf(ctx);
  const rows = array(stored).map((plan) => {
    const entries = channelFields(ctx, plan, capabilities?.level_ranges?.[plan.channel]).map((field) => fieldRow(field, initialText(field, zone, ctx.lang), zone));
    const heading = h("p", { class: "row-group-title", text: labelOr(ctx.t, "channel", plan.channel) });
    return { plan, entries, element: h("div", { class: "row-group-row" }, heading, entries.map((entry) => entry.row)) };
  });
  const element = h("fieldset", { class: "row-group" }, h("legend", { text: ctx.t("runsheet.form.channels") }), rows.map((row) => row.element));
  const values = () => {
    const found = rows.map((row) => convert(row.entries, zone, ctx.t));
    if (!found.every(Boolean)) return null;
    return { channels: found.map((value, index) => changesOf(rows[index].plan, value)) };
  };
  const placeErrors = (problems) => problems.filter((problem) => {
    const at = problem.loc.indexOf("channels");
    const row = at < 0 ? undefined : rows[problem.loc[at + 1]];
    return !(row && placeFieldErrors(row.entries, [{ ...problem, loc: problem.loc.slice(at + 2) }], ctx).length === 0);
  });
  const draft = () => rows.map((row) => ({ channel: row.plan.channel, ...bind(row.entries) }));
  const restore = (saved) => rows.forEach((row) => {
    const mine = array(saved).find((item) => item.channel === row.plan.channel);
    if (mine) row.entries.forEach((entry) => Object.hasOwn(mine, entry.field.name) && (entry.input.value = mine[entry.field.name]));
  });
  return { name: "channels", element, values, placeErrors, draft, restore };
}

// --- rows: timed actions, manual tasks, end actions ----------------------------------------------------

// A hidden field carries each row's place in the stored list, so a row that is edited keeps its stored copy
// (and its keys the form does not show) even after rows before it were removed.
const originField = { name: "origin", type: "hidden" };

// The row's level range follows the channel chosen on the row.
function linkLevel(capabilities) {
  return (entries) => {
    const named = (name) => entries.find((entry) => entry.field.name === name);
    const channel = named("channel");
    const level = named("level");
    const sync = () => {
      const range = capabilities?.level_ranges?.[channel.input.value];
      level.field = { ...level.field, parse: levelParse(range) };
      for (const [attr, at] of [["min", 0], ["max", 1]]) {
        if (range) level.input.setAttribute(attr, String(range[at]));
        else level.input.removeAttribute(attr);
      }
    };
    channel.input.addEventListener("change", sync);
    sync();
  };
}

function channelChoice(ctx, channels) {
  const options = channels.map((value) => ({ value, label: labelOr(ctx.t, "channel", value) }));
  return { name: "channel", label: ctx.t("runsheet.form.channel"), type: "select", required: true, options: [{ value: "", label: ctx.t("form.choose") }, ...options] };
}
const levelField = (ctx) => ({ name: "level", label: ctx.t("runsheet.form.level"), type: "number", step: 1, required: true, parse: levelParse(null) });
const timeField = (ctx, zone, label) => ({ name: "at", label, hint: ctx.t("runsheet.form.timeHint", { zone }), required: true, parse: timeOfDay });

// What a task's pump run may be, judged by the kind chosen on the same row.
function seconds(ctx) {
  return (rows) => rows.flatMap((row, index) => (row.kind !== "irrigation" && row.seconds !== undefined ? [{ row: index, field: "seconds", error: ctx.t("runsheet.form.pumpOnlyWatering") }] : []));
}

function rowsPart({ ctx, name, label, fields, stored, addLabel, removeLabel, capabilities, ranged = false, check, mainField = "level" }) {
  const rows = array(stored).map((row, index) => ({ ...row, origin: index }));
  const group = rowGroup({ ctx, name, label, fields: [originField, ...fields], rows, addLabel, removeLabel, onRow: ranged ? linkLevel(capabilities) : undefined, crossCheck: check });
  // A row's own model check names the row but no field (loc ends at the row's number): it lands on the row's main field.
  const place = group.placeErrors;
  const wholeRow = (problem) => {
    const at = problem.loc.indexOf(name);
    return at >= 0 && problem.loc.length === at + 2 && Number.isInteger(problem.loc[at + 1]);
  };
  group.placeErrors = (problems) => place(problems.map((problem) => (wholeRow(problem) ? { ...problem, loc: [...problem.loc, mainField] } : problem)));
  return group;
}

function rowParts(env) {
  const { ctx, sheet, capabilities } = env;
  const { t } = ctx;
  const channels = unique([...array(sheet.channels).map((plan) => plan.channel), ...["timed_actions", "end_actions"].flatMap((key) => array(sheet[key]).map((row) => row.channel))]);
  const common = { ctx, capabilities, addLabel: t("forms.addRow"), removeLabel: t("forms.removeRow") };
  const kinds = TASK_KINDS.map((value) => ({ value, label: labelOr(t, "tasks.kind", value) }));
  return [
    rowsPart({ ...common, name: "timed_actions", ranged: true, label: t("runsheet.form.timed"), stored: sheet.timed_actions, fields: [{ name: "id", label: t("runsheet.form.name"), required: true, parse: trimmed }, channelChoice(ctx, channels), timeField(ctx, sheet.timezone, t("runsheet.form.at")), levelField(ctx)] }),
    rowsPart({
      ...common, name: "manual_tasks", mainField: "seconds", label: t("runsheet.form.tasks"), stored: sheet.manual_tasks, check: seconds(ctx),
      fields: [
        { name: "id", label: t("runsheet.form.name"), required: true, parse: trimmed },
        { name: "kind", label: t("runsheet.form.kind"), type: "select", required: true, options: [{ value: "", label: t("form.choose") }, ...kinds] },
        timeField(ctx, sheet.timezone, t("runsheet.form.at")),
        { name: "make_up_allowed", label: t("runsheet.form.makeUp"), type: "checkbox" },
        { name: "seconds", label: t("runsheet.form.pump"), hint: t("runsheet.form.pumpHint", { max: MAX_IRRIGATION_SECONDS }), type: "number", min: 0, max: MAX_IRRIGATION_SECONDS, unit: t("runsheet.form.seconds"), parse: pumpSeconds },
      ],
    }),
    rowsPart({ ...common, name: "end_actions", ranged: true, label: t("runsheet.form.end"), stored: sheet.end_actions, fields: [channelChoice(ctx, channels), levelField(ctx)] }),
  ];
}

// --- the form ------------------------------------------------------------------------------------------

function settingsPart(ctx, sheet) {
  const { t } = ctx;
  const sampling = sheet.sampling || {};
  const number = (name, label, value) => ({ name, label, type: "number", required: true, min: 0, unit: t("runsheet.form.seconds"), parse: plainNumber, value });
  const options = [{ value: "", label: t("form.choose") }, ...EXPIRIES.map((value) => ({ value, label: labelOr(t, "runsheet.form.expiry", value) }))];
  const fields = [
    { name: "on_expiry", label: t("runsheet.form.expiry"), hint: t("runsheet.form.expiryHint"), type: "select", required: true, options, value: sheet.on_expiry },
    number("interval_seconds", t("runsheet.form.interval"), sampling.interval_seconds),
    number("max_gap_seconds", t("runsheet.form.gap"), sampling.max_gap_seconds),
  ];
  return fieldsPart({ ctx, name: "settings", label: t("runsheet.form.settings"), fields });
}

// What the draft was made from: the review's digest, else the round and the sheet's version.
const baseOf = (review, roundId) => review.run_sheet_digest || `${roundId}:${review.run_sheet.version}`;

// A part that holds only the draft's base, so the draft says which sheet it was typed on.
function basePart(base) {
  return { name: "base", element: h("span", { attrs: { hidden: true } }), values: () => ({}), placeErrors: (problems) => problems, draft: () => base, restore: () => {} };
}

// The server refuses a changed body that keeps the stored version, so a change goes as the next version;
// an unchanged sheet goes back exactly as stored, which keeps its approval.
function versioned(stored, built) {
  if (JSON.stringify(built) === JSON.stringify(stored)) return built;
  return { ...built, version: stored.version + 1 };
}

function versionNotePart(ctx, version) {
  const element = h("p", { class: "note run-sheet-version-note", text: ctx.t("runsheet.form.versionNote", { version: Number(version) + 1 }) });
  return { name: "versionNote", element, values: () => ({}), placeErrors: (problems) => problems, draft: () => null, restore: () => {} };
}

// A kept draft made on another run sheet is dropped, never put onto this one (its rows and channels would not line up).
function dropStaleDraft(key, base) {
  const saved = key ? takeDraft(key) : null;
  if (!saved) return false;
  const stale = !saved.parts || saved.parts.base !== base;
  if (!stale) saveDraft(key, saved);
  return stale;
}

// review: the run-sheet read (its run_sheet is the stored sheet); capabilities: the device's level ranges or null.
// onSubmit({round_id, run_sheet}) sends it. Returns the form.
export function runSheetForm(ctx, { review, roundId, capabilities, onSubmit, draftKey, submitLabel }) {
  const sheet = review.run_sheet;
  const { t } = ctx;
  const base = baseOf(review, roundId);
  const stale = dropStaleDraft(draftKey, base);
  const parts = [
    basePart(base),
    lengthPart({ ctx, key: "duration_seconds", prefix: "duration", label: t("runsheet.form.duration"), hint: t("runsheet.form.durationHint"), stored: sheet.duration_seconds }),
    lengthPart({ ctx, key: "max_wait_seconds", prefix: "max_wait", label: t("runsheet.form.wait"), hint: t("runsheet.form.waitHint"), stored: sheet.max_wait_seconds }),
    settingsPart(ctx, sheet),
    channelsPart({ ctx, stored: sheet.channels, capabilities }),
    ...rowParts({ ctx, sheet, capabilities }),
    versionNotePart(ctx, sheet.version),
  ];
  const send = (values) => onSubmit({ round_id: roundId, run_sheet: versioned(sheet, buildRunSheet(sheet, values)) });
  const form = simpleForm({ fields: [], parts, ctx, onSubmit: send, draftKey, submitLabel: submitLabel || t("stage.draft.submit") });
  if (stale) form.prepend(h("p", { class: "note", attrs: { role: "status" }, text: t("runsheet.form.draftStale") }));
  return form;
}
