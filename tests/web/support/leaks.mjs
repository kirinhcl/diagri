// Finds internal text in what a page shows: snake_case codes, hex ids, uuids, epoch seconds, raw JSON
// and catalog keys. Technical details (<details class="tech-details">) are where such text belongs,
// so they are not scanned.
import assert from "node:assert/strict";

import en from "../../../src/growbridge/web/workbench/i18n/en.js";
import { EXEMPTIONS } from "./leak-exemptions.mjs";
import { FIXTURES } from "./render-page.mjs";

const ELEMENT_NODE = 1;
const TEXT_NODE = 3;
const CONTEXT_CHARS = 30;

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// A catalog key that slipped through, e.g. report.labels.undefined: the first segment of a real key,
// then more segments. Addresses (my.csc.fi) and plain English do not match.
function keyPattern() {
  const heads = [...new Set(Object.keys(en).map((key) => key.split(".")[0]))].map(escapeRegExp);
  return new RegExp(`\\b(?:${heads.join("|")})\\.[A-Za-z]+(?:\\.[A-Za-z_]+)*\\b`);
}

export const LEAK_PATTERNS = Object.freeze({
  snake: /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/,
  hexId: /(?<![0-9a-f])[0-9a-f]{32,}(?![0-9a-f])/i, // no \b: round_9d38… has no word boundary between _ and 9
  uuid: /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i,
  epoch: /\b1\d{9}(?:\.\d+)?\b/,
  payload: /\{\s*"/,
  i18nKey: keyPattern(),
});

const isTechDetails = (node) => node.localName === "details" && (node.getAttribute("class") || "").split(/\s+/).includes("tech-details");

function collect(node, parts) {
  if (node.nodeType === TEXT_NODE) {
    parts.push(node.textContent);
    return;
  }
  const isElement = node.nodeType === ELEMENT_NODE;
  if (isElement && isTechDetails(node)) return;
  parts.push(" ", (isElement && node.getAttribute("aria-label")) || "");
  for (const child of node.childNodes) collect(child, parts);
  parts.push(" ");
}

// Text nodes and aria-labels, a space between elements; never title attributes or technical details.
export function visibleText(node) {
  const parts = [];
  collect(node, parts);
  return parts.join("").replace(/\s+/g, " ").trim();
}

// Each exempt string is cut out (longest first, leaving a space) before the patterns are applied.
function withoutExempt(text, exempt) {
  for (const item of exempt) if (typeof item !== "string") throw new TypeError(`exempt strings only: ${String(item)}`);
  const longestFirst = exempt.filter((item) => item.length > 0).sort((a, b) => b.length - a.length);
  return longestFirst.reduce((rest, item) => rest.split(item).join(" "), String(text));
}

// Every match of every kind, in LEAK_PATTERNS order and then in text order.
export function findLeaks(text, exempt = []) {
  const scanned = withoutExempt(text, exempt);
  return Object.entries(LEAK_PATTERNS).flatMap(([kind, pattern]) =>
    [...scanned.matchAll(new RegExp(pattern.source, `${pattern.flags}g`))].map((found) => ({ kind, match: found[0] })),
  );
}

function around(text, match) {
  const at = text.indexOf(match);
  if (at < 0) return "";
  return text.slice(Math.max(0, at - CONTEXT_CHARS), at + match.length + CONTEXT_CHARS);
}

export function assertNoLeaks(node, exempt = []) {
  const text = visibleText(node);
  const leaks = findLeaks(text, exempt);
  if (leaks.length === 0) return;
  const lines = leaks.map(({ kind, match }) => `  ${kind}: ${match}   in "…${around(text, match)}…"`);
  assert.fail(`${leaks.length} piece(s) of internal text shown:\n${lines.join("\n")}`);
}

// Path syntax: "a.b" and "a[*].b" only; "[*]" takes every item of an array.
const SEGMENT = /^([^.[\]]*)(\[\*\])?$/;

function valuesAt(root, path) {
  return String(path)
    .split(".")
    .reduce(
      (values, segment) => {
        const parsed = SEGMENT.exec(segment);
        if (!parsed || (!parsed[1] && !parsed[2])) throw new Error(`unsupported exemption path: ${path}`);
        const [, key, every] = parsed;
        const owned = (value) => (value !== null && typeof value === "object" && Object.hasOwn(value, key) ? [value[key]] : []);
        const stepped = key ? values.flatMap(owned) : values;
        return every ? stepped.flatMap((value) => (Array.isArray(value) ? value : [])) : stepped;
      },
      [root],
    );
}

// The fixture strings that `exemptions` let `page` show.
export function exemptStrings(page, fixtures = FIXTURES, exemptions = EXEMPTIONS) {
  const found = exemptions
    .filter((entry) => entry.page === page)
    .flatMap((entry) => {
      if (!Object.hasOwn(fixtures, entry.fixture)) throw new Error(`exemption for ${page}: no fixture ${entry.fixture}`);
      return valuesAt(fixtures[entry.fixture], entry.path);
    })
    .filter((value) => typeof value === "string");
  return [...new Set(found)];
}
