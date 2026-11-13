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

// Returns {empty, data, valid}: an empty body is fine, a non-JSON body is not.
async function readBody(response) {
  let text = "";
  try {
    text = await response.text();
  } catch {
    return { empty: false, data: null, valid: false };
  }
  if (text.trim() === "") return { empty: true, data: null, valid: true };
  try {
    return { empty: false, data: JSON.parse(text), valid: true };
  } catch {
    return { empty: false, data: null, valid: false };
  }
}

function toError(status, body) {
  // No 5xx is a definitive refusal: whatever its body says, the action may or may not have happened.
  if (status >= 500) return new ApiError(status, "server_error", `HTTP ${status}`);
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
    // An answer came, but not one that says what happened: "network" is kept for no answer at all.
    const { data, valid } = await readBody(response);
    if (!valid) throw new ApiError(response.status, "server_error", `HTTP ${response.status}: not JSON`);
    if (response.ok) return data;
    if (data === null) throw new ApiError(response.status, "server_error", `HTTP ${response.status}`);
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
      await confirmSecret(secret);
      try {
        return await send("POST", path, body);
      } catch (retryError) {
        throw await sessionCheck(retryError);
      }
    }
  }

  // POST /reauth answers 401 "session" for a wrong secret too, so probe /me to tell the cases apart.
  async function confirmSecret(secret) {
    try {
      await send("POST", "/reauth", { secret });
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== "session") throw error;
      try {
        await send("GET", "/me");
      } catch (probeError) {
        throw await sessionCheck(probeError.code === "session" ? error : probeError);
      }
      throw new ApiError(401, "reauth_failed", "reauth_failed");
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
