// The projects list, newest first, with a form to start a new project.
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { simpleForm } from "../ui/forms.js";
import { displayName, nameDetails } from "../ui/names.js";
import { note, pageHead, section, techDetails, timeText } from "../ui/section.js";
import { statePill } from "../ui/status.js";
import { table } from "../ui/table.js";

function latestRound(ctx, project) {
  const latest = project.latest_round;
  if (!latest) return "—";
  const link = h("a", { class: "text-link", attrs: { href: hrefFor("round", { roundId: latest.round_id }) }, text: displayName(ctx, "round", latest) });
  return h("span", { class: "cell-stack" }, link, statePill(ctx.t, latest.state));
}

// The project by name; its id and its latest round's id in the row's details.
function nameCell(ctx, project) {
  const href = hrefFor("project", { projectId: project.project_id });
  const link = h("a", { class: "text-link", attrs: { href }, text: displayName(ctx, "project", project) });
  const ids = [...nameDetails(project, ctx.t), ...nameDetails({ round_id: project.latest_round?.round_id }, ctx.t)];
  return h("span", { class: "cell-stack" }, link, techDetails(ctx.t, ids));
}

function columns(ctx) {
  return [
    { label: ctx.t("projects.name"), cell: (project) => nameCell(ctx, project) },
    { label: ctx.t("projects.rounds"), cell: (project) => String(project.round_count) },
    { label: ctx.t("projects.latest"), cell: (project) => latestRound(ctx, project) },
    { label: ctx.t("col.created"), cell: (project) => timeText(ctx, project.created_at) },
  ];
}

function createForm(ctx) {
  const onSubmit = async ({ name }) => {
    await ctx.api.post("/projects", { name }, { action: ctx.t("projects.create") });
    ctx.notify(ctx.t("projects.madeNotice", { name }), "ok");
    ctx.reload();
  };
  const fields = [{ name: "name", label: ctx.t("projects.newName"), type: "text", required: true }];
  return simpleForm({ fields, submitLabel: ctx.t("projects.create"), onSubmit, draftKey: "project:new", ctx });
}

export async function render(ctx) {
  const data = await ctx.api.get("/projects");
  const projects = data && Array.isArray(data.projects) ? data.projects : [];
  const list = projects.length
    ? table(columns(ctx), projects, { label: ctx.t("nav.projects") })
    : note(ctx.t("projects.empty"));
  const element = h(
    "div",
    { class: "page projects" },
    pageHead(ctx.t("nav.projects"), ctx.t("projects.lead")),
    section(ctx.t("projects.list"), list),
    section(ctx.t("projects.new"), createForm(ctx)),
  );
  return { element };
}
