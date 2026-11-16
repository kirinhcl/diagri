// The project conversation: what the operator asked and what each model role answered, with the
// tools it used, in order. Sending a message gives the orchestrator a new goal; nothing said here
// approves anything (approval is a separate, re-authenticated action on the stage page).
import { labelOr } from "../i18n.js";
import { newRequestId } from "../receipts.js";
import { clear, h } from "../ui/dom.js";
import { richText } from "../ui/rich-text.js";
import { errorParts, timeText } from "../ui/section.js";

const ROLES = new Set(["user", "orchestrator", "planner", "researcher", "auditor"]);
const CLOSED_ROUNDS = new Set(["delivered", "aborted"]);
const NEAR_BOTTOM_PX = 48;

function roleLabel(ctx, role) {
  return labelOr(ctx.t, "chat.role", ROLES.has(role) ? role : "other");
}

function codeDetail(label, text) {
  if (text === undefined || text === null || text === "") return null;
  return h("div", { class: "chat-tool-part" }, h("p", { class: "chat-tool-label", text: label }), h("pre", { class: "code-block", text: String(text) }));
}

function messageView(ctx, entry) {
  const head = h("p", { class: "chat-meta" }, `${roleLabel(ctx, "user")} · ${entry.detail.operator || ""} · ${timeText(ctx, entry.at)}`);
  return h("li", { class: "chat-entry chat-user" }, head, h("div", { class: "chat-bubble", text: entry.text }));
}

function replyView(ctx, entry) {
  const head = h("p", { class: "chat-meta" }, h("span", { class: `chat-role chat-role-${entry.role}`, text: roleLabel(ctx, entry.role) }), ` · ${timeText(ctx, entry.at)}`);
  const kind = entry.detail.final ? "chat-bubble" : "chat-bubble chat-bubble-aside";
  return h("li", { class: "chat-entry chat-agent" }, head, richText(entry.text, `${kind} rich-text`));
}

function toolView(ctx, entry) {
  const failed = entry.detail.is_error === true;
  const summary = h(
    "summary",
    {},
    h("span", { class: `chat-role chat-role-${entry.role}`, text: roleLabel(ctx, entry.role) }),
    " ",
    h("code", { text: entry.text }),
    failed ? h("span", { class: "chat-tool-failed", text: ` ${ctx.t("chat.toolFailed")}` }) : null,
  );
  const body = [codeDetail(ctx.t("chat.toolInput"), entry.detail.input), codeDetail(ctx.t("chat.toolResult"), entry.detail.result)];
  return h("li", { class: ["chat-entry", "chat-tool", failed ? "chat-tool-error" : null] }, h("details", {}, summary, ...body));
}

// One line for a status entry; a reason is shown unless it only says that the run finished.
export function statusText(ctx, entry) {
  const role = roleLabel(ctx, entry.role);
  if (entry.text === "follow_up") return ctx.t("chat.followUp", { role });
  const detail = entry.detail || {};
  const reason = detail.reason && detail.reason !== "run finished" ? `: ${detail.reason}` : "";
  return `${ctx.t("chat.taskEnded", { role, state: labelOr(ctx.t, "state", entry.text) })}${reason}`;
}

function statusView(ctx, entry) {
  const tone = entry.text === "needs_attention" ? "chat-status chat-status-warn" : "chat-status";
  return h("li", { class: ["chat-entry", tone] }, h("p", { text: statusText(ctx, entry) }));
}

export function entryView(ctx, entry) {
  if (entry.kind === "message") return messageView(ctx, entry);
  if (entry.kind === "reply") return replyView(ctx, entry);
  if (entry.kind === "tool") return toolView(ctx, entry);
  return statusView(ctx, entry);
}

// The rounds a message can be about: the open ones, newest first (as the project read lists them).
export function openRounds(project) {
  return (Array.isArray(project.rounds) ? project.rounds : []).filter((r) => !CLOSED_ROUNDS.has(r.state));
}

function roundPicker(ctx, project) {
  const open = openRounds(project);
  const select = h("select", { class: "input chat-round", attrs: { "aria-label": ctx.t("chat.round") } });
  select.append(h("option", { attrs: { value: "" }, text: ctx.t("chat.noRound") }));
  for (const item of open) {
    select.append(h("option", { attrs: { value: item.round_id }, text: `${item.round_id} · ${labelOr(ctx.t, "state", item.state)}` }));
  }
  if (open.length) select.value = open[0].round_id;
  return select;
}

export function conversationSection(ctx, project) {
  const log = h("ol", { class: "chat-log", attrs: { "aria-live": "polite", "aria-label": ctx.t("chat.title") } });
  const empty = h("p", { class: "block-note", text: ctx.t("chat.empty") });
  const problem = h("div", { class: "form-status form-status-error", attrs: { role: "status", hidden: true } });
  const input = h("textarea", { class: "input input-area chat-input", attrs: { rows: 3, "aria-label": ctx.t("chat.placeholder"), placeholder: ctx.t("chat.placeholder") } });
  const rounds = roundPicker(ctx, project);
  const send = h("button", { class: "button button-primary", attrs: { type: "submit" }, text: ctx.t("chat.send") });
  const hint = h("p", { class: "block-note", text: ctx.t("chat.hint") });
  const form = h("form", { class: "chat-form" }, input, h("div", { class: "chat-actions" }, rounds, send), hint);
  let last = 0;

  const showProblem = (error) => {
    clear(problem).append(...errorParts(ctx, error));
    problem.hidden = false;
  };

  // The newest entry is shown on opening and after sending; a reader who scrolled up to read is
  // left where they are when new entries arrive. The first batch comes before the page is on
  // screen, where scrolling does nothing, so it is repeated once the log is laid out.
  let shown = false;
  const scrollToEnd = () => {
    log.scrollTop = log.scrollHeight;
    if (!log.isConnected) requestAnimationFrame(() => (log.scrollTop = log.scrollHeight));
  };
  const refresh = async () => {
    const data = await ctx.api.get(`/projects/${encodeURIComponent(project.project_id)}/conversation?after=${last}`);
    const entries = Array.isArray(data && data.entries) ? data.entries : [];
    if (!entries.length) return;
    const follow = !shown || log.scrollHeight - log.scrollTop - log.clientHeight < NEAR_BOTTOM_PX;
    for (const entry of entries) {
      log.append(entryView(ctx, entry));
      last = Math.max(last, entry.seq);
    }
    empty.hidden = true;
    shown = true;
    if (follow) scrollToEnd();
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const goal = input.value.trim();
    if (!goal) return;
    problem.hidden = true;
    send.disabled = true;
    const body = { project_id: project.project_id, goal, request_id: newRequestId() };
    if (rounds.value) body.round_id = rounds.value;
    try {
      await ctx.api.post("/goals", body, { action: ctx.t("chat.send") });
      input.value = "";
      await refresh();
      scrollToEnd();
    } catch (error) {
      showProblem(error);
    } finally {
      send.disabled = false;
    }
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) form.requestSubmit();
  });

  const element = h("div", { class: "chat" }, empty, log, problem, form);
  return { element, refresh };
}
