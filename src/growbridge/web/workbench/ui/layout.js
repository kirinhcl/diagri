// The signed-in frame: sidebar navigation, top bar with breadcrumbs, language and sign-out.
import { singleFlight } from "../api.js";
import { LANGS, labelOr } from "../i18n.js";
import { hrefFor } from "../router.js";
import { clear, h, svg } from "./dom.js";
import { errorLines } from "./forms.js";

// 24x24 stroke icons; each entry is the list of path data for one icon.
const ICONS = {
  brand: ["M5 19c0-8 6-14 14-14 0 8-6 14-14 14z", "M5 19l8-8"],
  inbox: ["M4 13l2-8h12l2 8v6H4z", "M4 13h4l2 3h4l2-3h4"],
  environment: ["M12 3v4", "M12 17v4", "M3 12h4", "M17 12h4", "M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8z"],
  projects: ["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"],
  alerts: ["M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z", "M10 20a2 2 0 0 0 4 0"],
  evidence: ["M7 3h7l5 5v13H7z", "M14 3v5h5", "M10 14l2 2 4-4"],
  compute: ["M7 7h10v10H7z", "M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"],
  safety: ["M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"],
};
const NAV = [
  { page: "inbox", countKey: "inbox" },
  { page: "environment" },
  { page: "projects", also: ["project", "round", "stage"] },
  { page: "alerts", countKey: "alerts" },
  { page: "evidence" },
  { page: "compute" },
  { page: "safety" },
];
const LANGUAGE_NAMES = { zh: "中文", en: "English" };

function icon(name) {
  const attrs = { viewBox: "0 0 24 24", class: "icon", "aria-hidden": "true", focusable: "false" };
  return svg("svg", attrs, ICONS[name].map((d) => svg("path", { d })));
}

function navigation(t) {
  const links = new Map();
  const counts = new Map();
  const items = NAV.map((item) => {
    const countClass = ["wb-count", `wb-count-${item.countKey}`];
    const count = item.countKey ? h("span", { class: countClass, attrs: { hidden: true } }) : null;
    if (count) counts.set(item.countKey, count);
    const link = h(
      "a",
      { class: "wb-nav-link", attrs: { href: hrefFor(item.page) } },
      icon(item.page),
      h("span", { class: "wb-nav-label", text: t(`nav.${item.page}`) }),
      count,
    );
    links.set(item, link);
    return h("li", {}, link);
  });
  const nav = h("nav", { class: "wb-nav", attrs: { "aria-label": t("nav.main") } }, h("ul", {}, items));
  return { nav, links, counts };
}

// Shared with the sign-in page, which has no frame but still offers both languages.
export function languageSwitch(ctx, id = "wb-language") {
  const options = LANGS.map((lang) =>
    h("option", { attrs: { value: lang, selected: lang === ctx.lang }, text: LANGUAGE_NAMES[lang] || lang }),
  );
  const select = h("select", { class: "wb-language", attrs: { id }, on: { change: () => ctx.setLang(select.value) } }, options);
  const label = h("label", { class: "sr-only", attrs: { for: id }, text: ctx.t("common.language") });
  return h("div", { class: "wb-language-field" }, label, select);
}

function signOutButton(ctx) {
  const button = h("button", { class: "button button-quiet", attrs: { type: "button" }, text: ctx.t("nav.logout") });
  const signOut = singleFlight(async () => {
    button.disabled = true;
    try {
      await ctx.api.post("/logout");
      ctx.navigate(hrefFor("login"));
    } catch (error) {
      ctx.notify(errorLines(error, ctx.lang, ctx.t).join(" "), "error");
    } finally {
      button.disabled = false;
    }
  });
  button.addEventListener("click", () => signOut());
  return button;
}

// The product mark: a link home inside the frame, plain on the sign-in page.
export function brand(t, tag = "a") {
  const attrs = tag === "a" ? { href: hrefFor("inbox") } : {};
  return h(
    tag,
    { class: "wb-brand", attrs },
    h("span", { class: "wb-brand-mark" }, icon("brand")),
    h("span", { class: "wb-brand-name" }, "DiAGRI", h("small", { text: t("app.subtitle") })),
  );
}

export function sidebar(ctx, nav) {
  const entry = ctx.me && ctx.me.entry ? ctx.me.entry : "unknown";
  const zone = (ctx.me && ctx.me.timezone) || "UTC";
  return h(
    "aside",
    { class: "wb-sidebar" },
    brand(ctx.t),
    nav,
    h(
      "div",
      { class: ["wb-entry", `wb-entry-${entry}`] },
      h("span", { class: "wb-entry-label", text: ctx.t("entry.label") }),
      h("strong", { text: labelOr(ctx.t, "entry", entry) }),
      h("span", { class: "wb-entry-note", text: ctx.t("entry.onsiteHint") }),
      h("span", { class: "wb-entry-label", text: ctx.t("frame.timezone") }),
      h("strong", { class: "wb-entry-zone", text: zone }),
    ),
  );
}

function topBar(ctx, crumbs) {
  const operator = ctx.me && ctx.me.operator ? ctx.me.operator : "";
  return h(
    "header",
    { class: "wb-topbar" },
    h("nav", { class: "wb-crumbs", attrs: { "aria-label": ctx.t("nav.breadcrumb") } }, crumbs),
    h(
      "div",
      { class: "wb-topbar-tools" },
      languageSwitch(ctx),
      h("span", { class: "wb-operator" }, h("span", { class: "sr-only", text: ctx.t("nav.signedInAs") }), operator),
      signOutButton(ctx),
    ),
  );
}

function crumbItem(item, isLast) {
  if (isLast || !item.href) {
    return h("li", {}, h("span", { attrs: { "aria-current": isLast ? "page" : null }, text: item.label }));
  }
  return h("li", {}, h("a", { attrs: { href: item.href }, text: item.label }));
}

function skipLink(ctx, main) {
  const focusMain = (event) => {
    event.preventDefault();
    main.focus();
  };
  return h("a", { class: "skip-link", attrs: { href: "#wb-main" }, on: { click: focusMain }, text: ctx.t("nav.skip") });
}

// Beyond the contract it also returns setActive(page), which main.js uses to mark the current section.
export function shell(ctx) {
  const { nav, links, counts } = navigation(ctx.t);
  const crumbs = h("ol", {});
  const main = h("main", { class: "wb-main", attrs: { id: "wb-main", tabindex: "-1" } });
  const root = h(
    "div",
    { class: "wb-shell" },
    skipLink(ctx, main),
    sidebar(ctx, nav),
    h("div", { class: "wb-body" }, topBar(ctx, crumbs), main),
  );
  const setBreadcrumbs = (items) => {
    clear(crumbs);
    items.forEach((item, index) => crumbs.append(crumbItem(item, index === items.length - 1)));
  };
  const setCounts = (values) => {
    for (const [key, badge] of counts) {
      const value = values ? values[key] : null;
      badge.textContent = Number.isFinite(value) && value > 0 ? String(value) : "";
      badge.hidden = !badge.textContent;
    }
  };
  const setActive = (page) => {
    for (const [item, link] of links) {
      const active = item.page === page || (item.also || []).includes(page);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
  };
  return { root, main, setBreadcrumbs, setCounts, setActive };
}
