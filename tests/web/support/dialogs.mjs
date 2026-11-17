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
