// Evidence cards: every card with its source and verification, a form to enter one, and verification of a model's card.
import { h } from "../ui/dom.js";
import { simpleForm } from "../ui/forms.js";
import { afterWrite, note, pageHead, section, timeText } from "../ui/section.js";

const SOURCE_CLASSES = ["handbook", "paper", "local"];

const yesNo = (ctx) => [
  { value: "yes", label: ctx.t("common.yes") },
  { value: "no", label: ctx.t("common.no") },
];

// Whether a card was calibrated is recorded as the operator's own choice: no answer is preset.
export function enterFields(ctx) {
  const classes = SOURCE_CLASSES.map((value) => ({ value, label: ctx.t(`evidence.class.${value}`) }));
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
    const card = await ctx.api.post("/evidence", { ...rest, calibrated: calibrated === "yes" }, { action: submitLabel });
    afterWrite(ctx, ctx.t("evidence.entered", { id: card.id }));
  };
  return simpleForm({ fields: enterFields(ctx), submitLabel, onSubmit, draftKey: "evidence:new", ctx });
}

function verifyForm(ctx, card) {
  const submitLabel = ctx.t("evidence.verify");
  const fields = [
    { name: "note", label: ctx.t("evidence.note"), type: "text" },
    { name: "calibrated", label: ctx.t("evidence.attest"), type: "select", value: "no", options: yesNo(ctx) },
  ];
  const onSubmit = async ({ note: text, calibrated }) => {
    const body = { note: text || "", calibrated: calibrated === "yes" };
    await ctx.api.post(`/evidence/${encodeURIComponent(card.id)}/verify`, body, { action: submitLabel });
    afterWrite(ctx, ctx.t("evidence.verified", { id: card.id }));
  };
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: `evidence-verify:${card.id}`, ctx });
}

function factsLine(ctx, card) {
  const hasValue = card.value !== null && card.value !== undefined;
  const parts = [ctx.t(`evidence.class.${card.source_class}`)];
  if (hasValue) parts.push(ctx.t("evidence.valueOf", { value: `${card.value} ${card.unit || ""}`.trim() }));
  if (!card.calibrated) parts.push(ctx.t("evidence.uncalibrated"));
  parts.push(ctx.t("evidence.entryLine", { source: card.source || "—", time: timeText(ctx, card.added_at) }));
  return parts.join(" · ");
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
    h("div", { class: "evidence-head" }, h("code", { text: card.id }), pill),
    h("p", { class: "evidence-claim", text: card.claim }),
    h("p", { class: "cell-sub", text: ctx.t("evidence.citedFrom", { citation: card.citation }) }),
    h("p", { class: "cell-sub", text: factsLine(ctx, card) }),
    verificationBlock(ctx, card),
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
