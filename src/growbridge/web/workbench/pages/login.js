// Sign-in page. A wrong name or secret and a lock-out get their own texts, not the session denial.
import { ApiError, singleFlight } from "../api.js";
import { hrefFor } from "../router.js";
import { clear, h } from "../ui/dom.js";
import { errorLines } from "../ui/forms.js";
import { brand, languageSwitch } from "../ui/layout.js";

const IN_CONSOLE = /^#\/\S*$/;

function failureLines(error, ctx) {
  if (error instanceof ApiError && error.code === "session") return [ctx.t("login.failed")];
  if (error instanceof ApiError && error.code === "locked") return [ctx.t("login.locked")];
  return errorLines(error, ctx.lang, ctx.t, ctx);
}

// Only an address inside the console, and never the sign-in page itself.
function target(returnTo) {
  const valid = typeof returnTo === "string" && IN_CONSOLE.test(returnTo) && !returnTo.startsWith(hrefFor("login"));
  return valid ? returnTo : hrefFor("inbox");
}

function input(id, name, type, autocomplete) {
  const attrs = { id, name, type, autocomplete, required: true, autocapitalize: "none", spellcheck: "false" };
  return h("input", { class: "input", attrs });
}

function field(id, label, control) {
  return h("div", { class: "field" }, h("label", { class: "field-label", attrs: { for: id }, text: label }), control);
}

export async function render(ctx, params = {}) {
  const name = input("login-name", "name", "text", "username");
  const secret = input("login-secret", "secret", "password", "current-password");
  const status = h("div", { class: "form-status form-status-error", attrs: { role: "alert", hidden: true } });
  const button = h("button", { class: "button button-primary button-wide", attrs: { type: "submit" }, text: ctx.t("login.submit") });
  const submit = singleFlight(async () => {
    status.hidden = true;
    button.disabled = true;
    try {
      await ctx.api.post("/login", { name: name.value.trim(), secret: secret.value });
      ctx.navigate(target(params.returnTo));
    } catch (error) {
      clear(status).append(...failureLines(error, ctx).map((line) => h("p", { text: line })));
      status.hidden = false;
      secret.focus();
    } finally {
      secret.value = "";
      button.disabled = false;
    }
  });
  const onSubmit = (event) => {
    event.preventDefault();
    submit();
  };
  const form = h(
    "form",
    { class: "login-form", on: { submit: onSubmit } },
    field("login-name", ctx.t("login.name"), name),
    field("login-secret", ctx.t("login.secret"), secret),
    status,
    button,
  );
  const head = h("div", { class: "login-head" }, brand(ctx.t, "div"), languageSwitch(ctx, "login-language"));
  const card = h(
    "section",
    { class: "login-card", attrs: { "aria-labelledby": "login-title" } },
    head,
    h("h1", { attrs: { id: "login-title" }, text: ctx.t("login.title") }),
    h("p", { class: "login-intro", text: ctx.t("login.intro") }),
    form,
  );
  return { element: h("main", { class: "login" }, card) };
}
