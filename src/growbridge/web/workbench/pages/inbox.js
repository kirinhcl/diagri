// "My inbox": everything that waits for a person, grouped by kind and refreshed every 15 seconds.
import { singleFlight } from "../api.js";
import { formatDuration } from "../format.js";
import { labelOr } from "../i18n.js";
import { hrefFor } from "../router.js";
import { clear, h } from "../ui/dom.js";
import { deviceName, displayName, nameDetails, roleLabel } from "../ui/names.js";
import { errorParts, foldedText, replaceParts, techDetails, timeText } from "../ui/section.js";
import { severityPill, statePill } from "../ui/status.js";

const POLL_SECONDS = 15;
// Most urgent first: on-site checks and alerts, then decisions waiting on a person, then the rest.
export const KIND_ORDER = [
  "stage_recovery",
  "alert",
  "stage_review",
  "stage_manual",
  "stage_paused",
  "round_choice",
  "compute_stuck",
  "task",
];
const STAGE_KINDS = new Set(["stage_review", "stage_manual", "stage_recovery", "stage_paused"]);
const ONSITE_KINDS = new Set(["stage_recovery", "alert"]);

export function inboxTarget(item) {
  if (STAGE_KINDS.has(item.kind)) return hrefFor("stage", { stageId: item.id });
  if (item.kind === "round_choice") return hrefFor("round", { roundId: item.id });
  if (item.kind === "alert") return hrefFor("alerts", { focus: item.id });
  if (item.kind === "compute_stuck") return hrefFor("compute");
  if (item.kind === "task") {
    return item.project_id ? hrefFor("project", { projectId: item.project_id }) : hrefFor("projects");
  }
  return null;
}

// The server's answer, with anything malformed dropped rather than trusted.
export function normalizeInbox(data) {
  const usable = (item) => item && typeof item.kind === "string" && item.id !== null && item.id !== undefined;
  const items = data && Array.isArray(data.items) ? data.items.filter(usable) : [];
  const raw = data && data.truncated && typeof data.truncated === "object" ? data.truncated : {};
  const truncated = Object.fromEntries(Object.entries(raw).filter(([, count]) => Number.isInteger(count) && count > 0));
  return { items, truncated };
}

export function inboxCounts(data) {
  const { items, truncated } = normalizeInbox(data);
  const hidden = Object.values(truncated).reduce((sum, count) => sum + count, 0);
  const alerts = items.filter((item) => item.kind === "alert").length + (truncated.alert || 0);
  return { inbox: items.length + hidden, alerts };
}

// Kinds in KIND_ORDER first, then any kind this console does not know yet, in arrival order.
export function groupByKind({ items, truncated }) {
  const kinds = [...new Set([...KIND_ORDER, ...items.map((item) => item.kind), ...Object.keys(truncated)])];
  return kinds
    .map((kind) => ({ kind, items: items.filter((item) => item.kind === kind), hidden: truncated[kind] || 0 }))
    .filter((group) => group.items.length > 0 || group.hidden > 0);
}

// The text for key, or null when one of its values is missing.
function say(t, key, vars) {
  const present = Object.values(vars).every((value) => value !== undefined && value !== null && value !== "");
  return present ? t(key, vars) : null;
}

// Project and round by name; a round choice is about one round, so it says the round in its title.
function where(ctx, item) {
  const project = displayName(ctx, "project", item);
  const round = item.kind === "round_choice" ? null : displayName(ctx, "round", item);
  return [ctx.t("inbox.project", { name: project }), round];
}

export const DESCRIBERS = {
  stage: (ctx, item, d) => {
    const stage = displayName(ctx, "stage", item);
    const review = item.kind === "stage_review";
    const title = review
      ? ctx.t("inbox.title.review", { project: displayName(ctx, "project", item), round: displayName(ctx, "round", item), stage })
      : ctx.t("inbox.title.stage", { stage, state: labelOr(ctx.t, "state", d.state) });
    return {
      title,
      pill: statePill(ctx.t, d.state),
      meta: [say(ctx.t, "inbox.device", { device: deviceName(ctx.t, d.device_id) }), ...(review ? [] : where(ctx, item))],
    };
  },
  round_choice: (ctx, item, d) => ({
    title: ctx.t("inbox.title.choice", { project: displayName(ctx, "project", item), round: displayName(ctx, "round", item) }),
    pill: statePill(ctx.t, "awaiting_choice"),
    lines: [
      d.awaiting_choice ? ctx.t("inbox.roundChoice") : null,
      d.since_from === "round_created" ? ctx.t("inbox.sinceRoundCreated") : null,
    ],
    meta: [],
  }),
  alert: (ctx, item, d) => ({
    title: foldedText(ctx, d.message || ""),
    plain: d.message || "",
    pill: severityPill(ctx.t, d.severity),
    meta: [
      labelOr(ctx.t, "alert.kind", d.alert_kind),
      say(ctx.t, "inbox.alertCount", { count: d.count }),
      d.last_at ? ctx.t("inbox.lastAt", { time: timeText(ctx, d.last_at) }) : null,
    ],
  }),
  compute_stuck: (ctx, item, d) => ({
    title: ctx.t("inbox.title.stuck", { phase: labelOr(ctx.t, "state", d.phase) }),
    pill: statePill(ctx.t, d.phase),
    lines: [d.reason],
    meta: [],
  }),
  task: (ctx, item, d) => ({
    title: d.question ? foldedText(ctx, d.question) : displayName(ctx, "researchTask", d),
    plain: d.question || "",
    pill: statePill(ctx.t, d.state),
    meta: [d.owner_role ? ctx.t("inbox.owner", { role: roleLabel(ctx.t, d.owner_role) }) : null, ...where(ctx, item)],
  }),
};

