import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { answerNextDialog, assertNoPendingDialogAnswers, resetDialogs } from "./support/dialogs.mjs";
import { visibleText } from "./support/leaks.mjs";
import { renderPage, testCtx } from "./support/render-page.mjs";
import { messageParts } from "../../src/growbridge/web/workbench/messages.js";
import { hrefFor, parseHash } from "../../src/growbridge/web/workbench/router.js";
import { formControls } from "../../src/growbridge/web/workbench/ui/forms.js";

afterEach(() => {
  assertNoPendingDialogAnswers();
  resetDialogs();
});

const walk = (node) => [node, ...[...(node.children || [])].flatMap(walk)];
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const buttons = (element, text) => walk(element).filter((el) => el.localName === "button" && el.textContent === text);
const forms = (element) => walk(element).filter((el) => el.localName === "form");
const links = (element) => walk(element).filter((el) => el.localName === "a");

const CARD = { id: "card_old", source_class: "paper", citation: "Smith 2020", claim: "Blue light shortens lettuce", value: 12.5, unit: "cm", calibrated: true, source: "dev", added_at: 1796594000, verified_by: "dev", verified_at: 1796594100, note: null };
const ACTIVE = { card_id: "card_old", validity: "active", superseded_by: null, current_replacement: null, retracted_reason: null, contested_with: [], pending: [], invalid_dependency: null };
const NEWER = { ...CARD, id: "card_new", claim: "Red light shortens lettuce more", status: { ...ACTIVE, card_id: "card_new" } };
const OLD = { ...CARD, status: { ...ACTIVE, validity: "superseded", superseded_by: "card_new", current_replacement: { card_id: "card_new", validity: "active" } } };
const VARIABLES = [
  { id: "air_temperature", kind: "sensor", unit: "C", label_en: "Air temperature", label_zh: "气温" },
  { id: "leaf_area", kind: "manual", unit: "cm2", label_en: "Leaf area", label_zh: "叶面积" },
];
const evidence = (cards, variables = VARIABLES) => ({ "evidence.json": { cards, variables } });
const relations = (rows) => ({ "evidence-relations.json": { relations: rows } });
const RELATION = { relation: { id: "rel_1", kind: "supersedes", subject_id: "card_new", object_id: "card_old", reason: "newer trial", source: "dev", task_id: null, project_id: null, proposed_in: null, at: 1796594200 }, review: null, withdrawal: null, state: "pending" };

test("a superseded card shows its badge and links its replacement", async () => {
  const { element } = await renderPage("evidence", {}, { lang: "en", fixtures: evidence([OLD, NEWER]) });
  assert.match(visibleText(element), /Replaced/);
  const link = links(element).find((el) => el.getAttribute("href") === "#/evidence?focus=card_new");
  assert.ok(link, "a link to the replacement");
  assert.equal(link.textContent, NEWER.claim);
});

test("the replacement link keeps the selected project", async () => {
  const projectId = "project_a";
  const { element } = await renderPage("evidence", { projectId }, { lang: "en", fixtures: evidence([OLD, NEWER]) });
  assert.ok(links(element).some((el) => el.getAttribute("href") === hrefFor("evidence", { projectId, focus: "card_new" })));
});

test("the evidence page reads its filters from the address and the links write them back", () => {
  assert.deepEqual(parseHash("#/evidence?projectId=p1&status=retracted&variable=air_temperature&focus=c1"), { page: "evidence", params: { projectId: "p1", status: "retracted", variable: "air_temperature", focus: "c1" } });
  assert.equal(hrefFor("evidence", { projectId: "p 1", focus: "c1" }), "#/evidence?projectId=p%201&focus=c1");
  assert.equal(hrefFor("evidence"), "#/evidence");
});

