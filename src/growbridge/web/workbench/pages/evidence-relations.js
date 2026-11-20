// The relations between evidence cards: the list with review and withdrawal, and the form to record one.
import { labelOr } from "../i18n.js";
import { h } from "../ui/dom.js";
import { confirmOrCancel, simpleForm } from "../ui/forms.js";
import { afterWrite, confirmedButton, errorParts, note, section, timeText } from "../ui/section.js";
import { enteredBy } from "./evidence-card.js";
import { claimName } from "./evidence-text.js";

const KINDS = ["supersedes", "contradicts", "retracts"];
const REASON_CHARS = 500;
const STATE_PILL = { pending: "pill-waiting", confirmed: "pill-active", rejected: "pill-onsite", withdrawn: "pill-onsite" };
const SENTENCES = { supersedes: "evidence.relation.supersedes", contradicts: "evidence.relation.contradicts", retracts: "evidence.relation.retracts" };
const REVIEW_KEYS = {
  confirmed: { label: "evidence.relation.confirm", title: "evidence.relation.confirmTitle", line: "evidence.relation.confirmLine", done: "evidence.relation.confirmed" },
  rejected: { label: "evidence.relation.reject", title: "evidence.relation.rejectTitle", line: "evidence.relation.rejectLine", done: "evidence.relation.rejected" },
};
const base = (id) => `/evidence/relations/${encodeURIComponent(id)}`;

// A card as a sentence names it: its claim when this page lists it, else "another card".
function cardName(ctx, env, id) {
  const card = env.byId.get(id);
  return card ? claimName(card.claim) : ctx.t("evidence.otherCard");
}

function sentence(ctx, env, relation) {
  const params = { subject: cardName(ctx, env, relation.subject_id), object: cardName(ctx, env, relation.object_id) };
  return Object.hasOwn(SENTENCES, relation.kind) ? ctx.t(SENTENCES[relation.kind], params) : ctx.t("common.unknown");
}

function reviewButton(ctx, relation, decision) {
  const keys = REVIEW_KEYS[decision];
  const label = ctx.t(keys.label);
  const run = async () => {
    await ctx.api.post(`${base(relation.id)}/review`, { decision, note: "" }, { action: label });
    afterWrite(ctx, ctx.t(keys.done));
  };
  return confirmedButton(ctx, { label, title: ctx.t(keys.title), lines: [ctx.t(keys.line)], tone: decision === "rejected" ? "quiet" : "primary", run });
}

function withdrawForm(ctx, relation) {
  const submitLabel = ctx.t("evidence.relation.withdraw");
  const fields = [{ name: "reason", label: ctx.t("evidence.relation.withdrawReason"), type: "textarea", required: true, maxlength: REASON_CHARS }];
  const onSubmit = async ({ reason }) => {
    const prompt = { title: ctx.t("evidence.relation.withdrawTitle"), lines: [ctx.t("evidence.relation.withdrawLine")], confirmLabel: submitLabel };
    await confirmOrCancel(ctx, prompt);
    await ctx.api.post(`${base(relation.id)}/withdraw`, { reason }, { action: submitLabel });
    afterWrite(ctx, ctx.t("evidence.relation.withdrawn"));
  };
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: `relation-withdraw:${relation.id}`, ctx });
}

function actions(ctx, record) {
  const relation = record.relation;
  if (record.state === "pending") return h("div", { class: "action-row" }, reviewButton(ctx, relation, "confirmed"), reviewButton(ctx, relation, "rejected"));
  if (record.state === "confirmed") return h("details", { class: "row-form" }, h("summary", { text: ctx.t("evidence.relation.withdraw") }), withdrawForm(ctx, relation));
  return null;
}

function relationView(ctx, record, env) {
  const relation = record.relation;
  const pill = h("span", { class: ["pill", STATE_PILL[record.state]], text: labelOr(ctx.t, "evidence.relation.state", record.state) });
  const by = ctx.t("evidence.relation.by", { name: enteredBy(ctx, relation.source), time: timeText(ctx, relation.at) });
  return h(
    "li",
    { class: "evidence-card" },
    h("div", { class: "evidence-head" }, h("h3", { class: "evidence-claim", text: sentence(ctx, env, relation) }), pill),
    relation.reason ? h("p", { text: ctx.t("evidence.relation.reason", { reason: relation.reason }) }) : null,
    h("p", { class: "cell-sub", text: by }),
    actions(ctx, record),
  );
}

function recordForm(ctx, env) {
  const submitLabel = ctx.t("evidence.relation.record");
  const choose = { value: "", label: ctx.t("form.choose") };
  const cards = env.cards.map((card) => ({ value: card.id, label: claimName(card.claim) }));
  const fields = [
    { name: "kind", label: ctx.t("evidence.relation.kind"), type: "select", required: true, options: [choose, ...KINDS.map((value) => ({ value, label: labelOr(ctx.t, "evidence.relation.kind", value) }))] },
    { name: "card_id", label: ctx.t("evidence.relation.card"), type: "select", required: true, options: [choose, ...cards] },
    { name: "other_card_id", label: ctx.t("evidence.relation.other"), type: "select", options: [choose, ...cards] },
    { name: "reason", label: ctx.t("evidence.relation.formReason"), type: "textarea", required: true, maxlength: REASON_CHARS },
  ];
  const onSubmit = async (values) => {
    await confirmOrCancel(ctx, { title: ctx.t("evidence.relation.recordTitle"), lines: [ctx.t("evidence.relation.recordLine")], confirmLabel: submitLabel });
    await ctx.api.post("/evidence/relations", values, { action: submitLabel });
    afterWrite(ctx, ctx.t("evidence.relation.recorded"));
  };
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: "evidence-relation:new", ctx });
}

async function loadRelations(ctx, env) {
  const query = env.projectId ? `?project_id=${encodeURIComponent(env.projectId)}` : "";
  const data = await ctx.api.get(`/evidence/relations${query}`);
  return Array.isArray(data && data.relations) ? data.relations : [];
}

// The list and the form, as two sections; a list that could not be read says why in its own place.
export async function relationSections(ctx, env) {
  let body;
  try {
    const records = await loadRelations(ctx, env);
    const list = h("ul", { class: "evidence-list", attrs: { "aria-label": ctx.t("evidence.relations") } }, records.map((record) => relationView(ctx, record, env)));
    body = records.length ? list : note(ctx.t("evidence.relations.empty"));
  } catch (error) {
    body = h("div", { class: "form-status form-status-error" }, errorParts(ctx, error));
  }
  return [section(ctx.t("evidence.relations"), body), section(ctx.t("evidence.relation.new"), recordForm(ctx, env))];
}