export function describe(ctx, item) {
  const detail = item.detail && typeof item.detail === "object" ? item.detail : {};
  const kind = STAGE_KINDS.has(item.kind) ? "stage" : item.kind;
  const fallback = () => ({ title: labelOr(ctx.t, "inbox.kind", item.kind), meta: where(ctx, item) });
  const describer = Object.hasOwn(DESCRIBERS, kind) ? DESCRIBERS[kind] : fallback;
  return { pill: null, lines: [], meta: [], ...describer(ctx, item, detail) };
}

// What an item's detail carries that only its technical details show: the stopped stage of a round
// choice, the device of a stage, the raw alert code.
function detailEntries(ctx, item, d) {
  if (item.kind === "round_choice") return [[ctx.t("tech.id.stage_id"), d.awaiting_choice]];
  if (item.kind === "alert") return [[ctx.t("inbox.tech.alertKind"), d.alert_kind]];
  return STAGE_KINDS.has(item.kind) ? [[ctx.t("stage.review.device"), d.device_id]] : [];
}

// The item's own ids and detailEntries, for its technical details.
function itemDetails(ctx, item) {
  const d = item.detail && typeof item.detail === "object" ? item.detail : {};
  const own = { stage: "stage_id", round_choice: "round_id", compute_stuck: "attempt_id", task: "task_id" };
  const key = STAGE_KINDS.has(item.kind) ? own.stage : own[item.kind];
  const row = key ? { ...item, id: undefined, [key]: item.id } : item;
  if (item.kind === "compute_stuck") row.task_id = d.task_id;
  return techDetails(ctx.t, [...nameDetails(row, ctx.t), ...detailEntries(ctx, item, d)]);
}

// "Waiting 3 h 20 min", or the full time when the clock says the item is from the future.
function waitingText(ctx, since) {
  const age = (ctx.now ?? Date.now() / 1000) - since;
  if (typeof since !== "number" || !(age >= 0)) return timeText(ctx, since);
  return ctx.t("inbox.waiting", { duration: formatDuration(ctx.t, age) });
}

const LABEL_CHARS = 80;
const shortTitle = (text) => {
  const chars = [...String(text).trim().replace(/\s+/g, " ")];
  return chars.length > LABEL_CHARS ? `${chars.slice(0, LABEL_CHARS).join("")}…` : chars.join("");
};

// A folded title holds its own toggle, so it cannot sit inside a link: the row then has an open link.
function itemView(ctx, item) {
  const { title, plain, pill, lines, meta } = describe(ctx, item);
  const href = inboxTarget(item);
  const folded = typeof title !== "string";
  const main = h(
    "div",
    { class: "inbox-main" },
    h("p", { class: "inbox-title", text: folded ? undefined : title }, folded ? title : null),
    lines.filter(Boolean).map((line) => h("p", { class: "inbox-text", text: line })),
    h("p", { class: "inbox-meta" }, meta.filter(Boolean).map((part) => h("span", { text: part }))),
  );
  const open = href && folded ? h("a", { class: "inbox-open", attrs: { href, "aria-label": `${ctx.t("inbox.open")}: ${shortTitle(plain)}` }, text: ctx.t("inbox.open") }) : null;
  const time = h("span", { class: "inbox-time", text: waitingText(ctx, item.since), attrs: { title: timeText(ctx, item.since) } });
  const side = h("div", { class: "inbox-side" }, pill, time, open);
  const key = `${item.kind}:${item.id}`;
  const linked = href && !folded;
  const row = linked
    ? h("a", { class: "inbox-item", attrs: { href } }, main, side)
    : h("div", { class: "inbox-item" }, main, side);
  return h("li", { attrs: { "data-key": key } }, row, h("div", { class: "inbox-tech" }, itemDetails(ctx, item)));
}

const MORE_PAGES = { alert: "alerts", compute_stuck: "compute" };

