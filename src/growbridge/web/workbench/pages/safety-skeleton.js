// The diff baseline for the approval dialog when no safety limits have been approved yet: nothing at all.
// Nothing here is a safety value (the form and the JSON fold both start empty, never from a default).
// tests/web/config-pages.test.mjs pins its shape.
export function safetySkeleton() {
  return { version: null, rules: [], frozen: { minutes: {}, max_gap_seconds: null } };
}
