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

// The greenhouse this installation drives, from the greenhouse list; null when it cannot be read.
async function controlledGreenhouse(ctx) {
  try {
    const data = await ctx.api.get("/greenhouses");
    const rows = data && Array.isArray(data.greenhouses) ? data.greenhouses : [];
    return rows.find((row) => row.controlled) || null;
  } catch {
    return null;
  }
}

function lockLink(ctx, house) {
  const text = house ? ctx.t("greenhouses.lockNamed", { name: house.name }) : ctx.t("greenhouses.goLock");
  return h("p", {}, h("a", { class: "text-link", attrs: { href: hrefFor("greenhouses") }, text }));
}

// Names the greenhouse the page shows when it can: whoever holds it, or a link to lock it.
export async function lockFirst(ctx, title) {
  const house = await controlledGreenhouse(ctx);
  const lines = house ? [note(ctx.t("greenhouses.needLockNamed", { name: house.name }))] : [note(ctx.t("greenhouses.needLock"))];
  if (house && house.state === "taken") lines.push(note(ctx.t("greenhouses.takenHere", { name: house.name })));
  else lines.push(lockLink(ctx, house));
  return h("div", { class: "page" }, pageHead(title, ""), section(title, ...lines));
}
