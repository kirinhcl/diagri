// Why a compute attempt is stuck, as sentences: the reason's code, then (for an error) the error's
// own code, each through the catalog. The server's English goes into the technical details only.
import { messageParts } from "../messages.js";

const isCode = (value) => typeof value === "string" && value !== "";
const params = (value) => (value && typeof value === "object" && !Array.isArray(value) ? value : {});

// The error behind a stuck "error": its sentence and next step, or "unknown" when it has no code
// (an attempt from before codes) or a code this console does not know.
function errorLines(ctx, row) {
  const parts = isCode(row.error_code) ? messageParts(ctx, "compute_error", row.error_code, params(row.error_params)) : null;
  if (!parts || !parts.known) return { lines: [ctx.t("common.unknown")], entries: [] };
  const [code, args] = [parts.details[0][1], parts.details[parts.details.length - 1][1]];
  const entries = [[ctx.t("compute.tech.errorCode"), code], [ctx.t("compute.tech.errorParams"), args]];
  return { lines: [parts.text, parts.action].filter(Boolean), entries };
}

// { lines, entries }: the sentences to show and the entries for the one technical-details fold.
// An old row without a reason code shows a generic line.
export function stuckSentences(ctx, row) {
  const english = [[ctx.t("tech.serverMessage"), row.reason]];
  if (!isCode(row.reason_code)) return { lines: [ctx.t("compute.stuckGeneric")], entries: english };
  const parts = messageParts(ctx, "compute_stuck", row.reason_code, params(row.reason_params));
  const lines = [parts.text, parts.action].filter(Boolean);
  if (row.reason_code !== "error") return { lines, entries: [...parts.details, ...english] };
  const error = errorLines(ctx, row);
  return { lines: [...lines, ...error.lines], entries: [...parts.details, ...error.entries, ...english] };
}
