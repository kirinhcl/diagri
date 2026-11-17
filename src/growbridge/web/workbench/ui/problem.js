// What main.js shows instead of a page: what went wrong in plain words, its facts folded into the
// technical details (never the raw error in the page), and a retry when there is something to retry.
import { h } from "./dom.js";
import { errorDetail } from "./forms.js";
import { techDetails } from "./section.js";

// lines: the plain sentences (the title is the heading, so a line equal to it is left out).
// onRetry: called by the retry button; none without it. details: [label, value] pairs.
export function problemView(t, lines, { onRetry = null, details = [] } = {}) {
  const title = t("error.title");
  const retry = onRetry ? h("button", { class: "button button-primary", attrs: { type: "button" }, on: { click: onRetry }, text: t("common.retry") }) : null;
  return h(
    "section",
    { class: "wb-problem", attrs: { role: "alert" } },
    h("h1", { text: title }),
    lines.filter((line) => line !== title).map((line) => h("p", { text: line })),
    techDetails(t, details),
    retry,
  );
}

// A page module that would not load or did not render: one generic sentence; the error, if any, is a detail.
export function loadFailedView(t, error, onRetry) {
  return problemView(t, [t("page.loadFailed")], { onRetry, details: error ? errorDetail(error, t) : [] });
}
