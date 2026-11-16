// Bilingual texts: makeT(lang) gives t(key, vars).
import en from "./i18n/en.js";
import zh from "./i18n/zh.js";

export const LANGS = ["zh", "en"];
const TABLES = { zh, en };

export function makeT(lang) {
  const table = TABLES[lang] || en;
  return (key, vars = {}) => {
    const text = table[key];
    if (typeof text !== "string") return key;
    return text.replace(/\{(\w+)\}/g, (whole, name) => (name in vars ? String(vars[name]) : whole));
  };
}

// The text for a code the server sent (state, event, alert kind, ...): "—" when there is no code,
// and "unknown" when the catalog has no text for it, never the key or the raw code. The caller
// puts the raw code in the technical details.
export function labelOr(t, prefix, value) {
  if (value === null || value === undefined || value === "") return "—";
  const key = `${prefix}.${value}`;
  const text = t(key);
  return text === key ? t("common.unknown") : text;
}

export function initialLang(stored, navigatorLanguage) {
  if (LANGS.includes(stored)) return stored;
  return String(navigatorLanguage || "").toLowerCase().startsWith("zh") ? "zh" : "en";
}
