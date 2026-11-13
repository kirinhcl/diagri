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

export function initialLang(stored, navigatorLanguage) {
  if (LANGS.includes(stored)) return stored;
  return String(navigatorLanguage || "").toLowerCase().startsWith("zh") ? "zh" : "en";
}
