// The projects list, newest first, with a form to start a new project.
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { simpleForm } from "../ui/forms.js";
import { note, pageHead, section, timeText } from "../ui/section.js";
import { statePill } from "../ui/status.js";
import { table } from "../ui/table.js";

function latestRound(ctx, project) {
  const latest = project.latest_round;
  if (!latest) return "—";
  const link = h("a", { class: "text-link", attrs: { href: hrefFor("round", { roundId: latest.round_id }) }, text: latest.round_id });
  return h("span", { class: "cell-stack" }, link, statePill(ctx.t, latest.state));
}

function columns(ctx) {
  const link = (project) =>
    h("a", { class: "text-link", attrs: { href: hrefFor("project", { projectId: project.project_id }) }, text: project.name });
  return [
    { label: ctx.t("projects.name"), cell: link },
    { label: ctx.t("col.id"), cell: (project) => h("code", { text: project.project_id }) },
    { label: ctx.t("projects.rounds"), cell: (project) => String(project.round_count) },
    { label: ctx.t("projects.latest"), cell: (project) => latestRound(ctx, project) },
    { label: ctx.t("col.created"), cell: (project) => timeText(ctx, project.created_at) },
  ];
}

function createForm(ctx) {
  const onSubmit = async ({ name }) => {
    const made = await ctx.api.post("/projects", { name }, { action: ctx.t("projects.create") });
    ctx.notify(ctx.t("projects.madeNotice", { id: made.project_id }), "ok");
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
