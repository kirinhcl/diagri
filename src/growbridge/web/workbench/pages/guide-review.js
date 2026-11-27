// Step 7 of the guide: what is missing or wrong, then the composed protocol in the normal protocol form so every value
// can be seen and changed. The form saves through POST /protocols as the project page does; the guide never saves on
// its own. After the save the guide is told which protocol and version were saved.
import { ApiError } from "../api.js";
import { saveDraft } from "../drafts.js";
import { protocolFormDraft } from "../guide-draft.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { simpleForm } from "../ui/forms.js";
import { protocolName } from "../ui/names.js";
import { errorBox, note, section, showErrors, techDetails } from "../ui/section.js";
import { protocolForm } from "./protocol-form.js";
import { findingsList } from "./stage-actions.js";

const array = (value) => (Array.isArray(value) ? value : []);
const enc = encodeURIComponent;

// When the project already holds a protocol with the review's id, the form saves its next version.
const saveAsOf = (project, review) => (array(project.protocols).some((row) => row.protocol_id === review.protocol_id) ? review.protocol_id : "");

function missingSteps(ctx, review, onOpenStep) {
  const steps = array(review.missing);
  if (steps.length === 0) return null;
  const button = (step) => h("li", {}, h("button", { class: ["button", "guide-missing-step"], attrs: { type: "button" }, text: ctx.t(`guide.step.${step}`), on: { click: () => onOpenStep(step) } }));
  return section(ctx.t("guide.review.missing"), h("ul", { class: "guide-review-list" }, steps.map(button)));
}

function problemsBlock(ctx, review) {
  const blocking = array(review.design).filter((finding) => finding && finding.blocking === true);
  const problems = array(review.problems);
  if (problems.length + blocking.length === 0) return null;
  const list = problems.length ? h("ul", { class: "guide-review-list" }, problems.map((text) => h("li", { text }))) : null;
  return section(ctx.t("guide.review.problems"), list, blocking.length ? findingsList(ctx, blocking) : null);
}

function hintsBlock(ctx, review) {
  const hints = array(review.design).filter((finding) => finding && finding.blocking !== true);
  return hints.length ? section(ctx.t("guide.review.hints"), findingsList(ctx, hints)) : null;
}

// The script hash an earlier version carried has no field in the form. It is shown read-only with a box that is
// ticked at first; it goes back on the protocol only when the box is ticked and the protocol saved is the same one
// the review was made for (a different or new id never inherits it).
function hashBlock(ctx, hash) {
  if (!hash) return { element: null, keep: () => false };
  const box = h("input", { class: "input-check", attrs: { type: "checkbox", name: "keep_script_hash", checked: true } });
  const label = h("label", { class: "guide-choice" }, box, h("span", { text: ctx.t("guide.review.keepHash") }));
  const element = h("div", { class: "guide-review-hash" }, note(ctx.t("guide.review.hash")), techDetails(ctx.t, [[ctx.t("analysis.sha"), hash]]), label);
  return { element, keep: () => box.checked };
}

const withHash = (protocol, hash) => ({ ...protocol, analysis: { ...protocol.analysis, script_sha256: hash } });

// Tells the guide what was saved. A failure replaces the form (it would save one more version) with a note saying
// what is saved and a retry; the error stays beside it.
function recorder(ctx, { base, onSaved, box, holder }) {
  const record = async (body) => {
    try {
      const view = await ctx.api.post(`${base}/saved`, body, { action: ctx.t("guide.step.review") });
      await onSaved(view);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      showErrors(box, error, ctx);
      const saved = protocolName(ctx.t, body.protocol_id, body.version);
      const retry = h("button", { class: ["button", "guide-retry"], attrs: { type: "button" }, text: ctx.t("guide.review.retry"), on: { click: () => record(body) } });
      holder.replaceChildren(note(ctx.t("guide.review.notRecorded", { protocol: saved })), retry);
    }
  };
  return record;
}