test("a retracted card shows its reason and a contested card names the cards that contradict it", async () => {
  const retracted = { ...OLD, status: { ...ACTIVE, validity: "retracted", retracted_reason: "sensor was broken" } };
  const contested = { ...NEWER, status: { ...ACTIVE, card_id: "card_new", contested_with: ["card_old"] } };
  const { element } = await renderPage("evidence", {}, { lang: "en", fixtures: evidence([retracted, contested]) });
  const text = visibleText(element);
  assert.match(text, /Retracted/);
  assert.match(text, /sensor was broken/);
  assert.match(text, /Contradicted by/);
  assert.ok(!text.includes("card_old") && !text.includes("card_new"));
});

test("a card shows its new fields and the round it came from", async () => {
  const card = { ...CARD, variable: "air_temperature", conditions: [{ variable: "leaf_area", min: 1, max: null }], crop_taxon: "Lactuca sativa", cultivar: "Salanova", growth_stage: "vegetative", conditions_note: "indoor", status: ACTIVE, origin: { round_id: "round_x", report_artifact_id: "artifact_x", label: "descriptive" } };
  const { element } = await renderPage("evidence", {}, { lang: "en", fixtures: evidence([card]) });
  const text = visibleText(element);
  for (const part of ["Air temperature", "Lactuca sativa", "Salanova", "vegetative", "indoor", "Leaf area", "Descriptive"]) assert.ok(text.includes(part), part);
  assert.ok(links(element).some((el) => el.getAttribute("href") === hrefFor("round", { roundId: "round_x" })));
});

test("a pending relation offers confirm and reject; a confirmed one offers withdraw", async () => {
  const confirmed = { ...RELATION, relation: { ...RELATION.relation, id: "rel_2" }, review: { relation_id: "rel_2", decision: "confirmed", reviewer: "dev", note: "", at: 1796594300 }, state: "confirmed" };
  const { element, ctx } = await renderPage("evidence", {}, { lang: "en", fixtures: { ...evidence([OLD, NEWER]), ...relations([RELATION, confirmed]) } });
  assert.equal(buttons(element, "Confirm").length, 1);
  assert.equal(buttons(element, "Reject").length, 1);
  assert.equal(buttons(element, "Withdraw").length, 1);
  answerNextDialog(true);
  buttons(element, "Confirm")[0].dispatchEvent(new Event("click"));
  await settle();
  await settle();
  const post = ctx.api.calls.find((call) => call.method === "POST");
  assert.equal(post.path, "/evidence/relations/rel_1/review");
  assert.deepEqual(post.body, { decision: "confirmed", note: "" });
});

test("a withdrawal needs a reason", async () => {
  const confirmed = { ...RELATION, review: { relation_id: "rel_1", decision: "confirmed", reviewer: "dev", note: "", at: 1796594300 }, state: "confirmed" };
  const { element, ctx } = await renderPage("evidence", {}, { lang: "en", fixtures: { ...evidence([OLD, NEWER]), ...relations([confirmed]) } });
  const form = forms(element).find((f) => buttons(f, "Withdraw").length);
  const posts = () => ctx.api.calls.filter((call) => call.method === "POST");
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  assert.equal(posts().length, 0);
  formControls(form).set({ reason: "the trial was flawed" });
  answerNextDialog(true);
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  await settle();
  assert.deepEqual([posts()[0].path, posts()[0].body], ["/evidence/relations/rel_1/withdraw", { reason: "the trial was flawed" }]);
});

test("the variable picker lists the server's variables and nothing else", async () => {
  const { element } = await renderPage("evidence", {}, { lang: "en", fixtures: evidence([]) });
  const picker = walk(element).find((el) => el.localName === "select" && el.getAttribute("name") === "variable");
  const values = [...picker.children].map((option) => option.getAttribute("value"));
  assert.deepEqual(values, ["", "air_temperature", "leaf_area"]);
});

