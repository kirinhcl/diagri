// Hash routes of the console.
const FLAT = ["login", "environment", "projects", "alerts", "evidence", "compute", "safety", "greenhouses", "admin"];
const WITH_ID = new Map([
  ["projects", ["project", "projectId"]],
  ["rounds", ["round", "roundId"]],
  ["stages", ["stage", "stageId"]],
  ["guide", ["guide", "sessionId"]],
]);

function decode(part) {
  try {
    return decodeURIComponent(part);
  } catch {
    return null;
  }
}

// The evidence page's selection (project, validity, variable, the time as of which, in epoch seconds)
// and the card to bring into view.
const EVIDENCE_PARAMS = ["projectId", "status", "variable", "asOf", "focus"];

function evidenceParams(query) {
  const found = new URLSearchParams(query);
  return Object.fromEntries(EVIDENCE_PARAMS.filter((name) => found.get(name)).map((name) => [name, found.get(name)]));
}

// Every page a signed-in operator can open; the sign-in page is separate.
export const PAGES = new Set(["inbox", "environment", "projects", "project", "round", "stage", "alerts", "evidence", "compute", "safety", "greenhouses", "admin", "guide"]);

export function parseHash(hash) {
  const [path, query = ""] = String(hash || "").replace(/^#/, "").split("?");
  if (path === "" || path === "/") return { page: "inbox", params: {} };
  const parts = path.replace(/^\//, "").split("/");
  const [head, id] = parts;
  if (parts.length === 1 && head === "alerts") {
    const focus = new URLSearchParams(query).get("focus");
    return { page: head, params: focus ? { focus } : {} };
  }
  if (parts.length === 1 && head === "evidence") return { page: head, params: evidenceParams(query) };
  if (parts.length === 1 && FLAT.includes(head)) return { page: head, params: {} };
  if (parts.length === 2 && WITH_ID.has(head) && id) {
    const value = decode(id);
    const [page, key] = WITH_ID.get(head);
    if (value !== null) return { page, params: { [key]: value } };
  }
  return { page: "not_found", params: {} };
}

// Where a newly signed-in operator starts: with multi-user and no greenhouse yet, at the greenhouses.
export function homeFor(me) {
  const lockless = Boolean(me && me.multi_user) && !(Array.isArray(me.greenhouses) && me.greenhouses.length);
  return hrefFor(lockless ? "greenhouses" : "inbox");
}

export function hrefFor(page, params = {}) {
  if (page === "inbox") return "#/";
  if (page === "alerts" && params.focus) return `#/alerts?focus=${encodeURIComponent(params.focus)}`;
  if (page === "evidence") return evidenceHref(params);
  if (FLAT.includes(page)) return `#/${page}`;
  for (const [segment, [name, key]] of WITH_ID) {
    if (name === page) return `#/${segment}/${encodeURIComponent(params[key])}`;
  }
  throw new RangeError(`unknown page: ${String(page)}`);
}

function evidenceHref(params) {
  const query = EVIDENCE_PARAMS.filter((name) => params[name]).map((name) => `${name}=${encodeURIComponent(params[name])}`);
  return query.length ? `#/evidence?${query.join("&")}` : "#/evidence";
}
