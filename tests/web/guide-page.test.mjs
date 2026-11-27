// The guide page: the step rail, the cards of the six answer steps, and the draft summary. The page
// sends exactly what the server's choose route takes; it never invents an answer.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { clearDrafts } from "../../src/growbridge/web/workbench/drafts.js";
import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { visibleText } from "./support/leaks.mjs";
import { FIXTURES, renderPage } from "./support/render-page.mjs";

afterEach(() => clearDrafts());

const BASE = FIXTURES["guide-session.json"];
const SESSION_PATH = "/guide/sessions/guide-1";
const settle = () => new Promise((resolve) => setImmediate(resolve));
const flush = async () => {
  for (let i = 0; i < 6; i += 1) await settle();
};
const find = (node, match) => [...(match(node) ? [node] : []), ...[...(node.children || [])].flatMap((child) => find(child, match))];
const byTag = (node, tag) => find(node, (el) => el.localName === tag);
const byClass = (node, name) => find(node, (el) => el.classList && el.classList.contains(name));
const named = (node, name) => find(node, (el) => el.getAttribute && el.getAttribute("name") === name);
const change = (input, value) => {
  input.value = value;
  input.dispatchEvent(new Event("input"));
  input.dispatchEvent(new Event("change"));
};
// A radio or a check box, chosen by its name and value.
const pick = (root, name, value) => {
  const input = named(root, name).find((el) => el.getAttribute("value") === value);
  assert.ok(input, `${name}=${value}`);
  input.checked = true;
  input.dispatchEvent(new Event("change"));
};
const railItems = (root) => byClass(root, "guide-rail-item");
const titleOf = (item) => byClass(item, "guide-rail-title")[0].textContent;
const currentTitle = (root) => {
  const current = railItems(root).find((item) => item.getAttribute("aria-current") === "step");
  return current ? titleOf(current) : null;
};
const submit = async (root) => {
  byTag(byClass(root, "guide-card")[0], "form")[0].dispatchEvent(new Event("submit", { cancelable: true }));
  await flush();
};
const text = (root) => visibleText(root);

const ANSWERS = {
  question: { question: "Does more light speed up growth?", hypothesis: "" },
  crop: { crop: "Lettuce", crop_taxon: "NCBITaxon:4236" },
  treatments: {
    treatments: [
      { id: "control", name: "Light 40", description: "", factors: { light: 40 } },
      { id: "high", name: "Light 70", description: "", factors: { light: 70 } },
    ],
    control_treatment_id: "control",
  },
  measures: { variables: ["canopy_area_growth"], primary_endpoint: "canopy_area_growth" },
  analysis: { target_effect: 0.15, method: "paired_block", exclusion_rules: [], max_missing_fraction: 0.2, max_deviation_fraction: 0.1 },
  scale: { layout: "series", blocks: 3, units: ["tent-1"], stages: ["vegetative"], experimental_unit: "tent" },
};

// A session view: the steps in `done` answered (with their source and status when given), the rest pending.
function session(done = [], { source = {}, status = {} } = {}) {
  const steps = BASE.steps.map(({ step }, index) =>
    done.includes(step)
      ? { step, status: status[step] || "done", chosen: { step, answer: ANSWERS[step], source: source[step] || "own", option_ids: [], seq: index + 2 } }
      : { step, status: "pending", chosen: null },
  );
  return { ...BASE, steps };
}
const option = (id, zh, en, value) => ({ id, value, label_zh: zh, label_en: en });
const OPTIONS = {
  treatments: { step: "treatments", options: [option("light", "光照", "Light", { factor: "light", unit: "%" })], defaults: {} },
  measures: {
    step: "measures",
    options: [
      option("canopy_area_growth", "冠层面积增长", "Canopy area growth", { variable: "canopy_area_growth", kind: "manual", unit: "cm2" }),
      option("air_temperature", "气温", "Air temperature", { variable: "air_temperature", kind: "sensor", unit: "C" }),
    ],
    defaults: {},
  },
  analysis: {
    step: "analysis",
    options: [option("paired_block", "配对区组", "Paired blocks", { method: "paired_block" }), option("two_group", "两组比较", "Two groups", { method: "two_group" })],
    defaults: { max_missing_fraction: 0.2, max_deviation_fraction: 0.1 },
  },
  scale: {
    step: "scale",
    options: [option("series", "连续轮次", "Run in series", { layout: "series" }), option("tents", "多帐篷并行", "Side by side in tents", { layout: "tents" })],
    defaults: { randomization_seed: 417978402, experimental_unit: "tent" },
  },
};
const ALL = ["question", "crop", "treatments", "measures", "analysis", "scale"];
const BEFORE = Object.fromEntries(ALL.map((step, index) => [step, ALL.slice(0, index)]));