// "N more, see <page>": a link to the full list.
function moreView(ctx, group) {
  const page = MORE_PAGES[group.kind] || "projects";
  const link = h("a", { attrs: { href: hrefFor(page) }, text: ctx.t(`nav.${page}`) });
  const [before, after] = ctx.t("inbox.more", { count: group.hidden, page: "\u0000" }).split("\u0000");
  return h("p", { class: "inbox-more" }, before, link, after);
}

export function groupView(ctx, group) {
  const headingId = `inbox-group-${group.kind}`;
  const tone = ONSITE_KINDS.has(group.kind) ? "tone-onsite" : "tone-waiting";
  const count = group.items.length + group.hidden;
  return h(
    "section",
    { class: ["inbox-group", tone], attrs: { "aria-labelledby": headingId } },
    h(
      "header",
      { class: "inbox-group-head" },
      h("h2", { attrs: { id: headingId }, text: labelOr(ctx.t, "inbox.kind", group.kind) }),
      h("span", { class: "inbox-group-count", text: String(count) }),
    ),
    h("ul", { class: "inbox-list" }, group.items.map((item) => itemView(ctx, item))),
    group.hidden > 0 ? moreView(ctx, group) : null,
  );
}

function emptyView(ctx) {
  return h("div", { class: "inbox-empty" }, h("p", { text: ctx.t("inbox.empty") }));
}

// Every element under node (children only, so it works in any DOM).
const descendants = (node) => (node.children ? [...node.children].flatMap((child) => [child, ...descendants(child)]) : []);
const keyedItems = (list) => descendants(list).filter((el) => el.getAttribute("data-key") !== null);
const FOCUSABLE = new Set(["a", "summary", "button"]);
const focusables = (item) => descendants(item).filter((el) => FOCUSABLE.has(el.localName));
const folds = (item) => descendants(item).filter((el) => el.localName === "details");

// Where keyboard focus is and which folds are open, as item key + position inside the item.
function remember(list) {
  const items = keyedItems(list);
  const active = typeof document !== "undefined" ? document.activeElement : null;
  const holder = items.find((item) => item === active || item.contains(active));
  const focus = holder ? { key: holder.getAttribute("data-key"), index: focusables(holder).indexOf(active) } : null;
  const open = items.flatMap((item) => folds(item).flatMap((fold, i) => (fold.hasAttribute("open") ? [`${item.getAttribute("data-key")}#${i}`] : [])));
  return { focus, open };
}

function restore(list, { focus, open }) {
  const items = keyedItems(list);
  for (const item of items) {
    folds(item).forEach((fold, i) => {
      if (open.includes(`${item.getAttribute("data-key")}#${i}`)) fold.setAttribute("open", "");
    });
  }
  const holder = focus && items.find((item) => item.getAttribute("data-key") === focus.key);
  const target = holder && (focus.index >= 0 ? focusables(holder)[focus.index] : null);
  if (target) target.focus();
}

// Redraws only when the answer changed, keeping keyboard focus and open folds on the same items.
export function draw(view, ctx, data) {
  const inbox = normalizeInbox(data);
  if (ctx.setCounts) ctx.setCounts(inboxCounts(inbox));
  view.updated.textContent = ctx.t("inbox.updated", { time: timeText(ctx, Date.now() / 1000), seconds: formatDuration(ctx.t, POLL_SECONDS) });
  const signature = JSON.stringify(inbox);
  if (signature === view.signature) return;
  view.signature = signature;
  const before = remember(view.list);
  const groups = groupByKind(inbox);
  clear(view.list).append(...(groups.length ? groups.map((group) => groupView(ctx, group)) : [emptyView(ctx)]));
  restore(view.list, before);
}

export function pageView(ctx) {
  const updated = h("p", { class: "page-sub" });
  const problem = h("div", { class: "form-status form-status-error", attrs: { role: "status", hidden: true } });
  const refreshButton = h("button", { class: "button button-quiet", attrs: { type: "button" }, text: ctx.t("inbox.refresh") });
  const list = h("div", { class: "inbox-groups" });
  const title = h("div", {}, h("h1", { text: ctx.t("nav.inbox") }), h("p", { class: "page-lead", text: ctx.t("inbox.lead") }), updated);
  const head = h("header", { class: "page-head" }, title, refreshButton);
  const element = h("div", { class: "page inbox" }, head, problem, list);
  return { element, updated, problem, refreshButton, list, signature: null };
}

export async function render(ctx) {
  const view = pageView(ctx);
  const load = async () => draw(view, ctx, await ctx.api.get("/inbox"));
  await load();
  const refresh = singleFlight(async () => {
    try {
      await load();
      view.problem.hidden = true;
    } catch (error) {
      replaceParts(view.problem, [h("p", { text: ctx.t("inbox.stale") }), ...errorParts(ctx, error)]);
      view.problem.hidden = false;
    }
  });
  view.refreshButton.addEventListener("click", () => refresh());
  return { element: view.element, refresh, pollSeconds: POLL_SECONDS };
}
