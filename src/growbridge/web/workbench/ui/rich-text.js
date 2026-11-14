// The little Markdown the model roles write in their replies, built as DOM nodes: paragraphs,
// "- " and "1. " lists, "#" headings, **bold** and `code`. Everything else stays plain text, and
// no text ever becomes markup.
import { h } from "./dom.js";

const BULLET = /^\s*[-*•]\s+/;
const NUMBERED = /^\s*\d+[.)]\s+/;
const HEADING = /^\s*#{1,6}\s+/;
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`)/;

// Text with **bold** and `code` spans, as a list of nodes for h().
export function inline(text) {
  return String(text)
    .split(INLINE)
    .filter((part) => part !== "")
    .map((part) => {
      if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) return h("strong", { text: part.slice(2, -2) });
      if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) return h("code", { text: part.slice(1, -1) });
      return part;
    });
}

// The blocks of a text: { kind: "p" | "ul" | "ol" | "h", lines }. Consecutive list items of one
// kind form one list; a line that continues an item is added to it.
export function blocks(text) {
  const out = [];
  for (const raw of String(text).split("\n")) {
    const line = raw.trimEnd();
    const last = out[out.length - 1];
    if (!line.trim()) {
      if (last) last.closed = true;
      continue;
    }
    const kind = BULLET.test(line) ? "ul" : NUMBERED.test(line) ? "ol" : HEADING.test(line) ? "h" : "p";
    const content = line.replace(kind === "ul" ? BULLET : kind === "ol" ? NUMBERED : HEADING, "");
    if (kind === "h") out.push({ kind, lines: [content.trim()], closed: true });
    else if (last && !last.closed && last.kind === kind && kind !== "p") last.lines.push(content);
    else if (last && !last.closed && kind === "p" && (last.kind === "p" || /^\s{2,}/.test(raw))) {
      last.lines[last.lines.length - 1] += `\n${line.trim()}`; // a wrapped line or an item's continuation
    } else out.push({ kind, lines: [content], closed: false });
  }
  return out.map(({ kind, lines }) => ({ kind, lines }));
}

function withBreaks(text) {
  return text.split("\n").flatMap((part, i) => (i ? [h("br"), ...inline(part)] : inline(part)));
}

export function richText(text, className = "rich-text") {
  const nodes = blocks(text).map(({ kind, lines }) => {
    if (kind === "h") return h("p", { class: "rich-heading" }, inline(lines[0]));
    if (kind === "p") return h("p", {}, withBreaks(lines[0]));
    return h(kind, {}, lines.map((item) => h("li", {}, withBreaks(item))));
  });
  return h("div", { class: className }, nodes);
}
