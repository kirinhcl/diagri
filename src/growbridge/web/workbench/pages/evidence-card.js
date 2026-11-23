// One evidence card: its claim, status, replacement or contradicting cards, context fields and verification.
import { labelOr } from "../i18n.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { roleLabel } from "../ui/names.js";
import { keyValues, techDetails, timeText } from "../ui/section.js";
import { verifyForm } from "./evidence-forms.js";
import { claimName, exactNumber, rangeText, variableName } from "./evidence-text.js";

// Who entered a card: "you" for the signed-in operator, the agent's role for the model's own cards
// (agents/handlers_evidence.py SOURCE), any other operator name as it was recorded.
const AGENT_SOURCES = { "model:planner": "planner" };
const BLOCKING = { superseded: "pill-waiting", retracted: "pill-onsite", dependency_invalid: "pill-onsite" };

export function enteredBy(ctx, source) {
  if (!source) return "—";
  if (ctx.me && source === ctx.me.operator) return roleLabel(ctx.t, "user");
  return Object.hasOwn(AGENT_SOURCES, source) ? roleLabel(ctx.t, AGENT_SOURCES[source]) : source;
}

const present = (value) => value !== null && value !== undefined && value !== "";

// A link to a card on the evidence page, in the same project.
export function cardLink(env, id, text) {
  const href = hrefFor("evidence", { projectId: env.projectId, focus: id });
  return h("a", { class: "text-link", attrs: { href }, text });
}

// A card named by its claim when this page lists it, "another card" when a filter hides it.
export function cardRef(ctx, env, id) {
  const card = env.byId.get(id);
  return card ? cardLink(env, id, claimName(card.claim)) : h("span", { text: ctx.t("evidence.otherCard") });
}

function facts(ctx, card, variables) {
  const hasValue = card.value !== null && card.value !== undefined;
  const conditions = Array.isArray(card.conditions) ? card.conditions.map((range) => rangeText(ctx, variables, range)) : [];
  return keyValues([
    [ctx.t("evidence.fact.class"), labelOr(ctx.t, "evidence.class", card.source_class)],
    [ctx.t("evidence.fact.variable"), present(card.variable) ? variableName(ctx, variables, card.variable) : null],
    [ctx.t("evidence.fact.value"), hasValue ? `${exactNumber(card.value, ctx.lang)} ${card.unit || ""}`.trim() : null],
    [ctx.t("evidence.fact.conditions"), conditions.length ? conditions.join(ctx.t("common.listSep")) : null],
    [ctx.t("evidence.fact.crop"), card.crop_taxon],
    [ctx.t("evidence.fact.cultivar"), card.cultivar],
    [ctx.t("evidence.fact.stage"), card.growth_stage],
    [ctx.t("evidence.fact.context"), card.conditions_note],
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

function pills(ctx, card) {
  const status = card.status || {};
  const verified = Boolean(card.verified_by);
  const list = [h("span", { class: ["pill", verified ? "pill-active" : "pill-waiting"], text: ctx.t(verified ? "evidence.status.verified" : "evidence.status.unverified") })];
  if (Object.hasOwn(BLOCKING, status.validity)) list.push(h("span", { class: ["pill", BLOCKING[status.validity]], text: labelOr(ctx.t, "evidence.validity", status.validity) }));
  return list;
}

// The end of the replacement chain, and when that card is no longer in force either, its status and
// the way out (design §5.3).
function replacement(ctx, status, env) {
  const target = status.current_replacement;
  if (!target) return h("p", { class: "cell-sub", text: ctx.t("evidence.noReplacement") });
  const link = h("p", {}, `${ctx.t("evidence.replacedBy")}: `, cardRef(ctx, env, target.card_id));
  if (target.validity === "active") return link;
  const validity = labelOr(ctx.t, "evidence.validity", target.validity);
  return [link, h("p", { class: "cell-sub", text: ctx.t("evidence.replacementInactive", { validity }) })];
}

// What the card's status says beyond its pill: the replacement, the reason, the contradicting cards.
function statusNotes(ctx, card, env) {
  const status = card.status || {};
  const notes = [];
  if (status.validity === "superseded") notes.push(replacement(ctx, status, env));
  if (status.validity === "retracted") notes.push(h("p", { text: ctx.t("evidence.retractedBecause", { reason: status.retracted_reason || "—" }) }));
  if (status.validity === "dependency_invalid") notes.push(h("p", { text: ctx.t("evidence.invalidDependency") }));
  const others = Array.isArray(status.contested_with) ? status.contested_with : [];
  if (others.length) notes.push(h("p", {}, `${ctx.t("evidence.contestedWith")}: `, others.flatMap((id, i) => [i ? ", " : null, cardRef(ctx, env, id)])));
  const pending = Array.isArray(status.pending) ? status.pending.length : 0;
  if (pending) notes.push(h("p", { class: "cell-sub", text: ctx.t("evidence.pendingNote", { n: pending }) }));
  return notes;
}

function originLine(ctx, card) {
  if (!card.origin) return null;
  const label = labelOr(ctx.t, "report.labels", card.origin.label);
  const href = hrefFor("round", { roundId: card.origin.round_id });
  return h("p", { class: "cell-sub" }, h("a", { class: "text-link", attrs: { href }, text: ctx.t("evidence.origin", { label }) }));
}

// `env`: { variables, byId (cards of the page by id), projectId, focus }.
export function cardView(ctx, card, env) {
  const focused = env.focus === card.id;
  return h(
    "li",
    { class: ["evidence-card", focused ? "evidence-card-focused" : null], attrs: { id: `card-${card.id}` } },
    h("div", { class: "evidence-head" }, h("h3", { class: "evidence-claim", text: card.claim }), h("span", { class: "evidence-pills" }, pills(ctx, card))),
    h("p", { class: "cell-sub", text: ctx.t("evidence.citedFrom", { citation: card.citation }) }),
    statusNotes(ctx, card, env),
    facts(ctx, card, env.variables),
    originLine(ctx, card),
    verificationBlock(ctx, card),
    techDetails(ctx.t, [[ctx.t("tech.id.id"), card.id], [ctx.t("evidence.fact.rawValue"), card.value]]),
  );
}
