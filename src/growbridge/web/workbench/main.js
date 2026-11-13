// Console start-up: session, hash routing, language, polling and notices.
import { ApiError, createApi, singleFlight } from "./api.js";
import { LANGS, initialLang, makeT } from "./i18n.js";
import { inboxCounts } from "./pages/inbox.js";
import * as loginPage from "./pages/login.js";
import { hrefFor, parseHash } from "./router.js";
import { askSecret } from "./ui/dialog.js";
import { clear, h } from "./ui/dom.js";
import { bindFormContext, errorLines } from "./ui/forms.js";
import { shell } from "./ui/layout.js";

const LANGUAGE_KEY = "growbridge-workbench-language";
const NOTICE_MS = 6000;
// Each page lives in pages/<name>.js and is loaded on its first visit.
const PAGES = new Set(["inbox", "projects", "project", "round", "stage", "alerts", "evidence", "compute", "safety"]);
const ID_CRUMBS = new Map([
  ["project", ["projectId", "crumb.project"]],
  ["round", ["roundId", "crumb.round"]],
  ["stage", ["stageId", "crumb.stage"]],
]);

const app = document.getElementById("app");
const notices = h("div", { class: "notice-region", attrs: { "aria-live": "polite" } });
const state = { lang: "en", t: makeT("en"), me: null, frame: null, at: null, poll: null, timer: null, token: 0, returnTo: null };
const api = createApi({ askReauth: (action) => askSecret(state.t, action || ""), onSessionLost });

// --- language: the only thing kept in localStorage ------------------------------------------------
function readLanguage() {
  try {
    return localStorage.getItem(LANGUAGE_KEY);
  } catch {
    return null; // storage blocked: fall back to the browser's language
  }
}

function writeLanguage(lang) {
  try {
    localStorage.setItem(LANGUAGE_KEY, lang);
  } catch {
    // storage blocked: the choice holds until the page is reloaded
  }
}

function applyLanguage(lang) {
  state.lang = lang;
  state.t = makeT(lang);
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  document.title = state.t("app.title");
}

async function setLang(lang) {
  if (!LANGS.includes(lang) || lang === state.lang) return;
  writeLanguage(lang);
  applyLanguage(lang);
  state.frame = null; // rebuilt in the new language
  await route();
  const select = document.getElementById("wb-language") || document.getElementById("login-language");
  if (select) select.focus();
}

// --- notices, navigation and the page context ----------------------------------------------------
function notify(message, kind = "info") {
  clear(notices);
  const attrs = { type: "button", "aria-label": state.t("common.close") };
  const close = h("button", { class: "notice-close", attrs, text: "×" });
  const role = kind === "error" ? "alert" : "status";
  const notice = h("div", { class: ["notice", `notice-${kind}`], attrs: { role } }, h("p", { text: message }), close);
  close.addEventListener("click", () => notice.remove());
  notices.append(notice);
  if (kind !== "error") setTimeout(() => notice.remove(), NOTICE_MS);
}

function navigate(href) {
  if (location.hash === href) route();
  else location.hash = href;
}

// Remembers where the operator was, so signing in again leads back there.
function onSessionLost() {
  if (parseHash(location.hash).page === "login") return;
  state.returnTo = location.hash || hrefFor("inbox");
  state.me = null;
  navigate(hrefFor("login"));
}

// The page contract's ctx, plus setLang, setBreadcrumbs and setCounts for the frame.
function makeCtx(frame) {
  return {
    api,
    t: state.t,
    lang: state.lang,
    me: state.me,
    navigate,
    notify,
    reload: () => route(),
    setLang,
    setBreadcrumbs: (items) => frame && frame.setBreadcrumbs(items),
    setCounts: (counts) => frame && frame.setCounts(counts),
  };
}

// --- views for pages that could not be shown ------------------------------------------------------
function problemView(lines, retry) {
  const title = state.t("error.title");
  const button = h("button", {
    class: "button button-primary",
    attrs: { type: "button" },
    on: { click: () => route() },
    text: state.t("common.retry"),
  });
  return h(
    "section",
    { class: "wb-problem", attrs: { role: "alert" } },
    h("h1", { text: title }),
    lines.filter((line) => line !== title).map((line) => h("p", { text: line })),
    retry ? button : null,
  );
}

function notFoundView() {
  return h(
    "section",
    { class: "wb-problem" },
    h("h1", { text: state.t("page.notFound") }),
    h("p", {}, h("a", { attrs: { href: hrefFor("inbox") }, text: state.t("nav.inbox") })),
  );
}

function showFatal(error) {
  state.frame = null;
  state.at = null;
  clear(app).append(h("main", { class: "wb-fatal" }, problemView(errorLines(error, state.lang, state.t), true)));
}