test("a card is entered with its variable, conditions and context; the conditions stop at 8 rows", async () => {
  const { element, ctx } = await renderPage("evidence", {}, { lang: "en", fixtures: evidence([]) });
  const form = forms(element).find((f) => buttons(f, "Enter card").length);
  const add = buttons(form, "Add condition")[0];
  for (let i = 0; i < 9; i += 1) if (!add.hasAttribute("disabled")) add.dispatchEvent(new Event("click")); // a disabled button takes no click
  assert.equal(walk(form).filter((el) => (el.getAttribute("class") || "") === "row-group-row").length, 8);
  assert.equal(add.hasAttribute("disabled"), true);
  formControls(form).set({ source_class: "paper", citation: "Smith 2020", claim: "A claim", calibrated: "yes", variable: "air_temperature", crop_taxon: "Lactuca sativa", cultivar: "Salanova", growth_stage: "vegetative", conditions_note: "indoor" });
  for (const row of walk(form).filter((el) => el.getAttribute("class") === "row-group-row").slice(1)) buttons(row, "Remove")[0].dispatchEvent(new Event("click"));
  const rowSelect = walk(form).find((el) => el.localName === "select" && el.getAttribute("name") === "variable" && el !== walk(form).find((s) => s.getAttribute("name") === "variable"));
  rowSelect.value = "leaf_area";
  answerNextDialog(true);
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  await settle();
  const body = ctx.api.calls.find((call) => call.method === "POST").body;
  assert.equal(body.variable, "air_temperature");
  assert.deepEqual(body.conditions, [{ variable: "leaf_area" }]);
  assert.deepEqual([body.crop_taxon, body.cultivar, body.growth_stage, body.conditions_note], ["Lactuca sativa", "Salanova", "vegetative", "indoor"]);
  assert.match(visibleText(element), /Round conclusions are made into cards from the round page/);
});

// --- the round page ------------------------------------------------------------------------------

const REPORT = structuredClone(JSON.parse(JSON.stringify((await import("./support/render-page.mjs")).FIXTURES["report.json"])));
const round = (card) => renderPage("round", { roundId: "round_9d38ffa4ca3049948194e0b60315c650" }, { lang: "en", fixtures: { "report.json": { ...REPORT, round_card: card }, ...evidence([]) } });

test("the convert button shows only for a delivered round with a usable report", async () => {
  const convertible = (await round({})).element;
  assert.equal(buttons(convertible, "Make evidence card").length, 1);
  const done = (await round({ card_id: "card_made" })).element;
  assert.equal(buttons(done, "Make evidence card").length, 0);
  assert.ok(links(done).some((el) => el.getAttribute("href").startsWith("#/evidence?") && el.getAttribute("href").includes("focus=card_made")));
  const refused = (await round({ refusal: { reason: "round_card_not_delivered", params: { state: "aborted" } } })).element;
  assert.equal(buttons(refused, "Make evidence card").length, 0);
  assert.match(visibleText(refused), /has not been delivered/);
  const none = (await renderPage("round", { roundId: "round_9d38ffa4ca3049948194e0b60315c650" }, { lang: "en" })).element;
  assert.equal(buttons(none, "Make evidence card").length, 0);
});

test("making a round's card sends its context and conditions to the round's route", async () => {
  const { element, ctx } = await round({});
  const form = forms(element).find((f) => buttons(f, "Make evidence card").length);
  formControls(form).set({ growth_stage: "vegetative", conditions_note: "indoor" });
  answerNextDialog(true);
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  await settle();
  const post = ctx.api.calls.find((call) => call.method === "POST");
  assert.equal(post.path, "/rounds/round_9d38ffa4ca3049948194e0b60315c650/evidence");
  assert.deepEqual(post.body, { growth_stage: "vegetative", conditions_note: "indoor", conditions: [] });
});

