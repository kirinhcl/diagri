// Following a device write to its result: GET /receipts/{request_id} every 2 s for at most 60 s.
// Pure apart from the timer in sleep(); the clock, the wait and the fetch can all be passed in.
export const RECEIPT_INTERVAL_MS = 2000;
export const RECEIPT_LIMIT_MS = 60000;

// ActionState of the server -> what the operator is told. pending and maybe_sent are not settled.
const OUTCOMES = new Map([
  ["confirmed", "applied"],
  ["unknown", "unknown"],
  ["failed", "failed"],
  ["void", "failed"],
]);

export function receiptOutcome(record) {
  const state = record && typeof record === "object" ? record.state : null;
  return OUTCOMES.get(String(state)) || null;
}

// Resolves after ms, or at once when the signal aborts; the timer never outlives the abort.
export function sleep(ms, signal) {
  return new Promise((resolve) => {
    if (signal && signal.aborted) return resolve();
    const done = () => {
      clearTimeout(timer);
      if (signal) signal.removeEventListener("abort", done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    if (signal) signal.addEventListener("abort", done, { once: true });
  });
}

// A request id the server accepts (^[a-zA-Z0-9_-]{8,100}$); a retry after re-auth reuses it.
export function newRequestId(randomUUID = () => globalThis.crypto.randomUUID()) {
  return `wb-${randomUUID()}`;
}

// No answer came (status 0), a server error (any 5xx, whatever its body says), or an answer that
// could not be read: the write may or may not have been done.
export function answerLost(error) {
  if (!error) return false;
  return error.status === 0 || error.status >= 500 || error.code === "network" || error.code === "server_error";
}

// Polls until the record settles, the time limit passes, or the page no longer wants it.
// Returns {outcome: "applied"|"unknown"|"failed"|"timeout"|"stopped", record, error}.
export async function pollReceipt({
  initial = null,
  fetchReceipt,
  onUpdate = () => {},
  signal = null,
  isActive = () => true,
  now = () => Date.now(),
  sleep: wait = sleep,
  intervalMs = RECEIPT_INTERVAL_MS,
  limitMs = RECEIPT_LIMIT_MS,
}) {
  const startedAt = now();
  const wanted = () => !(signal && signal.aborted) && isActive();
  let record = initial;
  let error = null;
  for (;;) {
    const outcome = receiptOutcome(record);
    if (outcome) return { outcome, record, error };
    if (!wanted()) return { outcome: "stopped", record, error };
    const left = limitMs - (now() - startedAt);
    if (left <= 0) return { outcome: "timeout", record, error };
    await wait(Math.min(intervalMs, left), signal);
    if (!wanted()) return { outcome: "stopped", record, error };
    try {
      record = await fetchReceipt();
      error = null;
    } catch (failure) {
      error = failure; // shown with the pending line, then tried again at the next tick
    }
    onUpdate({ record, error });
  }
}
