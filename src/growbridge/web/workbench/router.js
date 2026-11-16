// Hash routes of the console.
const FLAT = ["login", "environment", "projects", "alerts", "evidence", "compute", "safety"];
const WITH_ID = new Map([
  ["projects", ["project", "projectId"]],
  ["rounds", ["round", "roundId"]],
  ["stages", ["stage", "stageId"]],
]);

function decode(part) {
  try {
    return decodeURIComponent(part);
  } catch {
    return null;
  }
}

// Every page a signed-in operator can open; the sign-in page is separate.
export const PAGES = new Set(["inbox", "environment", "projects", "project", "round", "stage", "alerts", "evidence", "compute", "safety"]);

export function parseHash(hash) {
  const [path, query = ""] = String(hash || "").replace(/^#/, "").split("?");
  if (path === "" || path === "/") return { page: "inbox", params: {} };
  const parts = path.replace(/^\//, "").split("/");
  const [head, id] = parts;
  if (parts.length === 1 && head === "alerts") {
    const focus = new URLSearchParams(query).get("focus");
    return { page: head, params: focus ? { focus } : {} };
  }
  if (parts.length === 1 && FLAT.includes(head)) return { page: head, params: {} };
  if (parts.length === 2 && WITH_ID.has(head) && id) {
    const value = decode(id);
    const [page, key] = WITH_ID.get(head);
    if (value !== null) return { page, params: { [key]: value } };
  }
  return { page: "not_found", params: {} };
}

export function hrefFor(page, params = {}) {
  if (page === "inbox") return "#/";
  if (page === "alerts" && params.focus) return `#/alerts?focus=${encodeURIComponent(params.focus)}`;
  if (FLAT.includes(page)) return `#/${page}`;
  for (const [segment, [name, key]] of WITH_ID) {
    if (name === page) return `#/${segment}/${encodeURIComponent(params[key])}`;
  }
  throw new RangeError(`unknown page: ${String(page)}`);
}
