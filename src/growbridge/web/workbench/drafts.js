// In-memory drafts so a failed form keeps its values. Never written to storage.
const drafts = new Map();

export function saveDraft(key, values) {
  drafts.set(key, { ...values });
}

export function hasDraft(key) {
  return drafts.has(key);
}

export function takeDraft(key) {
  if (!drafts.has(key)) return null;
  const values = drafts.get(key);
  drafts.delete(key);
  return values;
}

export function clearDrafts() {
  drafts.clear();
}

// A different operator must not inherit another's half-filled forms: true (and drafts gone) when
// someone other than the previous operator signed in. No previous operator means nothing to hand over.
export function handOver(previousOperator, operator) {
  const changed = Boolean(previousOperator) && previousOperator !== operator;
  if (changed) clearDrafts();
  return changed;
}

export function stripSecrets(values, secretNames) {
  const hidden = new Set(secretNames);
  return Object.fromEntries(Object.entries(values).filter(([name]) => !hidden.has(name)));
}
