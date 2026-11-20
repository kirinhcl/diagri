// Evidence cards: every card with its status, source and verification, the filters, the relations
// between cards, and the forms to enter a card and to record a relation.
import { formatTime, zonedToEpoch } from "../format.js";
import { labelOr } from "../i18n.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { note, pageHead, section, siteZone } from "../ui/section.js";
import { cardView } from "./evidence-card.js";
import { enterForm } from "./evidence-forms.js";
import { relationSections } from "./evidence-relations.js";
import { variableName } from "./evidence-text.js";

export { claimName } from "./evidence-text.js";
export { enterFields } from "./evidence-forms.js";

const VALIDITIES = ["active", "superseded", "retracted", "dependency_invalid"];
const MINUTE_TEXT = "YYYY-MM-DDTHH:MM".length; // a datetime-local value may carry ":00" seconds

// A labelled select; picking a value reads the page again with the new address (the linked card is let go).
function filterSelect(ctx, { label, key, params, options }) {
  const id = `evidence-filter-${key}`;
  const choose = (event) => ctx.navigate(hrefFor("evidence", { ...params, focus: undefined, [key]: event.target.value }));
  const choices = options.map((option) => h("option", { attrs: { value: option.id, selected: option.id === (params[key] || "") }, text: option.text }));
  const select = h("select", { class: "input", attrs: { id }, on: { change: choose } }, choices);
  return h("div", { class: "field" }, h("label", { class: "field-label", attrs: { for: id }, text: label }), select);
}

// The projects to choose from; `failed` when the list cannot be read (the filters then say so).
async function projectChoices(ctx) {
  try {
    const data = await ctx.api.get("/projects");
    const projects = data && Array.isArray(data.projects) ? data.projects : [];
    return { projects: projects.map((project) => ({ id: project.project_id, text: project.name || project.project_id })), failed: false };
  } catch {
    return { projects: [], failed: true };
  }
}

// Global, the listed projects, and the selected project when the list does not name it, so the select
// never reads "Global" over a project's cards and statuses.
function projectOptions(ctx, params, projects) {
  const selected = params.projectId;
  const unlisted = selected && !projects.some((project) => project.id === selected) ? [{ id: selected, text: selected }] : [];
  return [{ id: "", text: ctx.t("evidence.filter.global") }, ...projects, ...unlisted];
}

// The time in the address, in epoch seconds; null for none (the cards as they are now).
function asOfSeconds(params) {
  return /^\d+(\.\d+)?$/.test(params.asOf || "") ? Number(params.asOf) : null;
}

// Picking a time reads the page again as of it, clearing the field reads it as of now; a time the
// site's zone skips is refused with a notice and the address stays as it was.
function asOfChange(ctx, params, zone) {
  return (event) => {
    const text = event.target.value;
    let asOf;
    try {
      asOf = text ? zonedToEpoch(text.slice(0, MINUTE_TEXT), zone).epoch : undefined;
    } catch {
      ctx.notify(ctx.t("form.badTime", { zone }), "error");
      return;
    }
    ctx.navigate(hrefFor("evidence", { ...params, focus: undefined, asOf }));
  };
}

// The time to see the cards as of, in the site's zone (design §5.7); empty is now.
function asOfField(ctx, params) {
  const id = "evidence-filter-asOf";
  const zone = siteZone(ctx);
  const asOf = asOfSeconds(params);
  const value = asOf === null ? "" : formatTime(asOf, zone, ctx.lang).replace(" ", "T");
  const input = h("input", { class: "input", attrs: { id, type: "datetime-local", value }, on: { change: asOfChange(ctx, params, zone) } });
  const label = h("label", { class: "field-label", attrs: { for: id }, text: ctx.t("evidence.filter.asOf") });
  return h("div", { class: "field" }, label, input, h("span", { class: "field-zone", text: zone }));
}

// Project, validity, variable and time; then a note when the project list could not be read.
function filterBar(ctx, params, choices, variables) {
  const all = { id: "", text: ctx.t("evidence.filter.all") };
  const selects = [
    { label: ctx.t("evidence.filter.project"), key: "projectId", options: projectOptions(ctx, params, choices.projects) },
    { label: ctx.t("evidence.filter.status"), key: "status", options: [all, ...VALIDITIES.map((id) => ({ id, text: labelOr(ctx.t, "evidence.validity", id) }))] },
    { label: ctx.t("evidence.filter.variable"), key: "variable", options: [all, ...variables.map((v) => ({ id: v.id, text: variableName(ctx, variables, v.id) }))] },
  ];
  const group = { class: "filter-bar", attrs: { role: "group", "aria-label": ctx.t("evidence.filters") } };
  const bar = h("div", group, selects.map((spec) => filterSelect(ctx, { ...spec, params })), asOfField(ctx, params));
  return [bar, choices.failed ? note(ctx.t("evidence.filter.projectsFailed")) : null];
}

function cardList(ctx, cards, env) {
  return h("ul", { class: "evidence-list", attrs: { "aria-label": ctx.t("evidence.list") } }, cards.map((card) => cardView(ctx, card, env)));
}

function query(params) {
  const found = new URLSearchParams();
  for (const [key, name] of [["projectId", "project_id"], ["status", "status"], ["variable", "variable"]]) {
    if (params[key]) found.set(name, params[key]);
  }
  const asOf = asOfSeconds(params);
  if (asOf !== null) found.set("as_of", String(asOf));
  const text = found.toString();
  return text ? `?${text}` : "";
}

// Once the page is in the document: bring the linked card into view (a no-op without scrollIntoView).
function scrollToCard(element, focus) {
  const find = (node) => [...(node.children || [])].flatMap((child) => [child, ...find(child)]);
  const card = find(element).find((el) => el.getAttribute && el.getAttribute("id") === `card-${focus}`);
  if (!card || typeof card.scrollIntoView !== "function") return;
  setTimeout(() => card.scrollIntoView({ block: "center" }), 0);
}

export async function render(ctx, params = {}) {
  const [data, choices] = await Promise.all([ctx.api.get(`/evidence${query(params)}`), projectChoices(ctx)]);
  const cards = Array.isArray(data && data.cards) ? data.cards : [];
  const variables = Array.isArray(data && data.variables) ? data.variables : [];
  const env = { variables, cards, byId: new Map(cards.map((card) => [card.id, card])), projectId: params.projectId, focus: params.focus };
  const relations = await relationSections(ctx, env);
  const element = h(
    "div",
    { class: "page evidence" },
    pageHead(ctx.t("nav.evidence"), ctx.t("evidence.lead")),
    filterBar(ctx, params, choices, variables),
    section(ctx.t("evidence.list"), cards.length ? cardList(ctx, cards, env) : note(ctx.t("evidence.empty"))),
    section(ctx.t("evidence.new"), enterForm(ctx, variables), note(ctx.t("evidence.roundHint"))),
    relations,
  );
  if (params.focus) scrollToCard(element, params.focus);
  return { element };
}
