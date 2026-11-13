// Deep comparison of two configuration values into a flat change list.

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function childPath(path, key) {
  if (typeof key === "number") return `${path}[${key}]`;
  return path ? `${path}.${key}` : key;
}

function keysOf(before, after) {
  if (Array.isArray(before)) {
    return Array.from({ length: Math.max(before.length, after.length) }, (_, i) => i);
  }
  return [...new Set([...Object.keys(before), ...Object.keys(after)])];
}

function walk(before, after, path, out) {
  const bothArrays = Array.isArray(before) && Array.isArray(after);
  const bothObjects = isPlainObject(before) && isPlainObject(after);
  if (bothArrays || bothObjects) {
    for (const key of keysOf(before, after)) {
      walk(before[key], after[key], childPath(path, key), out);
    }
    return;
  }
  if (!Object.is(before, after)) out.push({ path, before, after });
}

export function configDiff(before, after) {
  const out = [];
  walk(before, after, "", out);
  return out;
}
