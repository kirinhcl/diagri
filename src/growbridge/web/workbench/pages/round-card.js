// The round page's evidence-card block: make the delivered report's conclusion a card, link the card
// once it exists, or say why the round cannot become one.
import { messageParts } from "../messages.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { confirmOrCancel, simpleForm } from "../ui/forms.js";
import { afterWrite, note, section } from "../ui/section.js";
import { conditionsPart, contextFields } from "./evidence-forms.js";

// The variables a condition may name: the evidence list's own picker. `failed` when it cannot be read.
async function pickableVariables(ctx) {
  try {
    const data = await ctx.api.get("/evidence");
    return { variables: Array.isArray(data && data.variables) ? data.variables : [], failed: false };
  } catch {
    return { variables: [], failed: true };
  }
}

async function makeForm(ctx, round) {
  const submitLabel = ctx.t("round.card.make");
  const fields = [
    ...contextFields(ctx),
    { name: "value", label: ctx.t("evidence.value"), type: "number" },
    { name: "unit", label: ctx.t("evidence.unit"), type: "text" },
  ];
  const onSubmit = async (values) => {
    await confirmOrCancel(ctx, { title: ctx.t("round.card.confirmTitle"), lines: [ctx.t("round.card.confirmLine")], confirmLabel: submitLabel });
    await ctx.api.post(`/rounds/${encodeURIComponent(round.round_id)}/evidence`, values, { action: submitLabel });
    afterWrite(ctx, ctx.t("round.card.made"));
  };
  const { variables, failed } = await pickableVariables(ctx);
  const form = simpleForm({ fields, parts: [conditionsPart(ctx, variables)], submitLabel, onSubmit, draftKey: `round-card:${round.round_id}`, ctx });
  return failed ? [note(ctx.t("round.card.variablesFailed")), form] : [form];
}

function existingCard(ctx, round, cardId) {
  const href = hrefFor("evidence", { projectId: round.project_id, focus: cardId });
  return [note(ctx.t("round.card.exists")), h("a", { class: "text-link", attrs: { href }, text: ctx.t("round.card.open") })];
}

// The refusal in the console's words, with its next step; the code and params go to the details.
function refusal(ctx, refused) {
  const parts = messageParts(ctx, "denial", refused.reason, refused.params);
  const text = parts.known ? parts.text : ctx.t("round.card.cannot");
  return [note(text), parts.known && parts.action ? note(parts.action) : null];
}

// `card` is the report's `round_card`: {} (can convert), {card_id} (converted), {refusal} (cannot).
export async function cardSection(ctx, round, card) {
  if (!card || typeof card !== "object") return null;
  if (card.card_id) return section(ctx.t("round.card.title"), ...existingCard(ctx, round, card.card_id));
  if (card.refusal) return section(ctx.t("round.card.title"), ...refusal(ctx, card.refusal));
  return section(ctx.t("round.card.title"), note(ctx.t("round.card.lead")), ...(await makeForm(ctx, round)));
}