test("confirming or rejecting a pending relation sends the typed note", async () => {
  const { element, ctx } = await renderPage("evidence", {}, { lang: "en", fixtures: { ...evidence([OLD, NEWER]), ...relations([RELATION]) } });
  const field = walk(element).find((el) => el.localName === "textarea" && el.getAttribute("name") === "note");
  field.value = "the model's evidence checks out";
  answerNextDialog(true);
  buttons(element, "Confirm")[0].dispatchEvent(new Event("click"));
  await settle();
  await settle();
  const post = ctx.api.calls.find((call) => call.method === "POST");
  assert.deepEqual(post.body, { decision: "confirmed", note: "the model's evidence checks out" });
  field.value = "no";
  answerNextDialog(true);
  buttons(element, "Reject")[0].dispatchEvent(new Event("click"));
  await settle();
  await settle();
  assert.deepEqual(ctx.api.calls.filter((call) => call.method === "POST")[1].body, { decision: "rejected", note: "no" });
});

test("a note over 500 characters is refused beside the field and nothing is sent", async () => {
  const { element, ctx } = await renderPage("evidence", {}, { lang: "en", fixtures: { ...evidence([OLD, NEWER]), ...relations([RELATION]) } });
  walk(element).find((el) => el.localName === "textarea" && el.getAttribute("name") === "note").value = "x".repeat(501);
  answerNextDialog(true);
  buttons(element, "Confirm")[0].dispatchEvent(new Event("click"));
  await settle();
  await settle();
  assert.equal(ctx.api.calls.filter((call) => call.method === "POST").length, 0);
});

test("the round's card form says when the variable list could not be read", async () => {
  const fixtures = { "report.json": { ...REPORT, round_card: {} }, "evidence.json": null };
  const { element } = await renderPage("round", { roundId: "round_9d38ffa4ca3049948194e0b60315c650" }, { lang: "en", fixtures });
  assert.match(visibleText(element), /list of variables could not be read/);
  assert.equal(buttons(element, "Make evidence card").length, 1, "the card can still be made");
  const ok = (await round({})).element;
  assert.doesNotMatch(visibleText(ok), /list of variables could not be read/);
});

// --- copy fixes carried from earlier reviews -----------------------------------------------------

const say = (lang, family, code, params) => messageParts(testCtx({ lang }), family, code, params);

test("an exploratory finding names the round's label with the existing translation", () => {
  const en = say("en", "finding", "exploratory_finding", { source_kind: "rule", source: "r1", label: "descriptive" }).text;
  assert.match(en, /from a round labelled “Descriptive”|from a round labelled Descriptive/);
  const zh = say("zh", "finding", "exploratory_finding", { source_kind: "rule", source: "r1", label: "confirmatory" }).text;
  assert.ok(zh.includes("确认性") && !zh.includes("确证性"), zh);
});

test("the card's unit is shown as a unit, like the rule's", () => {
  const { text } = say("en", "finding", "evidence_unit_mismatch", { source_kind: "rule", source: "r1", rule_unit: "C", card_unit: "C" });
  const [rule, card] = [/uses unit (\S+),/.exec(text), /is in (\S+)\./.exec(text)];
  assert.equal(rule[1], card[1]);
});

test("findings do not print card or relation ids", () => {
  const contested = say("en", "finding", "contested_source", { source_kind: "rule", source: "r1", other_card_ids: ["card_zz"], others: ["card_zz"] });
  const pending = say("en", "finding", "pending_relation", { source_kind: "rule", source: "r1", relation_ids: ["rel_zz"], relations: ["rel_zz"] });
  for (const part of [contested, pending]) assert.ok(!part.text.includes("_zz") && !part.text.includes("—"), part.text);
});

test("a replaced source's next step is right with and without a replacement", () => {
  const { action } = say("en", "finding", "superseded_source", { source_kind: "rule", source: "r1" });
  assert.ok(!/current card instead/.test(action), action);
});

test("an undelivered round is not told to wait for delivery", () => {
  for (const lang of ["en", "zh"]) {
    const { text, action } = say(lang, "denial", "round_card_not_delivered", { state: "aborted" });
    assert.ok(!/Wait until|等这一轮交付/.test(`${text} ${action}`), `${text} ${action}`);
  }
});
