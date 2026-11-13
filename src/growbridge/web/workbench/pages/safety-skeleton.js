// The editor's start text when no safety limits have been approved yet: every field, every value null.
// Submitted unchanged the server refuses it (422), so it can never be approved by accident.
// tests/web/config-pages.test.mjs checks the field names against SafetyConfig in archive/models.py.
export function safetySkeleton() {
  return {
    version: null,
    rules: [
      {
        id: null,
        sensor: null,
        unit: null,
        validity_seconds: null,
        trigger: { op: null, value: null },
        duration_seconds: null,
        action: { channel: null, level: null },
      },
    ],
    approved_by: null,
    approved_at: null,
  };
}