export async function reviewStep(ctx, { session, project, onSaved, onOpenStep = () => {} }) {
  const base = `/guide/sessions/${enc(session.session.session_id)}`;
  const review = await ctx.api.get(`${base}/review`);
  const box = errorBox();
  const holder = h("div", { class: "guide-review-form" });
  const record = recorder(ctx, { base, onSaved, box, holder });
  const hash = review.protocol && review.protocol.analysis ? review.protocol.analysis.script_sha256 : null;
  const kept = hashBlock(ctx, hash);

  const onSubmit = async ({ protocol }) => {
    const sent = kept.keep() && protocol.id === review.protocol_id ? withHash(protocol, hash) : protocol;
    const made = await ctx.api.post("/protocols", { protocol: sent }, { action: ctx.t("project.protocols.save") });
    const id = (made && made.protocol_id) ?? sent.id;
    const version = (made && made.version) ?? sent.version;
    ctx.notify(ctx.t("project.protocols.saved", { protocol: protocolName(ctx.t, id, version) }), "ok");
    box.hidden = true;
    await record({ protocol_id: id, version });
  };

  if (!review.protocol) holder.append(note(ctx.t("guide.review.noProtocol")));
  else {
    const saveAs = saveAsOf(project, review);
    saveDraft(`protocol:${project.project_id}-form`, protocolFormDraft(review.protocol, { saveAs }));
    holder.append(protocolForm(ctx, { project, onSubmit, protocolId: saveAs }));
  }
  const lead = review.protocol ? note(ctx.t("guide.review.lead")) : null;
  return h("div", { class: "guide-review" }, missingSteps(ctx, review, onOpenStep), problemsBlock(ctx, review), hintsBlock(ctx, review), lead, kept.element, holder, box);
}

// The review after a save with nothing chosen since: what was saved and the way on to step 8. There is no form,
// so the same protocol is never offered again as one more version.
export function savedReview(ctx, { saved, onOpenStep = () => {} }) {
  const name = protocolName(ctx.t, saved.protocol_id, saved.version);
  const next = h("button", { class: ["button", "guide-to-round"], attrs: { type: "button" }, text: ctx.t("guide.step.round"), on: { click: () => onOpenStep("round") } });
  return h("div", { class: "guide-review" }, note(ctx.t("guide.review.savedUnchanged", { protocol: name })), next);
}

// --- step 8: the round and the goal (both optional) ---------------------------------------------------

const link = (href, text) => h("a", { class: "text-link", attrs: { href }, text });

// The research question of the session's question step, the first suggestion for the goal.
function questionOf(session) {
  const entry = array(session.steps).find((item) => item.step === "question");
  const answer = entry && entry.chosen && entry.chosen.answer;
  return answer && typeof answer.question === "string" ? answer.question : "";
}

// The goal goes to the round just made, in the page language; afterwards the round page is one link away.
function goalForm(ctx, { projectId, roundId, question, holder }) {
  const fields = [{ name: "goal", label: ctx.t("guide.round.goal"), type: "textarea", required: true, value: question }];
  const onSubmit = async ({ goal }) => {
    await ctx.api.post("/goals", { project_id: projectId, round_id: roundId, goal, language: ctx.lang }, { action: ctx.t("guide.round.send") });
    holder.replaceChildren(note(ctx.t("guide.round.done")), link(hrefFor("round", { roundId }), ctx.t("guide.round.open")));
  };
  return simpleForm({ fields, submitLabel: ctx.t("guide.round.send"), onSubmit, draftKey: `guide-goal:${roundId}`, ctx });
}

export function roundStep(ctx, { session, saved, onOpenStep = () => {} }) {
  if (!saved) {
    const open = () => onOpenStep("review");
    const back = h("button", { class: ["button", "guide-back-review"], attrs: { type: "button" }, text: ctx.t("guide.step.review"), on: { click: open } });
    return h("div", { class: "guide-round" }, note(ctx.t("guide.round.noSave")), back);
  }
  const projectId = session.session.project_id;
  const box = errorBox();
  const holder = h("div", { class: "guide-round-body" });
  const make = h("button", { class: ["button", "button-primary", "guide-make-round"], attrs: { type: "button" }, text: ctx.t("guide.round.make") });
  const onMake = async () => {
    make.disabled = true;
    try {
      const made = await ctx.api.post("/rounds", { project_id: projectId, protocol_id: saved.protocol_id }, { action: ctx.t("guide.round.make") });
      box.hidden = true;
      const form = goalForm(ctx, { projectId, roundId: made.round_id, question: questionOf(session), holder });
      holder.replaceChildren(note(ctx.t("guide.round.made")), form, link(hrefFor("round", { roundId: made.round_id }), ctx.t("guide.round.skipGoal")));
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      showErrors(box, error, ctx);
      make.disabled = false;
    }
  };
  make.addEventListener("click", onMake);
  const name = protocolName(ctx.t, saved.protocol_id, saved.version);
  holder.append(note(ctx.t("guide.round.lead", { protocol: name })), make, link(hrefFor("project", { projectId }), ctx.t("guide.round.skip")));
  return h("div", { class: "guide-round" }, holder, box);
}
