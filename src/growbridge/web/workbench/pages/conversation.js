// The project conversation: what the operator asked and what each model role answered, with the
// tools it used, in order. Sending a message gives the orchestrator a new goal; nothing said here
// approves anything (approval is a separate, re-authenticated action on the stage page).
import { labelOr } from "../i18n.js";
import { messageParts } from "../messages.js";
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

// What one call did, in words (the role first when asked).
function lineParts(ctx, entry, withRole) {
  const role = withRole ? [roleSpan(ctx, entry.role), " · "] : [];
  return [...role, labelOr(ctx.t, "chat.tool", entry.text), ...(failedCall(entry) ? [failedMark(ctx)] : [])];
}

// The tool's own name, its input and its result.
function callDetails(ctx, entry) {
  const detail = entry.detail || {};
  return techDetails(ctx.t, [
    [ctx.t("chat.tech.tool"), entry.text],
    [ctx.t("chat.toolInput"), detail.input],
    [ctx.t("chat.toolResult"), detail.result],
  ]);
}

// Adjacent tool calls in the log, grown in place as calls arrive. A single call is one line; from
// the second call on they sit in a closed fold that counts them, naming the role once when one role
// made them all, else on each call. Each call's details are made once and kept, so a fold the
// reader opened stays open; only the plain lines and the count are written again.
function toolRun(ctx) {
  const element = h("li", { class: "chat-entry chat-tool" });
  const calls = []; // { entry, line, details }
  let group = null; // { summary, list } from the second call on
  const startGroup = () => {
    const [first] = calls;
    const summary = h("summary");
    const list = h("ol", { class: "chat-tool-list" }, h("li", { class: "chat-tool-item" }, first.line, first.details));
    element.append(h("details", { class: "chat-tools" }, summary, list));
    group = { summary, list };
  };
  const redraw = () => {
    const failed = calls.some((call) => failedCall(call.entry));
    const mixed = new Set(calls.map((call) => call.entry.role)).size > 1;
    element.setAttribute("class", ["chat-entry", "chat-tool", failed ? "chat-tool-error" : "", group ? "chat-tool-group" : ""].filter(Boolean).join(" "));
    for (const call of calls) call.line.replaceChildren(...lineParts(ctx, call.entry, !group || mixed));
    if (!group) return;
    const role = mixed ? [] : [roleSpan(ctx, calls[0].entry.role), " · "];
    group.summary.replaceChildren(...role, ctx.t("chat.toolGroup", { count: calls.length }), ...(failed ? [failedMark(ctx)] : []));
  };
  const add = (entry) => {
    const call = { entry, line: h("p", { class: "chat-tool-line" }), details: callDetails(ctx, entry) };
    calls.push(call);
    if (calls.length === 1) element.append(call.line, ...(call.details ? [call.details] : []));
    else {
      if (!group) startGroup();
      group.list.append(h("li", { class: "chat-tool-item" }, call.line, call.details));
    }
    redraw();
  };
  return { element, add };
}

// Calls made one after another, as the log shows them.
export function toolGroupView(ctx, items) {
  const run = toolRun(ctx);
  for (const entry of items) run.add(entry);
  return run.element;
}

// --- status entries ----------------------------------------------------------------------------------

// One line for a status entry: who ended and how. The server's own reason is in the entry's details.
export function statusText(ctx, entry) {
  const role = roleLabel(ctx.t, entry.role);
  if (entry.text === "follow_up") return ctx.t("chat.followUp", { role });
  return ctx.t("chat.taskEnded", { role, state: labelOr(ctx.t, "state", entry.text) });
}

// A status entry: the sentence, then why it ended and what to do next when the server gave a code.
// One fold holds the state, the reason, the ids and the code's own details.
export function statusView(ctx, entry) {
  const detail = entry.detail || {};
  const tone = entry.text === "needs_attention" ? "chat-status chat-status-warn" : "chat-status";
  const coded = typeof detail.code === "string" ? messageParts(ctx, "chat_end", detail.code, detail.params) : null;
  const fold = techDetails(ctx.t, [
    [ctx.t("chat.tech.state"), entry.text],
    [ctx.t("chat.tech.reason"), detail.reason],
    [ctx.t("tech.id.task_id"), entry.task_id],
    [ctx.t("chat.tech.nextTask"), detail.task_id],
    ...(coded ? coded.details : []),
  ]);
  const lines = [h("p", { text: statusText(ctx, entry) })];
  if (coded) lines.push(h("p", { class: "message-text", text: coded.text }));
  if (coded && coded.action) lines.push(h("p", { class: "message-action", text: coded.action }));
  return h("li", { class: ["chat-entry", tone] }, ...lines, fold);
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

// The log in order. A tool call that arrives right after the last run of calls joins it. The
// operator's pending line stays last until the goal's own task writes something other than the
// operator's message (its task is unknown while the goal is on its way), or it is dropped.
function chatLog(ctx) {
  const log = h("ol", { class: "chat-log", attrs: { "aria-live": "polite", "aria-label": ctx.t("chat.title") } });
  const empty = h("p", { class: "block-note", text: ctx.t("chat.empty") });
  let pending = null; // { element, task }
  let lastPlaced = null;
  let run = null; // the last run of tool calls
  const syncEmpty = () => (empty.hidden = log.childNodes.length > 0);
  const place = (element) => {
    log.insertBefore(element, pending && pending.element);
    lastPlaced = element;
  };
  const addTools = (items) => {
    if (run === null || lastPlaced !== run.element) {
      run = toolRun(ctx);
      place(run.element);
    }
    for (const entry of items) run.add(entry);
  };
  const dropPending = () => {
    if (pending) pending.element.remove();
    pending = null;
    syncEmpty();
  };
  const answers = (entry) => entry.kind !== "message" && (pending.task === null || entry.task_id === pending.task);
  const add = (entries) => {
    if (pending && pending.task !== undefined && entries.some(answers)) dropPending();
    for (const item of groupToolEntries(entries)) {
      if (item.kind === "toolGroup") addTools(item.items);
      else place(entryView(ctx, item));
    }
    syncEmpty();
  };
  const showPending = () => {
    dropPending();
    const element = log.appendChild(h("li", { class: "chat-entry chat-status chat-pending" }, h("p", { text: ctx.t("chat.pending") })));
    pending = { element, task: undefined };
    syncEmpty();
  };
  // The task the server made for the goal; with none named, any other writer ends the wait.
  const pendingFor = (taskId) => {
    if (pending) pending = { ...pending, task: taskId ?? null };
  };
  return { log, empty, add, showPending, pendingFor, dropPending };
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
  const body = (goal) => ({ project_id: project.project_id, goal, language: ctx.lang, request_id: newRequestId(), ...(rounds.value ? { round_id: rounds.value } : {}) });
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
    const made = await ctx.api.post("/goals", parts.body(goal), { action: ctx.t("chat.send") });
    taken = true;
    view.pendingFor(made && made.task_id);
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
  // Sending reads the log outside the page's poll, so two reads can overlap: only entries newer
  // than the last one shown are added.
  const refresh = async () => {
    const data = await ctx.api.get(`/projects/${encodeURIComponent(project.project_id)}/conversation?after=${last}`);
    const entries = (Array.isArray(data && data.entries) ? data.entries : []).filter((entry) => entry.seq > last);
    if (!entries.length) return;
    const follow = !shown || log.scrollHeight - log.scrollTop - log.clientHeight < NEAR_BOTTOM_PX;
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