// The page for the step that is current once the steps before it are done (or for `view`).
async function open(step, { done = BEFORE[step], files = {}, answers = {}, lang = "zh", view } = {}) {
  const options = OPTIONS[step] ? { [`guide-options-${step}.json`]: OPTIONS[step] } : {};
  const fixtures = { "guide-session.json": view || session(done), ...options, ...files };
  return renderPage("guide", { sessionId: "guide-1" }, { lang, fixtures, answers });
}
const chooseCalls = (ctx, step) => ctx.api.calls.filter((call) => call.method === "POST" && call.path === `${SESSION_PATH}/steps/${step}/choose`);
const answering = (step, view) => ({ [`${SESSION_PATH}/steps/${step}/choose`]: () => view });

test("the rail shows nine steps and opens the first pending one", async () => {
  const { element } = await renderPage("guide", { sessionId: "guide-1" }, { lang: "zh" });
  assert.equal(railItems(element).length, 9);
  assert.equal(currentTitle(element), "研究问题");
});

test("the current step is the first pending one, and the review once all are answered", async () => {
  const { element } = await open("scale", { view: session(ALL) });
  assert.equal(currentTitle(element), "复核保存");
  const mixed = await open("crop", { view: session(["question", "treatments"]) });
  assert.equal(currentTitle(mixed.element), "作物");
});

test("choosing a listed crop sends its option id", async () => {
  const { element, ctx } = await open("crop", { answers: answering("crop", session(["question", "crop"], { source: { crop: "system" } })) });
  pick(element, "crop", "lettuce");
  await submit(element);
  const [call] = chooseCalls(ctx, "crop");
  assert.deepEqual(call.body.option_ids, ["lettuce"]);
  assert.equal(call.body.answer.crop_taxon, FIXTURES["guide-options-crop.json"].options[0].value.crop_taxon);
  assert.equal(call.body.answer.crop, "Lettuce");
});

test("a crop outside the table is typed, with the NCBI lookup opening in a new tab", async () => {
  const { element, ctx } = await open("crop", { answers: answering("crop", session(["question", "crop"])) });
  pick(element, "crop", "__other__");
  change(named(element, "crop_name")[0], "Rocket");
  change(named(element, "crop_taxon")[0], "NCBITaxon:3707");
  const link = byTag(element, "a").find((a) => a.getAttribute("href") === "https://www.ncbi.nlm.nih.gov/taxonomy");
  assert.ok(link);
  assert.equal(link.getAttribute("target"), "_blank");
  assert.match(link.getAttribute("rel"), /noopener/);
  await submit(element);
  const [call] = chooseCalls(ctx, "crop");
  assert.deepEqual(call.body, { answer: { crop: "Rocket", crop_taxon: "NCBITaxon:3707" }, option_ids: [] });
});

test("the crop names follow the language of the page", async () => {
  const zh = await open("crop", { lang: "zh" });
  assert.match(text(zh.element), /生菜/);
  const en = await open("crop", { lang: "en" });
  assert.match(text(en.element), /Lettuce/);
});

test("the question step sends both texts", async () => {
  const { element, ctx } = await renderPage("guide", { sessionId: "guide-1" }, { answers: answering("question", session(["question"])) });
  change(named(element, "question")[0], "Does more light speed up growth?");
  await submit(element);
  assert.deepEqual(chooseCalls(ctx, "question")[0].body, { answer: ANSWERS.question, option_ids: [] });
});

test("the treatments step sends the factor, the rows and the control", async () => {
  const { element, ctx } = await open("treatments", { answers: answering("treatments", session(["question", "crop", "treatments"])) });
  pick(element, "factor", "light");
  const [first, second] = byClass(element, "row-group-row");
  for (const [row, id, name, level] of [[first, "control", "Light 40", "40"], [second, "high", "Light 70", "70"]]) {
    change(named(row, "id")[0], id);
    change(named(row, "name")[0], name);
    change(named(row, "level")[0], level);
  }
  change(named(element, "control")[0], "control");
  await submit(element);
  assert.deepEqual(chooseCalls(ctx, "treatments")[0].body, { answer: ANSWERS.treatments, option_ids: ["light"] });
});

