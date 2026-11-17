// A small DOM for rendering console pages in node, with no browser and no jsdom. It holds only what
// the pages use while they render; a page that needs more makes "every Batch 1 page renders" fail.
// Events do not bubble, and requestAnimationFrame callbacks are kept but never run: no page timer
// or poll starts in a test.
const HTML_NS = "http://www.w3.org/1999/xhtml";
const ELEMENT_NODE = 1;
const TEXT_NODE = 3;
const DOCUMENT_NODE = 9;
const FRAGMENT_NODE = 11;

const documentOf = (node) => node.ownerDocument || node;

// What browsers return for children (HTMLCollection) and childNodes (NodeList): indexable, with a
// length, item(i) and iteration, but none of the Array methods (NodeList alone adds forEach).
export class FakeCollection {
  constructor(items, { withForEach = false } = {}) {
    items.forEach((item, index) => Object.defineProperty(this, index, { value: item, enumerable: true }));
    Object.defineProperty(this, "length", { value: items.length });
    Object.defineProperty(this, "item", { value: (index) => items[index] ?? null });
    Object.defineProperty(this, Symbol.iterator, { value: () => items[Symbol.iterator]() });
    if (withForEach) Object.defineProperty(this, "forEach", { value: (callback, thisArg) => items.forEach(callback, thisArg) });
  }
}

class FakeNode extends EventTarget {
  #kids = [];

  constructor(ownerDocument, nodeType, nodeName) {
    super();
    this.ownerDocument = ownerDocument;
    this.nodeType = nodeType;
    this.nodeName = nodeName;
    this.parentNode = null;
  }

