// Administration (multi-user, administrators only): accounts, greenhouse locks with their history, forced release.
import { h } from "../ui/dom.js";
import { simpleForm } from "../ui/forms.js";
import { table } from "../ui/table.js";
import { afterWrite, confirmedButton, note, pageHead, section, timeText } from "../ui/section.js";

const ROLES = ["user", "admin"];
const EVENT_KEYS = { lock: "admin.event.lock", release: "admin.event.release", force_release: "admin.event.force" };

function roleText(ctx, role) {
  return ctx.t(role === "admin" ? "admin.role.admin" : "admin.role.user");
}

function disableButton(ctx, row) {
  if (row.disabled_at) return ctx.t("admin.disabled");
  const label = ctx.t("admin.disable");
  const run = async () => {
    await ctx.api.post("/admin/operators/disable", { name: row.name }, { action: label });
    afterWrite(ctx, ctx.t("admin.disabledNotice", { name: row.name }));
  };
  return confirmedButton(ctx, { label, title: ctx.t("admin.disableTitle", { name: row.name }), lines: [ctx.t("admin.disableLine")], run });
}

function accountsTable(ctx, operators) {
  const columns = [
    { label: ctx.t("admin.name"), cell: (row) => row.name },
    { label: ctx.t("admin.role"), cell: (row) => roleText(ctx, row.role) },
    { label: ctx.t("admin.unfinished"), cell: (row) => String(row.unfinished_stages ?? 0) },
    { label: ctx.t("col.created"), cell: (row) => timeText(ctx, row.created_at) },
    { label: ctx.t("admin.state"), cell: (row) => disableButton(ctx, row) },
  ];
  return table(columns, operators, { label: ctx.t("admin.accounts") });
}

function addForm(ctx) {
  const submitLabel = ctx.t("admin.add");
  const fields = [
    { name: "name", label: ctx.t("admin.name"), type: "text", required: true },
    { name: "secret", label: ctx.t("admin.secret"), type: "password", required: true },
    { name: "role", label: ctx.t("admin.role"), type: "select", required: true, options: ROLES.map((value) => ({ value, label: roleText(ctx, value) })) },
  ];
  const onSubmit = async (values) => {
    await ctx.api.post("/admin/operators", values, { action: submitLabel });
    afterWrite(ctx, ctx.t("admin.added", { name: values.name }));
  };
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: "admin-add", ctx });
}

function secretForm(ctx) {
  const submitLabel = ctx.t("admin.resetSecret");
  const fields = [
    { name: "name", label: ctx.t("admin.name"), type: "text", required: true },
    { name: "secret", label: ctx.t("admin.secret"), type: "password", required: true },
  ];
  const onSubmit = async (values) => {
    await ctx.api.post("/admin/operators/secret", values, { action: submitLabel });
    afterWrite(ctx, ctx.t("admin.secretReset", { name: values.name }));
  };
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: "admin-secret", ctx });
}

function forceButton(ctx, row) {
  if (!row.holder) return "—";
  const submitLabel = ctx.t("admin.forceRelease");
  const fields = [{ name: "note", label: ctx.t("admin.reason"), type: "text", required: true }];
  const onSubmit = async ({ note: reason }) => {
    await ctx.api.post(`/admin/greenhouses/${encodeURIComponent(row.id)}/release`, { note: reason }, { action: submitLabel });
    afterWrite(ctx, ctx.t("admin.forced", { name: row.name }));
  };
  return simpleForm({ fields, submitLabel, onSubmit, draftKey: `admin-release-${row.id}`, ctx });
}

function locksTable(ctx, locks) {
  const columns = [
    { label: ctx.t("greenhouses.name"), cell: (row) => row.name },
    { label: ctx.t("greenhouses.holder"), cell: (row) => row.holder || "—" },
    { label: ctx.t("greenhouses.since"), cell: (row) => (row.locked_at ? timeText(ctx, row.locked_at) : "—") },
    { label: ctx.t("admin.forceRelease"), cell: (row) => forceButton(ctx, row) },
  ];
  return table(columns, locks, { label: ctx.t("admin.locks") });
}

function eventsTable(ctx, events) {
  if (!events.length) return note(ctx.t("admin.noEvents"));
  const columns = [
    { label: ctx.t("admin.time"), cell: (row) => timeText(ctx, row.at) },
    { label: ctx.t("greenhouses.name"), cell: (row) => row.greenhouse_id },
    { label: ctx.t("admin.eventAction"), cell: (row) => ctx.t(EVENT_KEYS[row.action] || "common.unknown") },
    { label: ctx.t("admin.by"), cell: (row) => row.actor },
    { label: ctx.t("admin.reason"), cell: (row) => row.note || "—" },
  ];
  return table(columns, events, { label: ctx.t("admin.events") });
}

export async function render(ctx) {
  const [accounts, locks] = await Promise.all([ctx.api.get("/admin/operators"), ctx.api.get("/admin/locks")]);
  const operators = Array.isArray(accounts?.operators) ? accounts.operators : [];
  const element = h(
    "div",
    { class: "page admin" },
    pageHead(ctx.t("nav.admin"), ctx.t("admin.lead")),
    section(ctx.t("admin.accounts"), accountsTable(ctx, operators), addForm(ctx), secretForm(ctx)),
    section(ctx.t("admin.locks"), locksTable(ctx, locks?.locks || [])),
    section(ctx.t("admin.events"), eventsTable(ctx, locks?.events || [])),
  );
  return { element };
}
