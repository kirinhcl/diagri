// Hash routes of the console.
const FLAT = ["login", "projects", "alerts", "evidence", "compute", "safety"];
const WITH_ID = { projects: ["project", "projectId"], rounds: ["round", "roundId"], stages: ["stage", "stageId"] };

function decode(part) {
  try {
    return decodeURIComponent(part);
  } catch {
    return null;
  }
}

export function parseHash(hash) {
  const path = String(hash || "").replace(/^#/, "");
  if (path === "" || path === "/") return { page: "inbox", params: {} };
  const parts = path.replace(/^\//, "").split("/");
  const [head, id] = parts;
  if (parts.length === 1 && FLAT.includes(head)) return { page: head, params: {} };
  if (parts.length === 2 && WITH_ID[head] && id) {
    const value = decode(id);
    if (value !== null) return { page: WITH_ID[head][0], params: { [WITH_ID[head][1]]: value } };
  }
  return { page: "not_found", params: {} };
}

export function hrefFor(page, params = {}) {
  if (page === "inbox") return "#/";
  if (FLAT.includes(page)) return `#/${page}`;
  for (const [segment, [name, key]] of Object.entries(WITH_ID)) {
    if (name === page) return `#/${segment}/${encodeURIComponent(params[key])}`;
  }
  return "#/";
}
