// How the evidence pages say things: a card by its claim, a variable by its catalog label, a condition as a range.
const CLAIM_CHARS = 40;

// A card as a notice names it: its claim, cut to CLAIM_CHARS characters with "…".
export function claimName(claim) {
  const chars = [...String(claim ?? "").trim().replace(/\s+/g, " ")];
  return chars.length > CLAIM_CHARS ? `${chars.slice(0, CLAIM_CHARS).join("")}…` : chars.join("");
}

// The value as it was entered: no fixed number of decimals (a datum is never rounded on screen).
export const exactNumber = (value, lang) => Number(value).toLocaleString(lang, { maximumFractionDigits: 20 });

const isNumber = (value) => typeof value === "number" && Number.isFinite(value);

// A catalog variable by its label in the page's language; a name the catalog does not list as it was written.
export function variableName(ctx, variables, id) {
  const known = (variables || []).find((variable) => variable.id === id);
  if (!known) return String(id ?? "—");
  return (ctx.lang === "zh" ? known.label_zh : known.label_en) || known.label_en || known.id;
}

// One condition of a card: the variable within its bounds.
export function rangeText(ctx, variables, range) {
  const variable = variableName(ctx, variables, range.variable);
  const [min, max] = [range.min, range.max].map((bound) => (isNumber(bound) ? exactNumber(bound, ctx.lang) : null));
  if (min !== null && max !== null) return ctx.t("evidence.range", { variable, min, max });
  if (min !== null) return ctx.t("evidence.range.atLeast", { variable, min });
  if (max !== null) return ctx.t("evidence.range.atMost", { variable, max });
  return ctx.t("evidence.range.any", { variable });
}
