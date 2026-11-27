// The guide page: a rail of the nine steps, the card of the step being answered, and the draft so far.
// Steps 1-6 are answered here (guide-steps.js); the review and the round step come later, so for now
// they show a plain card. Every answer is kept on the server; this page only holds which step is open.
import { labelOr, textOr } from "../i18n.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { errorParts, note, pageHead, section } from "../ui/section.js";
import { reviewStep, roundStep, savedReview } from "./guide-review.js";
import { stepCard } from "./guide-steps.js";

const RAIL = ["project", "question", "crop", "treatments", "measures", "analysis", "scale", "review", "round"];
const ANSWERED = RAIL.slice(1, 7);
const array = (value) => (Array.isArray(value) ? value : []);
const enc = encodeURIComponent;

const entryOf = (session, step) => array(session.steps).find((entry) => entry.step === step) || { step, status: "pending", chosen: null };

// The latest save came after every choice, so the protocol saved is what the choices make: the review has
// nothing new to offer until something is chosen again.
export function savedUnchanged(session) {
  const last = array(session.saved).at(-1);
  if (!last || !Number.isInteger(last.seq)) return false;
  return array(session.steps).every((entry) => !entry.chosen || entry.chosen.seq < last.seq);
}

// The project step is always done; the review is done while nothing was chosen since a save; the round has
// no answer here, so it stays pending.
function statusOf(session, step) {
  if (step === "project") return "done";
  if (step === "review") return savedUnchanged(session) ? "done" : "pending";
  return ANSWERED.includes(step) ? entryOf(session, step).status : "pending";
}

// The round step after a save with no choice since; otherwise the first step still to answer or to look at
// again, and the review once all six are done.
export function currentStep(session) {
  if (savedUnchanged(session)) return "round";
  return ANSWERED.find((step) => statusOf(session, step) !== "done") || "review";
}

// --- the draft ---------------------------------------------------------------------------------------

function summaryOf(ctx, step, answer) {
  const { t } = ctx;
  const a = answer || {};
  if (step === "question") return a.question || "";
  if (step === "crop") return a.crop || "";
  if (step === "treatments") return array(a.treatments).map((row) => row.name).join(t("common.listSep"));
  if (step === "measures") return t("guide.summary.measures", { n: array(a.variables).length });
  if (step === "analysis") return [textOr(t, "guide.methodName", a.method), a.target_effect].filter((part) => part !== null && part !== undefined).join(" · ");
  const count = a.layout === "tents" ? ["guide.scale.rounds", a.rounds] : ["guide.scale.blocks", a.blocks];
  return [textOr(t, "guide.layout", a.layout), `${t(count[0])} ${count[1]}`].filter(Boolean).join(" · ");
}

function draftRow(ctx, entry) {
  const mark = h("span", { class: ["pill", `pill-source-${entry.chosen.source}`], text: labelOr(ctx.t, "guide.source", entry.chosen.source) });
  const body = h("span", { class: "guide-draft-text", text: summaryOf(ctx, entry.step, entry.chosen.answer) });
  return h("li", { class: "guide-draft-row" }, h("strong", { text: ctx.t(`guide.step.${entry.step}`) }), body, mark);
}

function draftPanel(ctx, session) {
  const answered = array(session.steps).filter((entry) => entry.chosen && entry.status !== "pending");
  const body = answered.length ? h("ul", { class: "guide-draft-list" }, answered.map((entry) => draftRow(ctx, entry))) : note(ctx.t("guide.draft.empty"));
  return [h("h2", { text: ctx.t("guide.draft.title") }), body];
}

// --- the rail ----------------------------------------------------------------------------------------

function railItem(ctx, { session, step, index, shown, open }) {
  const status = statusOf(session, step);
  const title = h("span", { class: "guide-rail-title", text: ctx.t(`guide.step.${step}`) });
  const number = h("span", { class: "guide-rail-number", text: String(index) });
  const mark = status === "needs_review" ? h("span", { class: "guide-rail-status", text: ctx.t("guide.status.needs_review") }) : null;
  const clickable = (ANSWERED.includes(step) || step === "review") && status !== "pending";
  const inner = [number, h("span", { class: "guide-rail-text" }, title, mark)];
  const control = clickable ? h("button", { class: "guide-rail-button", attrs: { type: "button" }, on: { click: () => open(step) } }, inner) : h("span", { class: "guide-rail-button" }, inner);
  const attrs = { "aria-current": step === shown ? "step" : null };
  return h("li", { class: ["guide-rail-item", `guide-rail-${status}`], attrs }, control);
}

