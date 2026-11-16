// The project conversation: what the operator asked and what each model role answered, with the
// tools it used, in order. Sending a message gives the orchestrator a new goal; nothing said here
// approves anything (approval is a separate, re-authenticated action on the stage page).
import { labelOr } from "../i18n.js";
import { newRequestId } from "../receipts.js";
import { h } from "../ui/dom.js";
import { displayName, roleLabel } from "../ui/names.js";
import { richText } from "../ui/rich-text.js";
import { errorBox, showErrors, techDetails, timeText } from "../ui/section.js";

const CLOSED_ROUNDS = new Set(["delivered", "aborted"]);
const NEAR_BOTTOM_PX = 48;

function messageView(ctx, entry) {
  const head = h("p", { class: "chat-meta" }, `${roleLabel(ctx.t, "user")} · ${entry.detail.operator || ""} · ${timeText(ctx, entry.at)}`);
  return h("li", { class: "chat-entry chat-user" }, head, h("div", { class: "chat-bubble", text: entry.text }));
}

function replyView(ctx, entry) {
  const head = h("p", { class: "chat-meta" }, h("span", { class: `chat-role chat-role-${entry.role}`, text: roleLabel(ctx.t, entry.role) }), ` · ${timeText(ctx, entry.at)}`);
  const kind = entry.detail.final ? "chat-bubble" : "chat-bubble chat-bubble-aside";
  return h("li", { class: "chat-entry chat-agent" }, head, richText(entry.text, `${kind} rich-text`));
}

// --- tool calls ------------------------------------------------------------------------------------

// Adjacent tool calls become one group; every other entry stays as it is.
export function groupToolEntries(entries) {
  return entries.reduce((out, entry) => {
    if (entry.kind !== "tool") return [...out, entry];
    const previous = out.at(-1);
    if (previous && previous.kind === "toolGroup") return [...out.slice(0, -1), { kind: "toolGroup", items: [...previous.items, entry] }];
    return [...out, { kind: "toolGroup", items: [entry] }];
  }, []);
}

const roleSpan = (ctx, role) => h("span", { class: `chat-role chat-role-${role}`, text: roleLabel(ctx.t, role) });
const failedCall = (entry) => (entry.detail || {}).is_error === true;
const failedMark = (ctx) => h("span", { class: "chat-tool-failed", text: ` ${ctx.t("chat.toolFailed")}` });

// What one call did, in words; the tool's own name, its input and its result are in the details.
function toolLine(ctx, entry, withRole) {
  const detail = entry.detail || {};
  const line = h(
    "p",
    { class: "chat-tool-line" },
    withRole ? [roleSpan(ctx, entry.role), " · "] : null,
    labelOr(ctx.t, "chat.tool", entry.text),
    failedCall(entry) ? failedMark(ctx) : null,
  );
  const fold = techDetails(ctx.t, [
    [ctx.t("chat.tech.tool"), entry.text],
    [ctx.t("chat.toolInput"), detail.input],
    [ctx.t("chat.toolResult"), detail.result],
  ]);
  return [line, fold];
}

// Calls made one after another: a single call is one line; more are a closed fold that counts them.
// The role is named once when one role made them all, else on each call.
export function toolGroupView(ctx, items, { open = false } = {}) {
  const failed = items.some(failedCall);
  const classes = ["chat-entry", "chat-tool", failed ? "chat-tool-error" : null];
  if (items.length === 1) return h("li", { class: classes }, toolLine(ctx, items[0], true));
  const roles = [...new Set(items.map((entry) => entry.role))];
  const mixed = roles.length > 1;
  const summary = h(
    "summary",
    {},
    mixed ? null : [roleSpan(ctx, roles[0]), " · "],
    ctx.t("chat.toolGroup", { count: items.length }),
    failed ? failedMark(ctx) : null,
  );
  const list = h("ol", { class: "chat-tool-list" }, items.map((entry) => h("li", { class: "chat-tool-item" }, toolLine(ctx, entry, mixed))));
  return h("li", { class: [...classes, "chat-tool-group"] }, h("details", { class: "chat-tools", attrs: { open } }, summary, list));
}

// --- status entries ----------------------------------------------------------------------------------

// One line for a status entry: who ended and how. The server's own reason is in the entry's details.
export function statusText(ctx, entry) {
  const role = roleLabel(ctx.t, entry.role);
  if (entry.text === "follow_up") return ctx.t("chat.followUp", { role });
  return ctx.t("chat.taskEnded", { role, state: labelOr(ctx.t, "state", entry.text) });
}

export function statusView(ctx, entry) {
  const detail = entry.detail || {};
  const tone = entry.text === "needs_attention" ? "chat-status chat-status-warn" : "chat-status";
  const fold = techDetails(ctx.t, [
    [ctx.t("chat.tech.state"), entry.text],
    [ctx.t("chat.tech.reason"), detail.reason],
    [ctx.t("tech.id.task_id"), entry.task_id],
    [ctx.t("chat.tech.nextTask"), detail.task_id],
  ]);
  return h("li", { class: ["chat-entry", tone] }, h("p", { text: statusText(ctx, entry) }), fold);
}

function entryView(ctx, entry) {
  if (entry.kind === "message") return messageView(ctx, entry);
  if (entry.kind === "reply") return replyView(ctx, entry);
  return statusView(ctx, entry);
}

// --- the round a message is about ----------------------------------------------------------------

// The rounds a message can be about: the open ones, newest first (as the project read lists them).
export function openRounds(project) {
  return (Array.isArray(project.rounds) ? project.rounds : []).filter((r) => !CLOSED_ROUNDS.has(r.state));
}

