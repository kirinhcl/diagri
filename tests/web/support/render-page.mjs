// Renders console pages in node from tests/web/fixtures: a fake api answers each read by path as the
// fixtures README's table says (query strings ignored), records every call, and answers writes with {}.
import { readdirSync, readFileSync } from "node:fs";

import { ApiError } from "../../../src/growbridge/web/workbench/api.js";
import { makeT } from "../../../src/growbridge/web/workbench/i18n.js";
import { bindFormContext } from "../../../src/growbridge/web/workbench/ui/forms.js";
import { installFakeDom } from "./fake-dom.mjs";

export { installFakeDom };

const FIXTURE_DIR = new URL("../fixtures/", import.meta.url);
const PAGE_DIR = new URL("../../../src/growbridge/web/workbench/pages/", import.meta.url);
const DEFAULT_TIMEZONE = "Europe/Helsinki";

function deepFreeze(value) {
  if (value !== null && typeof value === "object") {
    for (const inner of Object.values(value)) deepFreeze(inner);
    Object.freeze(value);
  }
  return value;
}

// File name (e.g. "history.json") -> parsed JSON, frozen so no test can change another's data.
export const FIXTURES = Object.freeze(
  Object.fromEntries(
    readdirSync(FIXTURE_DIR)
      .filter((name) => name.endsWith(".json"))
      .sort()
      .map((name) => [name, deepFreeze(JSON.parse(readFileSync(new URL(name, FIXTURE_DIR), "utf8")))]),
  ),
);

// The stage and round waiting for review are told apart from the ended ones by their fixture ids.
const STAGE_PARTS = { "/run-sheet": "run-sheet", "/readings": "readings", "/measurements": "measurements", "/history": "history", "/manual-tasks": "manual-tasks" };
const ROUTES = [
  [/^\/me$/, () => "me.json"],
  [/^\/inbox$/, () => "inbox.json"],
  [/^\/projects$/, () => "projects.json"],
  [/^\/projects\/[^/]+$/, () => "project.json"],
  [/^\/projects\/[^/]+\/conversation$/, () => "conversation.json"],
  [/^\/holdouts$/, () => "holdouts.json"],
  [/^\/rounds\/([^/]+)$/, ([id], pending) => (id === pending.round ? "round-pending.json" : "round.json")],
  [/^\/rounds\/[^/]+\/report$/, () => "report.json"],
  [/^\/protocols\/[^/]+\/analysis$/, () => "analysis.json"],
  [/^\/stages\/([^/]+)(\/[a-z-]+)?$/, ([id, part], pending) => stageFixture(id, part, pending)],
  [/^\/experiments\/([^/]+)\/variables$/, ([id], pending) => (id === pending.experiment ? "variables-pending.json" : "variables.json")],
  [/^\/environment$/, () => "environment.json"],
  [/^\/capabilities$/, () => "capabilities.json"],
  [/^\/devices\/[^/]+\/notes$/, () => "device-notes.json"],
  [/^\/safety$/, () => "safety.json"],
  [/^\/alerts$/, () => "alerts.json"],
  [/^\/evidence$/, () => "evidence.json"],
  [/^\/evidence\/relations$/, () => "evidence-relations.json"],
  [/^\/compute$/, () => "compute.json"],
  [/^\/greenhouses$/, () => "greenhouses.json"],
  [/^\/greenhouses\/[^/]+\/tests$/, () => "greenhouse-tests.json"],
  [/^\/admin\/operators$/, () => "admin-operators.json"],
  [/^\/admin\/locks$/, () => "admin-locks.json"],
  [/^\/guide\/sessions\/[^/]+$/, () => "guide-session.json"],
  [/^\/guide\/sessions\/[^/]+\/review$/, () => "guide-review.json"],
  [/^\/guide\/sessions\/[^/]+\/steps\/([a-z]+)$/, ([step]) => `guide-options-${step}.json`],
];

function stageFixture(id, part, pending) {
  const base = part === undefined ? "stage" : STAGE_PARTS[part];
  if (!base) return null;
  return `${base}${id === pending.stage ? "-pending" : ""}.json`;
}

function decoded(part) {
  try {
    return decodeURIComponent(part);
  } catch {
    return part;
  }
}

function fixtureFor(path, pending) {
  const bare = String(path).split("?")[0];
  for (const [pattern, pick] of ROUTES) {
    const match = pattern.exec(bare);
    if (match) return pick(match.slice(1).map((part) => (part === undefined ? undefined : decoded(part))), pending);
  }
  return null;
}

// `answers` maps a POST path to a function giving its answer (or throwing a refusal); others get {}.
// A key "GET <path>" (no query string) does the same for a read, before any fixture.
function fakeApi(files, answers = {}) {
  const pending = {
    round: files["round-pending.json"]?.round_id,
    stage: files["stage-pending.json"]?.stage_id,
    experiment: files["stage-pending.json"]?.experiment_id,
  };
  const calls = [];
  const get = async (path) => {
    const read = answers[`GET ${String(path).split("?")[0]}`];
    if (typeof read === "function") {
      calls.push({ method: "GET", path, fixture: null });
      return read();
    }
    const name = fixtureFor(path, pending);
    const found = name !== null && Object.hasOwn(files, name) && files[name] !== null;
    calls.push({ method: "GET", path, fixture: found ? name : null });
    if (!found) throw new ApiError(404, null, "HTTP 404");
    return structuredClone(files[name]);
  };
  const post = async (path, body = {}, options = {}) => {
    calls.push({ method: "POST", path, body: JSON.parse(JSON.stringify(body)), options }); // the body as sent
    const answer = answers[path];
    return typeof answer === "function" ? answer(body) : {};
  };
  return { get, post, calls };
}

// `timezone: undefined` given on purpose means `me` has no time zone; left out, it is Europe/Helsinki.
function meWith(me, options) {
  const timezone = Object.hasOwn(options, "timezone") ? options.timezone : DEFAULT_TIMEZONE;
  const rest = Object.fromEntries(Object.entries(me).filter(([key]) => key !== "timezone"));
  return timezone === undefined ? rest : { ...rest, timezone };
}

// The page ctx of W/main.js makeCtx, plus `now` (fixed epoch seconds, or undefined). `fixtures`
// replaces fixture files by name; a file replaced by null is missing, so its read answers 404.
// Pages build DOM, so a fake DOM is installed when there is none.
export function testCtx(options = {}) {
  const { lang = "zh", fixtures = {}, now, answers = {} } = options;
  if (typeof document === "undefined") installFakeDom();
  const files = { ...FIXTURES, ...fixtures };
  const crumbs = [];
  return {
    api: fakeApi(files, answers),
    crumbs,
    t: makeT(lang),
    lang,
    me: meWith(files["me.json"], options),
    now,
    navigate: () => {},
    notify: () => {},
    reload: () => {},
    setLang: () => {},
    setBreadcrumbs: (items) => crumbs.splice(0, crumbs.length, ...items),
    setCounts: () => {},
  };
}

// Renders W/pages/<page>.js as main.js does, without its error views and without starting polls.
export async function renderPage(page, params = {}, options = {}) {
  if (!/^[a-z][a-z-]*$/.test(String(page))) throw new RangeError(`not a page name: ${String(page)}`);
  const ctx = testCtx(options);
  bindFormContext(ctx);
  const module = await import(new URL(`${page}.js`, PAGE_DIR).href);
  const result = await module.render(ctx, params);
  if (!result || !result.element) throw new Error(`${page}: render returned no element`);
  return { element: result.element, ctx, refresh: result.refresh };
}