// --- the page ----------------------------------------------------------------------------------------

export async function render(ctx, { sessionId }) {
  const base = `/guide/sessions/${enc(sessionId)}`;
  ctx.setBreadcrumbs([{ label: ctx.t("nav.projects"), href: hrefFor("projects") }, { label: ctx.t("crumb.guide") }]);
  let session = await ctx.api.get(base);
  let viewing = null; // a step the person opened; null means the current one
  let drawn = 0;
  const rail = h("ol", { class: "guide-rail" });
  const stage = h("div", { class: "guide-stage" });
  const draft = h("aside", { class: "guide-draft" });
  const shown = () => viewing || currentStep(session);

  const drawSides = () => {
    const open = (step) => (ANSWERED.includes(step) ? openStep(step) : goTo(step));
    rail.replaceChildren(...RAIL.map((step, index) => railItem(ctx, { session, step, index, shown: shown(), open })));
    draft.replaceChildren(...draftPanel(ctx, session));
  };

  const showFailure = (error) => stage.replaceChildren(h("div", { class: "form-status form-status-error" }, errorParts(ctx, error)));

  async function drawStage() {
    const step = shown();
    const mine = ++drawn;
    if (step === "review" && savedUnchanged(session)) {
      stage.replaceChildren(section(ctx.t("guide.step.review"), savedReview(ctx, { saved: array(session.saved).at(-1), onOpenStep: goTo })));
      return;
    }
    if (step === "review") return drawReview(mine);
    if (step === "round") {
      const saved = array(session.saved).at(-1) || null;
      stage.replaceChildren(section(ctx.t("guide.step.round"), roundStep(ctx, { session, saved, onOpenStep: goTo })));
      return;
    }
    if (!ANSWERED.includes(step)) {
      stage.replaceChildren(section(ctx.t(`guide.step.${step}`), note(ctx.t("guide.later"))));
      return;
    }
    try {
      const options = await ctx.api.get(`${base}/steps/${step}`);
      if (mine === drawn) stage.replaceChildren(stepCard(ctx, { session, step, options, onChosen }));
    } catch (error) {
      if (mine === drawn) showFailure(error);
    }
  }

  // The review needs the project the protocol form takes, read the way the project page reads it.
  async function drawReview(mine) {
    try {
      const project = await ctx.api.get(`/projects/${enc(session.session.project_id)}`);
      const card = await reviewStep(ctx, { session, project, onSaved, onOpenStep: goTo });
      if (mine === drawn) stage.replaceChildren(section(ctx.t("guide.step.review"), card));
    } catch (error) {
      if (mine === drawn) showFailure(error);
    }
  }

  // The protocol is saved and recorded: the page takes the server's view and moves on to the round step.
  function onSaved(view) {
    if (Array.isArray(view && view.steps)) session = view;
    viewing = "round";
    drawSides();
    return drawStage();
  }

  // A step not answered yet is opened as it is; nothing is recorded.
  function goTo(step) {
    viewing = step;
    drawSides();
    return drawStage();
  }

  // A saved answer: the page takes the server's view; with `stay` the card stays and says what to look at.
  function onChosen(view, { stay = false } = {}) {
    const keep = stay ? shown() : null;
    session = view;
    viewing = keep;
    drawSides();
    if (!stay) drawStage();
  }

  // A finished step is opened again; the server records that, the answer given is shown ready to change.
  async function openStep(step) {
    try {
      const view = await ctx.api.post(`${base}/steps/${step}/reopen`, {}, { action: ctx.t(`guide.step.${step}`) });
      if (Array.isArray(view && view.steps)) session = view;
    } catch (error) {
      showFailure(error);
      return;
    }
    viewing = step;
    drawSides();
    await drawStage();
  }

  drawSides();
  await drawStage();
  const nav = h("nav", { class: "guide-nav", attrs: { "aria-label": ctx.t("guide.rail.label") } }, rail);
  const element = h("div", { class: "page guide" }, pageHead(ctx.t("guide.title"), ctx.t("guide.lead")), h("div", { class: "guide-layout" }, nav, stage, draft));
  const refresh = async () => {
    session = await ctx.api.get(base);
    drawSides();
    await drawStage();
  };
  return { element, refresh };
}
