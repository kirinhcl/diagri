// Answers the console's <dialog> prompts in page tests. Answers queue up and apply, in order, to the
// dialogs opened next (or to one that is already open and waiting). An unused answer stays queued, so
// a test that queues one must open a dialog for it.

function documentOrThrow() {
  if (typeof document === "undefined") throw new Error("install the fake DOM (testCtx) before answering dialogs");
  return document;
}

// true confirms, false or null cancels, a string fills the first text box and then confirms.
export function answerNextDialog(answer) {
  const doc = documentOrThrow();
  doc.dialogAnswers.push(answer);
  doc.flushDialogs();
}

// The dialogs that are open right now, so a test can read their title and lines.
export function openDialogs() {
  return documentOrThrow().openDialogElements();
}

// Every test file that answers dialogs must call both of these in afterEach: the fake document is
// shared by the whole file, so a stale answer would silently decide a later test's dialog.
export function assertNoPendingDialogAnswers() {
  const left = typeof document === "undefined" ? [] : document.dialogAnswers;
  if (left.length) throw new Error(`${left.length} queued dialog answer(s) were never used`);
}

// Clears the queue and closes (cancelling) any dialog still open.
export function resetDialogs() {
  if (typeof document === "undefined") return;
  document.dialogAnswers.length = 0;
  for (const dialog of document.openDialogElements()) dialog.close();
}
