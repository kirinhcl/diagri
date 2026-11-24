// Greenhouses (multi-user): every greenhouse as free, yours or taken; lock a selection at once, release your own.
import { ApiError } from "../api.js";
import { h } from "../ui/dom.js";
import { table } from "../ui/table.js";
import { confirmedButton, errorBox, note, pageHead, section, showErrors, timeText } from "../ui/section.js";

const STATE_KEYS = { free: "greenhouses.state.free", mine: "greenhouses.state.mine", taken: "greenhouses.state.taken" };

function stateText(ctx, row) {
  return ctx.t(STATE_KEYS[row.state] || "common.unknown");
}

// The ids a lock refusal names ("already locked: gh-02, gh-03"), or none.
export function takenIds(error) {
  if (!(error instanceof ApiError) || error.code !== "lock_taken") return [];
  const listed = String(error.message || "").split(":")[1] || "";
  return listed.split(",").map((id) => id.trim()).filter(Boolean);
}

function releaseButton(ctx, row) {
  const label = ctx.t("greenhouses.release");
  const run = async () => {
    const body = { plants_removed: true }; // the dialog only confirms once that box is ticked
    await ctx.api.post(`/greenhouses/${encodeURIComponent(row.id)}/release`, body, { action: label });
    ctx.notify(ctx.t("greenhouses.released", { name: row.name }), "ok");
    ctx.reload();
  };
  const title = ctx.t("greenhouses.releaseTitle", { name: row.name });
  const tickLabel = ctx.t("greenhouses.releaseTick");
  return confirmedButton(ctx, { label, title, lines: [ctx.t("greenhouses.releaseLine")], run, tickLabel });
}

function checkbox(row, boxes) {
  const attrs = { type: "checkbox", name: "greenhouse", value: row.id, disabled: row.state !== "free", "aria-label": row.name };
  const box = h("input", { attrs });
  boxes.push(box);
  return box;
}

function columns(ctx, boxes) {
  const columnsList = [
    { label: ctx.t("greenhouses.pick"), cell: (row) => checkbox(row, boxes) },
    { label: ctx.t("greenhouses.name"), cell: (row) => row.name },
    { label: ctx.t("greenhouses.status"), cell: (row) => stateText(ctx, row) },
    { label: ctx.t("greenhouses.since"), cell: (row) => (row.locked_at ? timeText(ctx, row.locked_at) : "—") },
    { label: ctx.t("greenhouses.action"), cell: (row) => (row.state === "mine" ? releaseButton(ctx, row) : "") },
  ];
  if (ctx.me && ctx.me.role === "admin") columnsList.splice(3, 0, { label: ctx.t("greenhouses.holder"), cell: (row) => row.holder || "—" });
  return columnsList;
}

function lockForm(ctx, rows) {
  const box = errorBox();
  const takenNote = h("p", { class: "cell-sub", attrs: { role: "status" } });
  const label = ctx.t("greenhouses.lock");
  const button = h("button", { class: "button button-primary", attrs: { type: "submit" }, text: label });
  const boxes = [];
  const list = table(columns(ctx, boxes), rows, { label: ctx.t("nav.greenhouses") });
  const form = h("form", { class: "greenhouse-form" }, list, button, takenNote, box);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    box.hidden = true;
    takenNote.textContent = "";
    const ids = boxes.filter((input) => input.checked).map((input) => input.value);
    if (!ids.length) {
      takenNote.textContent = ctx.t("greenhouses.pickFirst");
      return;
    }
    try {
      await ctx.api.post("/greenhouses/lock", { greenhouse_ids: ids }, { action: label });
      ctx.notify(ctx.t("greenhouses.locked", { count: ids.length }), "ok");
      ctx.reload();
    } catch (error) {
      const taken = takenIds(error);
      if (taken.length) takenNote.textContent = ctx.t("greenhouses.takenMeanwhile", { ids: taken.join(", ") });
      showErrors(box, error, ctx);
    }
  });
  return form;
}

export async function render(ctx) {
  const data = await ctx.api.get("/greenhouses");
  const rows = data && Array.isArray(data.greenhouses) ? data.greenhouses : [];
  const body = rows.length ? lockForm(ctx, rows) : note(ctx.t("greenhouses.none"));
  const element = h("div", { class: "page greenhouses" }, pageHead(ctx.t("nav.greenhouses"), ctx.t("greenhouses.lead")), section(ctx.t("greenhouses.list"), body));
  return { element };
}
