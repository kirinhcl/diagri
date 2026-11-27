// The two ways into the guide: a new project made for it (projects list) and a guide for an existing project
// (project page). Both end on the guide page of the session the server made.
import { ApiError } from "../api.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { simpleForm } from "../ui/forms.js";
import { errorBox, showErrors } from "../ui/section.js";

// The plan's default budget; the person can change both numbers before sending.
const DEFAULT_MAX_CALLS = 100;
const DEFAULT_MAX_COST = 10;

const startSession = (ctx, projectId, action) => ctx.api.post("/guide/sessions", { project_id: projectId, lang: ctx.lang }, { action });
const openGuide = (ctx, made) => ctx.navigate(hrefFor("guide", { sessionId: made.session_id }));

// A deployment without a model has no budget route (404): the budget is skipped and the person is told.
async function setBudget(ctx, projectId, values, action) {
  try {
    await ctx.api.post(`/projects/${encodeURIComponent(projectId)}/budget`, values, { action });
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error;
    ctx.notify(ctx.t("guide.entry.noBudget"), "info");
  }
}

// Project, budget and guide, in that order. A project already made by an earlier try of this form is reused,
// so a refused later step never leaves a second project behind.
export function guidedNewForm(ctx) {
  const submitLabel = ctx.t("guide.entry.create");
  let projectId = null;
  const onSubmit = async ({ name, max_calls: maxCalls, max_cost: maxCost }) => {
    if (!projectId) projectId = (await ctx.api.post("/projects", { name }, { action: submitLabel })).project_id;
    await setBudget(ctx, projectId, { max_calls: maxCalls, max_cost: maxCost }, submitLabel);
    openGuide(ctx, await startSession(ctx, projectId, submitLabel));
  };
  const fields = [
    { name: "name", label: ctx.t("projects.newName"), type: "text", required: true },
    { name: "max_calls", label: ctx.t("project.budget.maxCalls"), type: "number", step: 1, min: 0, required: true, value: DEFAULT_MAX_CALLS },
    { name: "max_cost", label: ctx.t("project.budget.maxCost"), type: "number", min: 0, required: true, value: DEFAULT_MAX_COST },
  ];
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: "project:new-guided", ctx });
}

export function guideButton(ctx, project) {
  const box = errorBox();
  const label = ctx.t("guide.entry.start");
  const onClick = async () => {
    try {
      box.hidden = true;
      openGuide(ctx, await startSession(ctx, project.project_id, label));
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      showErrors(box, error, ctx);
    }
  };
  const button = h("button", { class: ["button", "guide-start"], attrs: { type: "button" }, text: label, on: { click: onClick } });
  return h("div", { class: "guide-entry" }, button, box);
}
