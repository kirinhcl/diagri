// A service that is not configured has no routes at all: the server answers a plain 404, with no refusal code.
import { ApiError } from "../api.js";
import { hrefFor } from "../router.js";
import { h } from "../ui/dom.js";
import { note, pageHead, section } from "../ui/section.js";

export function isNotMounted(error) {
  return error instanceof ApiError && error.status === 404 && !error.code;
}

// The caller does not hold the greenhouse (multi-user): say so and point at the greenhouses page.
export function isNotLockHolder(error) {
  return error instanceof ApiError && error.code === "not_lock_holder";
}

export function lockFirst(ctx, title) {
  const link = h("a", { class: "text-link", attrs: { href: hrefFor("greenhouses") }, text: ctx.t("greenhouses.goLock") });
  return h("div", { class: "page" }, pageHead(title, ""), section(title, note(ctx.t("greenhouses.needLock")), h("p", {}, link)));
}
