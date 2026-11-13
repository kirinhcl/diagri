import test from "node:test";
import assert from "node:assert/strict";
import { ApiError, createApi, singleFlight } from "../../src/growbridge/web/workbench/api.js";

function reply(status, body) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return { ok: status >= 200 && status < 300, status, text: async () => text };
}

function fakeFetch(responses) {
  const calls = [];
  const impl = async (url, init = {}) => {
    calls.push({ url, init });
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return next;
  };
  impl.calls = calls;
  return impl;
}

const denial = (code) => reply(403, { detail: { code, message: code } });

test("post sends JSON and the UI header", async () => {
  const f = fakeFetch([reply(200, { ok: true })]);
  const api = createApi({ fetchImpl: f });
  const out = await api.post("/pause", { a: 1 });
  assert.deepEqual(out, { ok: true });
  assert.equal(f.calls[0].url, "/wb/pause");
  assert.equal(f.calls[0].init.method, "POST");
  assert.equal(f.calls[0].init.headers["x-growbridge-ui"], "1");
  assert.equal(f.calls[0].init.headers["content-type"], "application/json");
  assert.equal(f.calls[0].init.body, JSON.stringify({ a: 1 }));
});

test("a denial becomes an ApiError with its code", async () => {
  const f = fakeFetch([reply(409, { detail: { code: "state", message: "m" } })]);
  const api = createApi({ fetchImpl: f });
  await assert.rejects(api.get("/inbox"), (e) => {
    assert.ok(e instanceof ApiError);
    assert.equal(e.status, 409);
    assert.equal(e.code, "state");
    return true;
  });
});

test("422 keeps the field errors", async () => {
  const detail = [{ loc: ["body", "name"], msg: "field required" }];
  const f = fakeFetch([reply(422, { detail })]);
  const api = createApi({ fetchImpl: f });
  await assert.rejects(api.post("/x", {}), (e) => {
    assert.equal(e.code, "validation");
    assert.deepEqual(e.fields[0].loc, ["body", "name"]);
    assert.equal(e.fields[0].msg, "field required");
    return true;
  });
});

test("a network failure becomes code network", async () => {
  const f = fakeFetch([new TypeError("failed")]);
  const api = createApi({ fetchImpl: f });
  await assert.rejects(api.get("/inbox"), (e) => e.code === "network");
});

test("retries once after reauth", async () => {
  const f = fakeFetch([denial("reauth_required"), reply(200, {}), reply(200, { done: 1 })]);
  const seen = [];
  const api = createApi({
    fetchImpl: f,
    askReauth: async (action) => {
      seen.push(action);
      return "secret";
    },
  });
  const out = await api.post("/stages/s1/start", {}, { action: "start" });
  assert.deepEqual(out, { done: 1 });
  assert.deepEqual(seen, ["start"]);
  assert.equal(f.calls.length, 3);
  assert.equal(f.calls[1].url, "/wb/reauth");
  assert.equal(f.calls[1].init.body, JSON.stringify({ secret: "secret" }));
});

test("a second reauth_required is not retried again", async () => {
  const f = fakeFetch([denial("reauth_required"), reply(200, {}), denial("reauth_required")]);
  let asked = 0;
  const api = createApi({
    fetchImpl: f,
    askReauth: async () => {
      asked += 1;
      return "s";
    },
  });
  await assert.rejects(api.post("/x"), (e) => e.code === "reauth_required");
  assert.equal(asked, 1);
  assert.equal(f.calls.length, 3);
});

test("a cancelled reauth sends nothing more", async () => {
  const f = fakeFetch([denial("reauth_required")]);
  const api = createApi({ fetchImpl: f, askReauth: async () => null });
  await assert.rejects(api.post("/x"), (e) => e.code === "reauth_required");
  assert.equal(f.calls.length, 1);
});

test("a lost session calls onSessionLost", async () => {
  const f = fakeFetch([reply(401, { detail: { code: "session", message: "m" } })]);
  let lost = 0;
  const api = createApi({ fetchImpl: f, onSessionLost: () => (lost += 1) });
  await assert.rejects(api.get("/me"), (e) => e.code === "session");
  assert.equal(lost, 1);
});

test("singleFlight ignores calls while one is pending", async () => {
  let n = 0;
  let release;
  const fn = singleFlight(
    () =>
      new Promise((resolve) => {
        n += 1;
        release = resolve;
      }),
  );
  const a = fn();
  const b = fn();
  assert.equal(a, b);
  assert.equal(n, 1);
  release(1);
  await a;
  const c = fn();
  assert.equal(n, 2);
  release(2);
  await c;
});

const lostSession = () => reply(401, { detail: { code: "session", message: "m" } });

test("a session error during the retry calls onSessionLost", async () => {
  const f = fakeFetch([denial("reauth_required"), reply(200, {}), lostSession()]);
  let lost = 0;
  const api = createApi({ fetchImpl: f, askReauth: async () => "s", onSessionLost: () => (lost += 1) });
  await assert.rejects(api.post("/x"), (e) => e.code === "session");
  assert.equal(lost, 1);
});

test("a session error from POST /reauth calls onSessionLost and does not retry", async () => {
  const f = fakeFetch([denial("reauth_required"), lostSession()]);
  let lost = 0;
  const api = createApi({ fetchImpl: f, askReauth: async () => "s", onSessionLost: () => (lost += 1) });
  await assert.rejects(api.post("/x"), (e) => e.code === "session");
  assert.equal(lost, 1);
  assert.equal(f.calls.length, 2);
});

test("a failed reauth (403) does not retry the original request", async () => {
  const f = fakeFetch([denial("reauth_required"), denial("session_wrong")]);
  const api = createApi({ fetchImpl: f, askReauth: async () => "bad" });
  await assert.rejects(api.post("/x"), (e) => e.status === 403 && e.code === "session_wrong");
  assert.equal(f.calls.length, 2);
});

test("an HTML error page becomes a network error with its status", async () => {
  const f = fakeFetch([reply(502, "<html>Bad Gateway</html>"), reply(503, "")]);
  const api = createApi({ fetchImpl: f });
  await assert.rejects(api.get("/x"), (e) => e.code === "network" && e.status === 502);
  await assert.rejects(api.get("/x"), (e) => e.code === "network" && e.status === 503);
});

test("a 2xx response that is not JSON is an error", async () => {
  const f = fakeFetch([reply(200, "<html>oops</html>"), reply(204, "")]);
  const api = createApi({ fetchImpl: f });
  await assert.rejects(api.get("/x"), (e) => e.code === "network" && e.status === 200);
  assert.equal(await api.get("/x"), null);
});
