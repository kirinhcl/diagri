// In-memory drafts so a failed form keeps its values. Never written to storage.
const drafts = new Map();

export function saveDraft(key, values) {
  drafts.set(key, { ...values });
}

export function takeDraft(key) {
  if (!drafts.has(key)) return null;
  const values = drafts.get(key);
  drafts.delete(key);
  return values;
}

export function stripSecrets(values, secretNames) {
  const hidden = new Set(secretNames);
  return Object.fromEntries(Object.entries(values).filter(([name]) => !hidden.has(name)));
}