test("two treatments with the same ID are refused beside the field", async () => {
  const { element, ctx } = await open("treatments");
  pick(element, "factor", "light");
  for (const row of byClass(element, "row-group-row")) {
    change(named(row, "id")[0], "same");
    change(named(row, "name")[0], "x");
    change(named(row, "level")[0], "1");
  }
  change(named(element, "control")[0], "same");
  await submit(element);
  assert.equal(chooseCalls(ctx, "treatments").length, 0);
  assert.match(text(element), /两个处理用了同一个编号/);
});

test("the main outcome is chosen among the ticked hand-measured variables", async () => {
  const { element, ctx } = await open("measures", { answers: answering("measures", session(["question", "crop", "treatments", "measures"])) });
  pick(element, "variable", "air_temperature");
  pick(element, "variable", "canopy_area_growth");
  const endpoint = named(element, "endpoint")[0];
  assert.deepEqual(byTag(endpoint, "option").map((o) => o.getAttribute("value")).filter(Boolean), ["canopy_area_growth"]);
  change(endpoint, "canopy_area_growth");
  await submit(element);
  const body = chooseCalls(ctx, "measures")[0].body;
  assert.deepEqual(body.answer, { variables: ["canopy_area_growth", "air_temperature"], primary_endpoint: "canopy_area_growth" });
  assert.deepEqual(body.option_ids, ["canopy_area_growth", "air_temperature"]);
});

test("a reopened measures step keeps a variable the catalog no longer offers", async () => {
  const kept = { variables: ["canopy_area_growth", "retired_height"], primary_endpoint: "retired_height" };
  const view = session(["question", "crop", "treatments", "measures"]);
  const withOld = { ...view, steps: view.steps.map((e) => (e.step === "measures" ? { ...e, chosen: { ...e.chosen, answer: kept, option_ids: ["canopy_area_growth"] } } : e)) };
  const answers = { ...answering("measures", view), [`${SESSION_PATH}/steps/measures/reopen`]: () => withOld };
  const { element, ctx } = await open("measures", { view: withOld, answers, files: { "guide-options-measures.json": OPTIONS.measures } });
  byTag(railItems(element).find((item) => titleOf(item) === "测量"), "button")[0].dispatchEvent(new Event("click"));
  await flush();
  const row = named(element, "variable").find((el) => el.getAttribute("value") === "retired_height");
  assert.ok(row && row.hasAttribute("checked"));
  assert.match(text(element), /目录里已不再提供/);
  pick(element, "variable", "canopy_area_growth");
  await submit(element);
  const body = chooseCalls(ctx, "measures")[0].body;
  assert.deepEqual(body.answer, kept);
  assert.deepEqual(body.option_ids, ["canopy_area_growth"]);
});

test("the analysis step prefills the two fractions and sends the method, effect and rules", async () => {
  const { element, ctx } = await open("analysis", { answers: answering("analysis", session(["question", "crop", "treatments", "measures", "analysis"])) });
  assert.equal(named(element, "max_missing_fraction")[0].value, "0.2");
  assert.equal(named(element, "max_deviation_fraction")[0].value, "0.1");
  pick(element, "method", "paired_block");
  change(named(element, "target_effect")[0], "0.15");
  change(named(element, "exclusion_rules")[0], "tent 3 failed\n\n");
  await submit(element);
  assert.deepEqual(chooseCalls(ctx, "analysis")[0].body, {
    answer: { ...ANSWERS.analysis, exclusion_rules: ["tent 3 failed"] },
    option_ids: ["paired_block"],
  });
});

test("a step to recheck says so", async () => {
  const view = session(ALL, { status: { analysis: "needs_review" } });
  const { element } = await open("analysis", { view });
  assert.equal(currentTitle(element), "分析计划");
  assert.match(text(element), /前面改过，请重看/);
});

test("the draft panel marks where each answer came from", async () => {
  const view = session(["question", "crop", "treatments"], { source: { question: "own", crop: "system", treatments: "carried" } });
  const { element } = await open("measures", { view });
  const panel = text(byClass(element, "guide-draft")[0]);
  const at = ["自己填写", "系统选项", "沿用上一版"].map((mark) => panel.indexOf(mark));
  assert.ok(at.every((index) => index >= 0), panel);
  assert.deepEqual([...at].sort((a, b) => a - b), at);
});

