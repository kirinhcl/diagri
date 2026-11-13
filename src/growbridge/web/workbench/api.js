// Request wrapper for the /wb routes: JSON, UI header, denial errors, one reauth retry.
const BASE = "/wb";

export class ApiError extends Error {
  constructor(status, code, message, fields = []) {
    super(message || code || "error");
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

async function readBody(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function toError(status, body) {
  const detail = body ? body.detail : null;
  if (status === 422 && Array.isArray(detail)) {
    const fields = detail.map((d) => ({ loc: (d.loc || []).map(String), msg: String(d.msg || "") }));
    return new ApiError(status, "validation", "validation", fields);
  }
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    return new ApiError(status, detail.code || null, detail.message || detail.code);
  }
  return new ApiError(status, null, `HTTP ${status}`);
}

export function createApi({ fetchImpl, askReauth, onSessionLost } = {}) {
  const doFetch = fetchImpl || ((...args) => fetch(...args));

  async function send(method, path, body) {
    const init = { method, headers: { "x-growbridge-ui": "1" } };
    if (method !== "GET") {
      init.headers["content-type"] = "application/json";
      init.body = JSON.stringify(body ?? {});
    }
    let response;
    try {
      response = await doFetch(BASE + path, init);
    } catch (cause) {
      throw new ApiError(0, "network", String(cause && cause.message ? cause.message : cause));
    }
    const data = await readBody(response);
    if (response.ok) return data;
    throw toError(response.status, data);
  }

  async function post(path, body = {}, { action } = {}) {
    try {
      return await send("POST", path, body);
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== "reauth_required" || !askReauth) {
        throw await sessionCheck(error);
      }
      const secret = await askReauth(action);
      if (secret === null || secret === undefined) throw error;
      await send("POST", "/reauth", { secret });
      return send("POST", path, body);
    }
  }

  async function sessionCheck(error) {
    if (error instanceof ApiError && error.code === "session" && onSessionLost) {
      await onSessionLost();
    }
    return error;
  }

  async function get(path) {
    try {
      return await send("GET", path);
    } catch (error) {
      throw await sessionCheck(error);
    }
  }

  return { get, post };
}

export function singleFlight(fn) {
  let pending = null;
  return (...args) => {
    if (pending) return pending;
    let result;
    try {
      result = Promise.resolve(fn(...args));
    } catch (error) {
      result = Promise.reject(error);
    }
    pending = result.finally(() => {
      pending = null;
    });
    return pending;
  };
}
