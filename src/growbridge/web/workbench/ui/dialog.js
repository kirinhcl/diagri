// Modal dialogs on <dialog>: a secret prompt for re-authentication and a yes/no confirmation.
import { h } from "./dom.js";

let counter = 0;
const nextId = (prefix) => `${prefix}-${++counter}`;

// Opens the dialog; when it closes, removes it, gives focus back and resolves with settle().
function openDialog(dialog, settle) {
  const before = document.activeElement;
  return new Promise((resolve) => {
    dialog.addEventListener(
      "close",
      () => {
        const value = settle();
        dialog.remove();
        if (before && before.isConnected && typeof before.focus === "function") before.focus();
        resolve(value);
      },
      { once: true },
    );
    document.body.append(dialog);
    dialog.showModal();
  });
}

// Cancel comes first so that it, not the action, has the focus when the dialog opens.
function actions(t, confirmLabel, onCancel) {
  return h(
    "div",
    { class: "dialog-actions" },
    h("button", {
      class: "button button-quiet",
      attrs: { type: "button", autofocus: true },
      on: { click: onCancel },
      text: t("common.cancel"),
    }),
    h("button", { class: "button button-primary", attrs: { type: "submit" }, text: confirmLabel }),
  );
}

function frame(titleId, onSubmit, ...children) {
  const dialog = h("dialog", { class: "dialog", attrs: { "aria-labelledby": titleId } });
  dialog.append(h("form", { class: "dialog-body", on: { submit: onSubmit } }, ...children));
  return dialog;
}

export function askSecret(t, actionLabel) {
  const titleId = nextId("dialog-title");
  const inputId = nextId("dialog-secret");
  const attrs = { id: inputId, type: "password", name: "secret", required: true, autocomplete: "current-password" };
  const input = h("input", { class: "input", attrs: { ...attrs, autofocus: true } });
  let secret = null;
  const submit = (event) => {
    event.preventDefault();
    if (!input.value) return;
    secret = input.value;
    dialog.close();
  };
  const dialog = frame(
    titleId,
    submit,
    h("h2", { attrs: { id: titleId }, text: t("reauth.title") }),
    h("p", { class: "dialog-text", text: t("reauth.body") }),
    actionLabel ? h("p", { class: "dialog-action", text: t("reauth.action", { action: actionLabel }) }) : null,
    h("label", { class: "field-label", attrs: { for: inputId }, text: t("login.secret") }),
    input,
    actions(t, t("reauth.submit"), () => dialog.close()),
  );
  return openDialog(dialog, () => {
    input.value = "";
    return secret;
  });
}

export function confirmAction(t, { title, lines = [], confirmLabel } = {}) {
  const titleId = nextId("dialog-title");
  let confirmed = false;
  const submit = (event) => {
    event.preventDefault();
    confirmed = true;
    dialog.close();
  };
  const dialog = frame(
    titleId,
    submit,
    h("h2", { attrs: { id: titleId }, text: title }),
    lines.length ? h("ul", { class: "dialog-lines" }, lines.map((line) => h("li", { text: line }))) : null,
    actions(t, confirmLabel || t("common.confirm"), () => dialog.close()),
  );
  return openDialog(dialog, () => confirmed);
}