test("the sample-size helper fills the blocks", async () => {
  const answers = { "GET /guide/sample-size": () => ({ n: 6, design: "paired_block" }) };
  const { element, ctx } = await open("scale", { answers });
  change(named(element, "sd")[0], "0.4");
  byClass(element, "guide-estimate")[0].dispatchEvent(new Event("click"));
  await flush();
  assert.equal(named(element, "blocks")[0].value, "6");
  const read = ctx.api.calls.find((call) => call.path.startsWith("/guide/sample-size"));
  assert.equal(read.path, "/guide/sample-size?effect=0.15&sd=0.4&design=paired_block");
});

test("not knowing the spread fills two blocks and says the experiment is a pilot", async () => {
  const { element } = await open("scale");
  assert.doesNotMatch(text(element), /按先导实验处理/);
  byClass(element, "guide-unknown")[0].dispatchEvent(new Event("click"));
  assert.equal(named(element, "blocks")[0].value, "2");
  assert.match(text(element), /按先导实验处理，结论会是不确定/);
});

async function fillScale(element) {
  pick(element, "layout", "series");
  change(named(element, "blocks")[0], "3");
  change(named(element, "units")[0], "tent-1");
  change(named(element, "stages")[0], "vegetative");
  await submit(element);
}

test("the scale step sends the layout, the count, the units and the stages", async () => {
  const answers = { ...answering("scale", session(ALL)), [`GET ${SESSION_PATH}/review`]: () => ({ design: [] }) };
  const { element, ctx } = await open("scale", { answers });
  await fillScale(element);
  assert.deepEqual(chooseCalls(ctx, "scale")[0].body, { answer: ANSWERS.scale, option_ids: ["series"] });
});

test("a blocking design finding keeps the page on the scale step", async () => {
  const finding = { code: "unbalanced_block", message: "Block 1 has 1 treatment.", blocking: true, variant: "", params: {} };
  const answers = {
    ...answering("scale", session(ALL)),
    [`GET ${SESSION_PATH}/review`]: () => ({ protocol: null, missing: [], problems: [], design: [finding], ready: false }),
  };
  const { element } = await open("scale", { answers });
  await fillScale(element);
  assert.equal(currentTitle(element), "规模");
  assert.ok(byClass(element, "findings").length > 0);
  assert.match(text(byClass(element, "guide-card")[0]), /这些结果会拦住设计/);
});

test("a design with only hints moves on to the review", async () => {
  const answers = { ...answering("scale", session(ALL)), [`GET ${SESSION_PATH}/review`]: () => ({ design: [{ code: "unbalanced_block", message: "", blocking: false }] }) };
  const { element } = await open("scale", { answers });
  await fillScale(element);
  assert.equal(currentTitle(element), "复核保存");
});

test("a refused answer is shown on the card and nothing moves", async () => {
  const refuse = () => {
    throw new ApiError(422, "guide_answer_invalid", "refused");
  };
  const { element } = await open("crop", { answers: { [`${SESSION_PATH}/steps/crop/choose`]: refuse } });
  pick(element, "crop", "lettuce");
  await submit(element);
  assert.equal(currentTitle(element), "作物");
  assert.ok(byClass(element, "form-status-error").some((box) => !box.hasAttribute("hidden")));
});

test("a finished step opens again and is reopened on the server", async () => {
  const view = session(["question", "crop"]);
  const answers = { [`${SESSION_PATH}/steps/question/reopen`]: () => view };
  const { element, ctx } = await open("treatments", { view, answers });
  assert.equal(currentTitle(element), "处理");
  const done = railItems(element).find((item) => titleOf(item) === "研究问题");
  byTag(done, "button")[0].dispatchEvent(new Event("click"));
  await flush();
  assert.ok(ctx.api.calls.some((call) => call.method === "POST" && call.path === `${SESSION_PATH}/steps/question/reopen`));
  assert.equal(currentTitle(element), "研究问题");
  assert.equal(named(element, "question")[0].value, ANSWERS.question.question);
});

test("a saved version with no comparison does not break the page", async () => {
  const view = { ...session(["question"]), saved: [{ protocol_id: "protocol-1-b714da", version: 1, digest: "d", edited: null }] };
  const { element } = await open("crop", { view });
  assert.equal(currentTitle(element), "作物");
});

test("no text of the page says AI, in either language", async () => {
  for (const step of ["crop", "treatments", "measures", "analysis", "scale"]) {
    for (const lang of ["zh", "en"]) {
      const { element } = await open(step, { lang });
      assert.doesNotMatch(text(element), /\bAI\b/, `${step} ${lang}`);
    }
  }
});