function defaultCrumbs(page, params) {
  const { t } = state;
  if (ID_CRUMBS.has(page)) {
    const [key, text] = ID_CRUMBS.get(page);
    return [{ label: t("nav.projects"), href: hrefFor("projects") }, { label: t(text, { id: params[key] }) }];
  }
  return [{ label: PAGES.has(page) ? t(`nav.${page}`) : t("page.notFound") }];
}

// --- rendering ------------------------------------------------------------------------------------
async function renderPage(page, ctx, params) {
  if (!PAGES.has(page)) return { element: notFoundView() };
  let module;
  try {
    module = await import(`./pages/${page}.js`);
  } catch (error) {
    const reason = String(error && error.message ? error.message : error);
    return { element: problemView([state.t("page.loadFailed"), reason], true) };
  }
  try {
    const result = await module.render(ctx, params);
    if (result && result.element) return result;
    return { element: problemView([state.t("page.loadFailed")], true) };
  } catch (error) {
    return { element: problemView(errorLines(error, state.lang, state.t), true) };
  }
}

function ensureFrame() {
  if (!state.frame) {
    state.frame = shell(makeCtx(null));
    clear(app).append(state.frame.root);
  }
  return state.frame;
}

async function showPage(page, params, token) {
  const frame = ensureFrame();
  const moved = state.at !== location.hash;
  const firstView = state.at === null;
  state.at = location.hash;
  frame.setActive(page);
  frame.setBreadcrumbs(defaultCrumbs(page, params));
  const ctx = makeCtx(frame);
  bindFormContext(ctx);
  if (moved) {
    clear(frame.main).append(h("p", { class: "wb-loading", text: state.t("common.loading") }));
    window.scrollTo(0, 0);
  }
  frame.main.setAttribute("aria-busy", "true");
  const result = await renderPage(page, ctx, params);
  if (token !== state.token) return;
  frame.main.removeAttribute("aria-busy");
  clear(frame.main).append(result.element);
  // After a move inside the console the clicked link may be gone; put the keyboard at the new content.
  const focusLost = !document.activeElement || document.activeElement === document.body;
  if (!firstView && focusLost) frame.main.focus({ preventScroll: true });
  startPolling(result, token, page);
  if (page !== "inbox") await refreshCounts(frame);
}

async function showLogin(token) {
  state.me = null;
  state.frame = null;
  state.at = null;
  const ctx = makeCtx(null);
  bindFormContext(ctx);
  const { element } = await loginPage.render(ctx, { returnTo: state.returnTo });
  if (token !== state.token) return;
  clear(app).append(element);
  const name = document.getElementById("login-name");
  if (name) name.focus();
}

async function loadMe(token) {
  try {
    state.me = await api.get("/me");
    return true;
  } catch (error) {
    // A lost session has already been sent to the sign-in page by onSessionLost.
    const lost = error instanceof ApiError && error.code === "session";
    if (token === state.token && !lost) showFatal(error);
    return false;
  }
}

async function route() {
  const token = ++state.token;
  stopPolling();
  const { page, params } = parseHash(location.hash);
  try {
    if (page === "login") return await showLogin(token);
    if (!state.me && !(await loadMe(token))) return;
    if (token !== state.token) return;
    state.returnTo = null;
    await showPage(page, params, token);
  } catch (error) {
    if (token === state.token) showFatal(error);
  }
}

// --- polling and the sidebar counts ---------------------------------------------------------------
async function refreshCounts(frame) {
  try {
    frame.setCounts(inboxCounts(await api.get("/inbox")));
  } catch {
    frame.setCounts(null); // the badges are only a hint: hide them rather than show stale numbers
  }
}

const pollOnce = singleFlight(async () => {
  const poll = state.poll;
  if (!poll || poll.token !== state.token) return;
  try {
    await poll.refresh();
  } catch (error) {
    if (poll.token === state.token) notify(errorLines(error, state.lang, state.t).join(" "), "error");
  }
  if (poll.page !== "inbox" && state.frame && poll.token === state.token) await refreshCounts(state.frame);
});

function schedulePoll() {
  clearInterval(state.timer);
  state.timer = setInterval(() => pollOnce(), state.poll.seconds * 1000);
}

function stopPolling() {
  clearInterval(state.timer);
  state.timer = null;
  state.poll = null;
}

function startPolling(result, token, page) {
  if (!(result.pollSeconds > 0) || typeof result.refresh !== "function") return;
  state.poll = { refresh: result.refresh, seconds: result.pollSeconds, token, page };
  if (!document.hidden) schedulePoll();
}

function onVisibilityChange() {
  if (document.hidden) {
    clearInterval(state.timer);
    state.timer = null;
  } else if (state.poll) {
    pollOnce();
    schedulePoll();
  }
}

function start() {
  applyLanguage(initialLang(readLanguage(), navigator.language));
  document.body.append(notices);
  window.addEventListener("hashchange", () => route());
  document.addEventListener("visibilitychange", onVisibilityChange);
  route();
}

start();
