// One readable sentence per problem Pydantic found in a request body (HTTP 422): its `type` picks the
// text (msg.validation.<type>) and its `ctx` fills the placeholders. Pydantic's own English `msg` is
// never shown here; it goes to the technical details.
import { formatterFor } from "./messages.js";
import { textOr } from "./i18n.js";

export const VALIDATION_TYPES = Object.freeze([
  "missing", "extra_forbidden",
  "string_type", "string_too_short", "string_too_long", "string_pattern_mismatch",
  "int_type", "int_parsing", "float_type", "float_parsing", "bool_type", "bool_parsing",
  "greater_than", "greater_than_equal", "less_than", "less_than_equal", "finite_number",
  "literal_error", "enum", "list_type", "dict_type", "too_short", "too_long",
  "value_error", "json_invalid",
  "duplicate", // the server's own: a row repeats an earlier row's id (a run sheet's end action: its channel)
]);

const DASH = "—";
const BODY = "body";
const BOUND_NAMES = ["gt", "ge", "lt", "le"];

// The type decides which of gt/ge/lt/le it was, so the text only needs "{bound}".
function placeholders(limits) {
  const source = limits && typeof limits === "object" && !Array.isArray(limits) ? limits : {};
  const values = { ...source };
  for (const name of BOUND_NAMES) {
    if (Object.hasOwn(source, name)) values.bound = source[name];
  }
  return values;
}

function fill(ctx, template, values) {
  return template.replace(/\{(\w+)\}/g, (whole, name) => {
    const format = formatterFor(name);
    return format ? format(ctx, values[name], values) : DASH;
  });
}

export function problemText(ctx, { type, limits, msg } = {}) {
  void msg; // for the technical details only
  const known = VALIDATION_TYPES.includes(type) ? type : "other";
  const template = textOr(ctx.t, "msg.validation", known) ?? textOr(ctx.t, "msg.validation", "other") ?? DASH;
  return fill(ctx, template, placeholders(limits));
}

const isItem = (part) => typeof part === "number";

// "treatments › item 1 › “id”": where in the request a problem is. Item numbers count from 1; a key
// stays as typed, because that is what the JSON editor shows.
export function positionText(ctx, loc) {
  const parts = Array.isArray(loc) ? loc : [];
  const trimmed = parts[0] === BODY ? parts.slice(1) : parts;
  return trimmed
    .map((part) => (isItem(part) ? ctx.t("validation.item", { n: part + 1 }) : ctx.t("common.quoted", { text: String(part) })))
    .join(" › ");
}

// A problem away from any form input: where it is, then what is wrong.
export function locatedText(ctx, { loc, type, limits, msg }) {
  const where = positionText(ctx, loc);
  const what = problemText(ctx, { type, limits, msg });
  return where === "" ? what : `${where}${ctx.t("validation.sep")}${what}`;
}
