// Evidence cards: every card with its source and verification, a form to enter one, and verification of a model's card.
import { labelOr } from "../i18n.js";
import { h } from "../ui/dom.js";
import { confirmOrCancel, simpleForm } from "../ui/forms.js";
import { roleLabel } from "../ui/names.js";
import { afterWrite, keyValues, note, pageHead, section, techDetails, timeText } from "../ui/section.js";

const SOURCE_CLASSES = ["handbook", "paper", "local"];
const CLAIM_CHARS = 40;

// A card as a notice names it: its claim, cut to CLAIM_CHARS characters with "…".
export function claimName(claim) {
  const chars = [...String(claim ?? "").trim().replace(/\s+/g, " ")];
  return chars.length > CLAIM_CHARS ? `${chars.slice(0, CLAIM_CHARS).join("")}…` : chars.join("");
}

const yesNo = (ctx) => [
  { value: "yes", label: ctx.t("common.yes") },
  { value: "no", label: ctx.t("common.no") },
];

// Whether a card was calibrated is recorded as the operator's own choice: no answer is preset.
export function enterFields(ctx) {
  const classes = SOURCE_CLASSES.map((value) => ({ value, label: labelOr(ctx.t, "evidence.class", value) }));
  const calibration = [{ value: "", label: ctx.t("form.choose") }, ...yesNo(ctx)];
  return [
    { name: "source_class", label: ctx.t("evidence.sourceClass"), type: "select", required: true, options: classes },
    { name: "citation", label: ctx.t("evidence.citation"), type: "textarea", required: true },
    { name: "claim", label: ctx.t("evidence.claim"), type: "textarea", required: true },
    { name: "value", label: ctx.t("evidence.value"), type: "number" },
    { name: "unit", label: ctx.t("evidence.unit"), type: "text" },
    { name: "calibrated", label: ctx.t("evidence.calibrated"), type: "select", required: true, options: calibration },
  ];
}

function enterForm(ctx) {
  const submitLabel = ctx.t("evidence.enter");
  const onSubmit = async ({ calibrated, ...rest }) => {
    await confirmOrCancel(ctx, { title: ctx.t("evidence.enterTitle"), lines: [ctx.t("evidence.enterLine")], confirmLabel: submitLabel });
    const card = await ctx.api.post("/evidence", { ...rest, calibrated: calibrated === "yes" }, { action: submitLabel });
    afterWrite(ctx, ctx.t("evidence.entered", { claim: claimName(card?.claim ?? rest.claim) }));
  };
  return simpleForm({ fields: enterFields(ctx), submitLabel, onSubmit, draftKey: "evidence:new", ctx });
}

function verifyForm(ctx, card) {
  const submitLabel = ctx.t("evidence.verify");
  const fields = [
    { name: "note", label: ctx.t("evidence.note"), type: "text" },
    { name: "calibrated", label: ctx.t("evidence.attest"), type: "checkbox" },
  ];
  const onSubmit = async ({ note: text, calibrated }) => {
    await confirmOrCancel(ctx, { title: ctx.t("evidence.verifyTitle"), lines: [ctx.t("evidence.verifyLine")], confirmLabel: submitLabel });
    const body = { note: text || "", calibrated: calibrated === true };
    await ctx.api.post(`/evidence/${encodeURIComponent(card.id)}/verify`, body, { action: submitLabel });
    afterWrite(ctx, ctx.t("evidence.verified", { claim: claimName(card.claim) }));
  };
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: `evidence-verify:${card.id}`, ctx });
}

// Who entered a card: "you" for the signed-in operator, the agent's role for the model's own cards
// (agents/handlers_evidence.py SOURCE), any other operator name as it was recorded.
const AGENT_SOURCES = { "model:planner": "planner" };

function enteredBy(ctx, source) {
  if (!source) return "—";
  if (ctx.me && source === ctx.me.operator) return roleLabel(ctx.t, "user");
  return Object.hasOwn(AGENT_SOURCES, source) ? roleLabel(ctx.t, AGENT_SOURCES[source]) : source;
}

// The value as it was entered: no fixed number of decimals (a datum is never rounded on screen).
const exactNumber = (value, lang) => Number(value).toLocaleString(lang, { maximumFractionDigits: 20 });

function facts(ctx, card) {
  const hasValue = card.value !== null && card.value !== undefined;
  return keyValues([
    [ctx.t("evidence.fact.class"), labelOr(ctx.t, "evidence.class", card.source_class)],
    [ctx.t("evidence.fact.value"), hasValue ? `${exactNumber(card.value, ctx.lang)} ${card.unit || ""}`.trim() : null],
    [ctx.t("evidence.fact.calibration"), ctx.t(card.calibrated ? "evidence.calibratedYes" : "evidence.uncalibrated")],
    [ctx.t("evidence.fact.by"), enteredBy(ctx, card.source)],
    [ctx.t("evidence.fact.at"), timeText(ctx, card.added_at)],
  ]);
}

function verificationBlock(ctx, card) {
  if (!card.verified_by) {
    const summary = h("summary", { text: ctx.t("evidence.verify") });
    return h("details", { class: "row-form" }, summary, verifyForm(ctx, card));
  }
  const line = ctx.t("evidence.verifiedBy", { name: card.verified_by, time: timeText(ctx, card.verified_at) });
  return h("p", { class: "cell-sub", text: card.note ? `${line} — ${card.note}` : line });
}

function cardView(ctx, card) {
  const verified = Boolean(card.verified_by);
  const pill = h("span", {
    class: ["pill", verified ? "pill-active" : "pill-waiting"],
    text: ctx.t(verified ? "evidence.status.verified" : "evidence.status.unverified"),
  });
  return h(
    "li",
    { class: "evidence-card" },
    h("div", { class: "evidence-head" }, h("h3", { class: "evidence-claim", text: card.claim }), pill),
    h("p", { class: "cell-sub", text: ctx.t("evidence.citedFrom", { citation: card.citation }) }),
    facts(ctx, card),
    verificationBlock(ctx, card),
    techDetails(ctx.t, [[ctx.t("tech.id.id"), card.id], [ctx.t("evidence.fact.rawValue"), card.value]]),
  );
}

function cardList(ctx, cards) {
  return h("ul", { class: "evidence-list", attrs: { "aria-label": ctx.t("evidence.list") } }, cards.map((card) => cardView(ctx, card)));
}

export async function render(ctx) {
  const data = await ctx.api.get("/evidence");
  const cards = Array.isArray(data && data.cards) ? data.cards : [];
  const element = h(
    "div",
    { class: "page evidence" },
    pageHead(ctx.t("nav.evidence"), ctx.t("evidence.lead")),
    section(ctx.t("evidence.list"), cards.length ? cardList(ctx, cards) : note(ctx.t("evidence.empty"))),
    section(ctx.t("evidence.new"), enterForm(ctx)),
  );
  return { element };
}
