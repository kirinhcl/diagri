// A plain data table: columns are [{label, cell: (row) => Node | string | null}].
import { h } from "./dom.js";

// With a label the wrapper becomes a focusable region, so a wide table can be scrolled by keyboard.
export function table(columns, rows, { label, rowProps } = {}) {
  const head = h("tr", {}, columns.map((column) => h("th", { attrs: { scope: "col" }, text: column.label })));
  const body = rows.map((row, index) => h("tr", rowProps ? rowProps(row) : {}, columns.map((column) => h("td", {}, column.cell(row, index)))));
  const attrs = label ? { role: "region", "aria-label": label, tabindex: 0 } : {};
  return h(
    "div",
    { class: "table-wrap", attrs },
    h("table", { class: "data-table" }, h("thead", {}, head), h("tbody", {}, body)),
  );
}
