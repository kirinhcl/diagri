// Step 7 of the guide: what is missing or wrong, then the composed protocol in the normal protocol form so every value
// can be seen and changed. The form saves through POST /protocols as the project page does; the guide never saves on
// its own. After the save the guide is told which protocol and version were saved.
import { ApiError } from "../api.js";
import { saveDraft } from "../drafts.js";
import { protocolFormDraft } from "../guide-draft.js";
import { h } from "../ui/dom.js";
import { protocolName } from "../ui/names.js";
import { errorBox, note, section, showErrors } from "../ui/section.js";
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

// The script hash an earlier version carried is not a field of the form, so the form would drop it; it is put back.
function withCarriedHash(protocol, hash) {
  return hash ? { ...protocol, analysis: { ...protocol.analysis, script_sha256: hash } } : protocol;
}

// Tells the guide what was saved. A failure stays on the page with a retry: the protocol is already saved, so the
// form is not offered again (it would save one more version).
function recorder(ctx, { base, onSaved, box }) {
  const record = async (body) => {
    try {
      const view = await ctx.api.post(`${base}/saved`, body, { action: ctx.t("guide.step.review") });
      await onSaved(view);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      showErrors(box, error, ctx);
      const retry = h("button", { class: ["button", "guide-retry"], attrs: { type: "button" }, text: ctx.t("guide.review.retry"), on: { click: () => record(body) } });
      box.append(h("p", { text: ctx.t("guide.review.notRecorded") }), retry);
    }
  };
  return record;
}

export async function reviewStep(ctx, { session, project, onSaved, onOpenStep = () => {} }) {
  const base = `/guide/sessions/${enc(session.session.session_id)}`;
  const review = await ctx.api.get(`${base}/review`);
  const box = errorBox();
  const record = recorder(ctx, { base, onSaved, box });
  const hash = review.protocol && review.protocol.analysis ? review.protocol.analysis.script_sha256 : null;

  const onSubmit = async ({ protocol }) => {
    const sent = withCarriedHash(protocol, hash);
    const made = await ctx.api.post("/protocols", { protocol: sent }, { action: ctx.t("project.protocols.save") });
    const id = (made && made.protocol_id) ?? sent.id;
    const version = (made && made.version) ?? sent.version;
    ctx.notify(ctx.t("project.protocols.saved", { protocol: protocolName(ctx.t, id, version) }), "ok");
    box.hidden = true;
    await record({ protocol_id: id, version });
  };

  let form = note(ctx.t("guide.review.noProtocol"));
  if (review.protocol) {
    const saveAs = saveAsOf(project, review);
    saveDraft(`protocol:${project.project_id}-form`, protocolFormDraft(review.protocol, { saveAs }));
    form = protocolForm(ctx, { project, onSubmit, protocolId: saveAs });
  }
  const lead = review.protocol ? note(ctx.t("guide.review.lead")) : null;
  return h("div", { class: "guide-review" }, missingSteps(ctx, review, onOpenStep), problemsBlock(ctx, review), hintsBlock(ctx, review), lead, form, box);
}
