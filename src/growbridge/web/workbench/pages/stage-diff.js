// One difference between the run sheet and the device, as a sentence.
import { levelText } from "../format.js";
import { labelOr } from "../i18n.js";

const DASH = "—";

function valueText(t, item, value) {
  if (value === null || value === undefined) return DASH;
  if (item.field === "level") return levelText(t, item.channel, value);
  return String(value);
}

export function differenceText(t, item) {
  const row = item && typeof item === "object" ? item : {};
  return t("diff.text", {
    channel: labelOr(t, "channel", row.channel),
    field: labelOr(t, "diff.field", row.field),
    expected: valueText(t, row, row.expected),
    actual: valueText(t, row, row.actual),
  });
}