  get childNodes() {
    return new FakeCollection(this.#kids, { withForEach: true });
  }

  // The children as a real array, for this fake's own bookkeeping (never exposed to pages).
  kidList() {
    return [...this.#kids];
  }

  get firstChild() {
    return this.#kids[0] ?? null;
  }

  get lastChild() {
    return this.#kids.at(-1) ?? null;
  }

  get parentElement() {
    return this.parentNode && this.parentNode.nodeType === ELEMENT_NODE ? this.parentNode : null;
  }

  get nextSibling() {
    return this.parentNode ? (this.parentNode.kidList()[this.parentNode.kidList().indexOf(this) + 1] ?? null) : null;
  }

  get previousSibling() {
    return this.parentNode ? (this.parentNode.kidList()[this.parentNode.kidList().indexOf(this) - 1] ?? null) : null;
  }

  get isConnected() {
    let root = this;
    while (root.parentNode) root = root.parentNode;
    return root === documentOf(this);
  }

  get textContent() {
    return this.#kids.map((kid) => kid.textContent).join("");
  }

  set textContent(value) {
    const text = value === null || value === undefined ? "" : String(value);
    this.replaceChildren(...(text === "" ? [] : [text]));
  }

  contains(other) {
    for (let node = other; node; node = node.parentNode) if (node === this) return true;
    return false;
  }

  insertBefore(node, reference) {
    if (node instanceof FakeNode && node.nodeType === FRAGMENT_NODE) {
      for (const kid of node.childNodes) this.insertBefore(kid, reference);
      return node;
    }
    if (!(node instanceof FakeNode)) throw new TypeError(`not a node: ${String(node)}`);
    if (node === reference) return node;
    if (node.contains(this)) throw new Error("HierarchyRequestError: a node cannot hold its own ancestor");
    node.remove();
    const at = reference === null || reference === undefined ? this.#kids.length : this.#kids.indexOf(reference);
    if (at < 0) throw new Error("NotFoundError: the reference node is not a child");
    this.#kids.splice(at, 0, node);
    node.parentNode = this;
    return node;
  }

  appendChild(node) {
    return this.insertBefore(node, null);
  }

  removeChild(node) {
    const at = this.#kids.indexOf(node);
    if (at < 0) throw new Error("NotFoundError: not a child of this node");
    this.#kids.splice(at, 1);
    node.parentNode = null;
    return node;
  }

  #asNode(item) {
    return item instanceof FakeNode ? item : documentOf(this).createTextNode(String(item));
  }

  append(...items) {
    for (const item of items) this.appendChild(this.#asNode(item));
  }

  prepend(...items) {
    const first = this.firstChild;
    for (const item of items) this.insertBefore(this.#asNode(item), first);
  }

  replaceChildren(...items) {
    while (this.firstChild) this.removeChild(this.firstChild);
    this.append(...items);
  }

  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
  }
}

class FakeText extends FakeNode {
  constructor(ownerDocument, data) {
    super(ownerDocument, TEXT_NODE, "#text");
    this.data = String(data);
  }

  get nodeValue() {
    return this.data;
  }

  set nodeValue(value) {
    this.data = String(value ?? "");
  }

  get textContent() {
    return this.data;
  }

  set textContent(value) {
    this.data = String(value ?? "");
  }
}

class FakeFragment extends FakeNode {
  constructor(ownerDocument) {
    super(ownerDocument, FRAGMENT_NODE, "#document-fragment");
  }
}

// Properties that mirror an attribute, as in the browser.
const STRING_PROPERTIES = { id: "id", className: "class", name: "name", htmlFor: "for" };
const BOOLEAN_PROPERTIES = { hidden: "hidden", disabled: "disabled", required: "required", checked: "checked", selected: "selected", open: "open" };

class FakeElement extends FakeNode {
  #attributes = new Map();
  #typedValue = undefined; // what a script (or a person) put into a form control

  constructor(ownerDocument, namespaceURI, qualifiedName) {
    const name = String(qualifiedName);
    const isHtml = namespaceURI === HTML_NS;
    super(ownerDocument, ELEMENT_NODE, isHtml ? name.toUpperCase() : name);
    this.namespaceURI = namespaceURI;
    this.localName = isHtml ? name.toLowerCase() : name;
    this.tagName = this.nodeName;
    this.style = {};
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.clientHeight = 0;
  }

  #key(name) {
    return this.namespaceURI === HTML_NS ? String(name).toLowerCase() : String(name);
  }

  getAttribute(name) {
    const key = this.#key(name);
    return this.#attributes.has(key) ? this.#attributes.get(key) : null;
  }

  setAttribute(name, value) {
    this.#attributes.set(this.#key(name), String(value));
  }

  removeAttribute(name) {
    this.#attributes.delete(this.#key(name));
  }

  hasAttribute(name) {
    return this.#attributes.has(this.#key(name));
  }

  toggleAttribute(name, force) {
    const on = force === undefined ? !this.hasAttribute(name) : Boolean(force);
    if (on) this.setAttribute(name, "");
    else this.removeAttribute(name);
    return on;
  }

  getAttributeNames() {
    return [...this.#attributes.keys()];
  }

  get children() {
    return new FakeCollection(this.kidList().filter((node) => node.nodeType === ELEMENT_NODE));
  }

  get classList() {
    const read = () => (this.getAttribute("class") || "").split(/\s+/).filter(Boolean);
    const write = (names) => this.setAttribute("class", names.join(" "));
    const add = (...names) => write([...new Set([...read(), ...names])]);
    const remove = (...names) => write(read().filter((name) => !names.includes(name)));
    const contains = (name) => read().includes(name);
    const toggle = (name, force) => {
      const on = force === undefined ? !contains(name) : Boolean(force);
      if (on) add(name);
      else remove(name);
      return on;
    };
    return { add, remove, contains, toggle };
  }

  // A form control's value: what was typed or set, else what its markup says.
  get value() {
    if (this.#typedValue !== undefined) return this.#typedValue;
    if (this.localName === "textarea") return this.textContent;
    if (this.localName === "option") return this.getAttribute("value") ?? this.textContent;
    if (this.localName === "select") {
      const options = optionsOf(this);
      const chosen = options.find((option) => option.hasAttribute("selected")) || options[0];
      return chosen ? chosen.value : "";
    }
    return this.getAttribute("value") ?? "";
  }

  set value(value) {
    this.#typedValue = value === null || value === undefined ? "" : String(value);
  }

  focus() {
    this.ownerDocument.activeElement = this;
  }

  blur() {
    if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = this.ownerDocument.body;
  }

  // <dialog>: showModal opens it (answering at once, in a microtask, if a test queued an answer);
  // close() fires "close" like the browser does. Which button decides is dialog.js's business.
  showModal() {
    this.setAttribute("open", "");
    queueMicrotask(() => this.ownerDocument.flushDialogs());
  }

  close(returnValue) {
    if (!this.hasAttribute("open")) return;
    this.removeAttribute("open");
    if (returnValue !== undefined) this.returnValue = String(returnValue);
    this.dispatchEvent(new Event("close"));
  }
}

function descendants(node) {
  return node.kidList().flatMap((child) => [child, ...descendants(child)]);
}

// A person's answer: a string is typed into the first text box, then the form is submitted (the
// confirm button); false or null presses cancel, which just closes the dialog.
function applyAnswer(dialog, answer) {
  if (answer === false || answer === null) {
    dialog.close();
    return;
  }
  const all = descendants(dialog);
  if (typeof answer === "string") {
    const box = all.find((node) => node.localName === "textarea" || (node.localName === "input" && node.getAttribute("type") !== "hidden"));
    if (box) box.value = answer;
  }
  const form = all.find((node) => node.localName === "form");
  (form || dialog).dispatchEvent(new Event("submit", { cancelable: true }));
}

for (const [property, attribute] of Object.entries(STRING_PROPERTIES)) {
  Object.defineProperty(FakeElement.prototype, property, {
    get() {
      return this.getAttribute(attribute) ?? "";
    },
    set(value) {
      this.setAttribute(attribute, value);
    },
  });
}

for (const [property, attribute] of Object.entries(BOOLEAN_PROPERTIES)) {
  Object.defineProperty(FakeElement.prototype, property, {
    get() {
      return this.hasAttribute(attribute);
    },
    set(value) {
      this.toggleAttribute(attribute, Boolean(value));
    },
  });
}

function optionsOf(element) {
  return [...element.children].flatMap((child) => (child.localName === "option" ? [child] : optionsOf(child)));
}

class FakeDocument extends FakeNode {
  constructor() {
    super(null, DOCUMENT_NODE, "#document");
    this.documentElement = this.createElement("html");
    this.head = this.createElement("head");
    this.body = this.createElement("body");
    this.documentElement.append(this.head, this.body);
    this.appendChild(this.documentElement);
    this.activeElement = this.body;
    this.defaultView = null;
    this.dialogAnswers = [];
  }

  openDialogElements() {
    return descendants(this).filter((node) => node.localName === "dialog" && node.hasAttribute("open"));
  }

  // Gives each waiting dialog the next queued answer, oldest dialog first.
  flushDialogs() {
    for (const dialog of this.openDialogElements()) {
      if (!this.dialogAnswers.length) return;
      applyAnswer(dialog, this.dialogAnswers.shift());
    }
  }

  createElement(tagName) {
    return new FakeElement(this, HTML_NS, tagName);
  }

  createElementNS(namespaceURI, qualifiedName) {
    return new FakeElement(this, namespaceURI, qualifiedName);
  }

  createTextNode(data) {
    return new FakeText(this, data);
  }

  createDocumentFragment() {
    return new FakeFragment(this);
  }
}

class MemoryStorage {
  #items = new Map();

  get length() {
    return this.#items.size;
  }

  key(index) {
    return [...this.#items.keys()][index] ?? null;
  }

  getItem(key) {
    return this.#items.has(String(key)) ? this.#items.get(String(key)) : null;
  }

  setItem(key, value) {
    this.#items.set(String(key), String(value));
  }

  removeItem(key) {
    this.#items.delete(String(key));
  }

  clear() {
    this.#items.clear();
  }
}

function animationFrames() {
  const waiting = new Map();
  let last = 0;
  const requestAnimationFrame = (callback) => {
    last += 1;
    waiting.set(last, callback);
    return last;
  };
  const cancelAnimationFrame = (id) => {
    waiting.delete(id);
  };
  return { requestAnimationFrame, cancelAnimationFrame };
}

const GLOBAL_NAMES = ["document", "window", "navigator", "localStorage", "location", "requestAnimationFrame", "cancelAnimationFrame"];

// Puts a fresh document and its browser globals on globalThis; restore() puts back what was there.
// `clipboard` is navigator.clipboard (an object with writeText); left out, there is none.
export function installFakeDom({ clipboard } = {}) {
  const document = new FakeDocument();
  const navigator = { language: "zh-CN", userAgent: "fake-dom", ...(clipboard === undefined ? {} : { clipboard }) };
  const location = { hash: "", href: "http://localhost/wb/", pathname: "/wb/", search: "" };
  const shared = { document, navigator, localStorage: new MemoryStorage(), location, ...animationFrames() };
  const window = Object.assign(new EventTarget(), shared);
  window.window = window;
  document.defaultView = window;
  const globals = { ...shared, window };
  const saved = GLOBAL_NAMES.map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)]);
  for (const name of GLOBAL_NAMES) {
    Object.defineProperty(globalThis, name, { value: globals[name], configurable: true, enumerable: true, writable: true });
  }
  let restored = false;
  return {
    restore() {
      if (restored) return;
      restored = true;
      for (const [name, descriptor] of saved) {
        if (descriptor) Object.defineProperty(globalThis, name, descriptor);
        else delete globalThis[name];
      }
    },
  };
}