// A message is about no round unless the operator picks one.
export function roundPicker(ctx, project) {
  const select = h("select", { class: "input chat-round", attrs: { "aria-label": ctx.t("chat.round") } });
  select.append(h("option", { attrs: { value: "" }, text: ctx.t("chat.noRound") }));
  for (const item of openRounds(project)) {
    const text = `${displayName(ctx, "round", item)} · ${labelOr(ctx.t, "state", item.state)}`;
    select.append(h("option", { attrs: { value: item.round_id }, text }));
  }
  select.value = "";
  return select;
}

// --- the log and the message form ------------------------------------------------------------------

// The log in order. A tool call that arrives right after the last group joins it (an open group
// stays open). The operator's pending line stays last until it is dropped.
function chatLog(ctx) {
  const log = h("ol", { class: "chat-log", attrs: { "aria-live": "polite", "aria-label": ctx.t("chat.title") } });
  const empty = h("p", { class: "block-note", text: ctx.t("chat.empty") });
  let pending = null;
  let lastPlaced = null;
  let tail = null; // the last tool group: { items, element }
  const syncEmpty = () => (empty.hidden = log.childNodes.length > 0);
  const place = (element) => {
    log.insertBefore(element, pending);
    lastPlaced = element;
    return element;
  };
  const addTools = (items) => {
    if (tail === null || lastPlaced !== tail.element) {
      tail = { items, element: place(toolGroupView(ctx, items)) };
      return;
    }
    const merged = [...tail.items, ...items];
    const open = tail.items.length > 1 && tail.element.firstChild.open === true;
    const element = toolGroupView(ctx, merged, { open });
    log.insertBefore(element, tail.element);
    tail.element.remove();
    tail = { items: merged, element };
    lastPlaced = element;
  };
  const add = (entries) => {
    for (const item of groupToolEntries(entries)) {
      if (item.kind === "toolGroup") addTools(item.items);
      else place(entryView(ctx, item));
    }
    syncEmpty();
  };
  const dropPending = () => {
    if (pending) pending.remove();
    pending = null;
    syncEmpty();
  };
  const showPending = () => {
    dropPending();
    pending = log.appendChild(h("li", { class: "chat-entry chat-status chat-pending" }, h("p", { text: ctx.t("chat.pending") })));
    syncEmpty();
  };
  return { log, empty, add, showPending, dropPending };
}

function messageForm(ctx, project) {
  const input = h("textarea", { class: "input input-area chat-input", attrs: { rows: 3, "aria-label": ctx.t("chat.placeholder"), placeholder: ctx.t("chat.placeholder") } });
  const rounds = roundPicker(ctx, project);
  const send = h("button", { class: "button button-primary", attrs: { type: "submit" }, text: ctx.t("chat.send") });
  const hint = h("p", { class: "block-note", text: ctx.t("chat.hint") });
  const form = h("form", { class: "chat-form" }, input, h("div", { class: "chat-actions" }, rounds, send), hint);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) form.requestSubmit();
  });
  const body = (goal) => ({ project_id: project.project_id, goal, request_id: newRequestId(), ...(rounds.value ? { round_id: rounds.value } : {}) });
  return { form, input, send, body };
}

// Sending shows the pending line at once. A refusal takes it away and says why, and the text stays
// in the box; once the goal is taken the box is emptied and the log read again.
async function sendGoal(ctx, { view, parts, problem, refresh, scrollToEnd }) {
  const goal = parts.input.value.trim();
  if (!goal) return;
  problem.hidden = true;
  parts.send.disabled = true;
  view.showPending();
  scrollToEnd();
  let taken = false;
  try {
    await ctx.api.post("/goals", parts.body(goal), { action: ctx.t("chat.send") });
    taken = true;
    parts.input.value = "";
    await refresh();
    scrollToEnd();
  } catch (error) {
    if (!taken) view.dropPending();
    showErrors(problem, error, ctx);
  } finally {
    parts.send.disabled = false;
  }
}

export function conversationSection(ctx, project) {
  const view = chatLog(ctx);
  const problem = errorBox();
  const parts = messageForm(ctx, project);
  const { log } = view;
  let last = 0;

  // The newest entry is shown on opening and after sending; a reader who scrolled up to read is
  // left where they are when new entries arrive. The first batch comes before the page is on
  // screen, where scrolling does nothing, so it is repeated once the log is laid out.
  let shown = false;
  const scrollToEnd = () => {
    log.scrollTop = log.scrollHeight;
    if (!log.isConnected) requestAnimationFrame(() => (log.scrollTop = log.scrollHeight));
  };
  // The pending line goes when someone other than the operator writes: the server records the
  // operator's own message while it takes it, so that entry alone does not end the wait.
  const refresh = async () => {
    const data = await ctx.api.get(`/projects/${encodeURIComponent(project.project_id)}/conversation?after=${last}`);
    const entries = Array.isArray(data && data.entries) ? data.entries : [];
    if (!entries.length) return;
    const follow = !shown || log.scrollHeight - log.scrollTop - log.clientHeight < NEAR_BOTTOM_PX;
    if (entries.some((entry) => entry.kind !== "message")) view.dropPending();
    view.add(entries);
    last = entries.reduce((most, entry) => Math.max(most, entry.seq), last);
    shown = true;
    if (follow) scrollToEnd();
  };

  parts.form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendGoal(ctx, { view, parts, problem, refresh, scrollToEnd });
  });
  const element = h("div", { class: "chat" }, view.empty, log, problem, parts.form);
  return { element, refresh };
}
