// An alert as sentences: what happened, what to do next, a link to its stage or project. The
// server's own words, its code, key and ids stay in the technical details. Both the alerts page
// and the inbox read alerts through here.
import { hasLabel, labelOr } from "../i18n.js";
import { messageParts } from "../messages.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { techDetails } from "../ui/section.js";
import { detailLines } from "./stage-history.js";

const isText = (value) => typeof value === "string" && value !== "";
const plain = (value) => (value !== null && typeof value === "object" && !Array.isArray(value) ? value : {});

// The alert's fields as the server sends them (the inbox names them differently); no code means a row stored before codes.
export function alertFields(source) {
  return {
    kind: source.kind ?? source.alert_kind,
    key: source.key,
    message: source.message,
    code: isText(source.code) ? source.code : null,
    params: plain(source.params),
  };
}

// The sentences of an alert and the entries for its single technical-details fold.
export function alertSentences(ctx, source, kindLabel) {
  const a = alertFields(source);
  const { t } = ctx;
  const known = hasLabel(t, "alert.kind", a.kind);
  const kindEntry = known ? [kindLabel, `${labelOr(t, "alert.kind", a.kind)} (${a.kind})`] : [t("tech.code"), a.kind]; // an unknown kind shows only its code
  const own = [kindEntry, [t("alerts.tech.key"), a.key], [t("tech.serverMessage"), a.message]];
  if (a.code === null) {
    return { legacy: true, known: false, text: labelOr(t, "alert.kind", a.kind), action: null, lines: [], note: null, entries: own, fields: a };
  }
  const parts = messageParts(ctx, "alert", a.code, a.params);
  const waiting = a.code === "stage_waiting" && parts.known ? detailLines(ctx, { type: "transition", event: a.params.event, detail: a.params.detail }) : { lines: [], raw: [] };
  return { legacy: false, known: parts.known, text: parts.text, action: parts.action, lines: waiting.lines, note: auditNote(a), entries: [...own, ...parts.details, ...waiting.raw], fields: a };
}

// The auditor's own words (model-written): its summary and evidence, quoted.
function auditNote(a) {
  if (a.code !== "audit_finding") return null;
  const { summary, evidence } = a.params;
  const items = (Array.isArray(evidence) ? evidence : []).filter(isText).map((line) => h("li", { text: line }));
  if (!isText(summary) && !items.length) return null;
  return h("blockquote", { class: "model-note" }, isText(summary) ? h("p", { text: summary }) : null, items.length ? h("ul", {}, items) : null);
}

// Links come from the params only, never from the alert's key.
export function alertLinks(ctx, params) {
  const link = (page, key, id, label) => (isText(id) ? [h("a", { class: "text-link", attrs: { href: hrefFor(page, { [key]: id }) }, text: ctx.t(label) })] : []);
  const links = [...link("stage", "stageId", params.stage_id, "alerts.openStage"), ...link("project", "projectId", params.project_id, "alerts.openProject")];
  return links.length ? h("p", { class: "message-links" }, links) : null;
}

// The message column of the alerts page.
export function alertCell(ctx, source) {
  const s = alertSentences(ctx, source, ctx.t("alerts.kind"));
  const text = h("p", { class: "message-text", text: s.text });
  const legacy = s.legacy ? h("p", { class: "message-action", text: ctx.t("alerts.legacy") }) : null;
  const action = s.action ? h("p", { class: "message-action", text: s.action }) : null;
  const lines = s.lines.map((line) => h("p", { class: "message-detail", text: line }));
  return h("div", { class: "message" }, text, lines, s.note, legacy, action, alertLinks(ctx, s.fields.params), techDetails(ctx.t, s.entries));
}
