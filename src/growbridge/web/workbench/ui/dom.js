// Tiny DOM builders. Text goes in through text nodes and attributes only, never as markup.
const SVG_NS = "http://www.w3.org/2000/svg";

function setAttributes(el, attrs) {
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === false || value === null || value === undefined) continue;
    el.setAttribute(name, value === true ? "" : String(value));
  }
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(typeof child === "object" ? child : document.createTextNode(String(child)));
  }
}

// h("a", { class: "nav-link", attrs: { href }, on: { click }, text }, ...children)
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  const { class: className, attrs, on, text } = props || {};
  if (className) el.setAttribute("class", Array.isArray(className) ? className.filter(Boolean).join(" ") : className);
  setAttributes(el, attrs);
  for (const [event, handler] of Object.entries(on || {})) el.addEventListener(event, handler);
  if (text !== undefined && text !== null) el.textContent = String(text);
  append(el, children);
  return el;
}

export function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  setAttributes(el, attrs);
  append(el, children);
  return el;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}
