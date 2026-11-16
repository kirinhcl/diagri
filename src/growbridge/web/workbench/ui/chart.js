// Environment curves of a stage: one small SVG line chart per reading that has data.
// Downsampling and problem samples are always stated, never hidden (design §2, anti-goals).
import { METRICS, MIN_SPAN, gapLimit, paddedRange, seriesPoints, splitAtGaps } from "../chart-math.js";
import { DEFAULT_LEVEL_RANGES, formatDateTime, formatNumber } from "../format.js";
import { h, svg } from "./dom.js";
import { table } from "./table.js";

const WIDTH = 600;
const HEIGHT = 120;
const PAD = 8; // room for the markers at the edges
// layer: drawing order. The hover target is bigger than any mark and invisible until hovered.
const MARKS = {
  hit: { className: "chart-hit", radius: 6, layer: 0 },
  lone: { className: "chart-lone", radius: 3, layer: 1 },
  flagged: { className: "chart-flagged", radius: 3.5, layer: 2 },
};

// now: the page's clock (ctx.now), so the year rule here is the one timeText applies.
function timeLabel(epoch, timeZone, lang, now) {
  return formatDateTime(epoch, timeZone, lang, now ?? Date.now() / 1000);
}

function valueLabel(value, metric, lang) {
  return `${formatNumber(value, metric.precision, lang)} ${metric.unit}`.trim();
}

// The time span drawn: the stage's window, or the samples' own span when there is none.
function span(readings, samples) {
  const window = readings.window;
  if (window && Number.isFinite(window.start) && Number.isFinite(window.end)) {
    return { start: window.start, end: window.end };
  }
  const times = samples.map((sample) => sample.timestamp).filter(Number.isFinite);
  return { start: Math.min(...times), end: Math.max(...times) };
}

function pointTitle(t, point, metric, options) {
  const text = `${valueLabel(point.v, metric, options.lang)} · ${timeLabel(point.t, options.timeZone, options.lang, options.now)}`;
  return point.flagged ? `${text} · ${t("chart.flaggedPoint")}` : text;
}

// Every point gets a hover target with its value and time. A point with no neighbour on a line is a
// visible dot and a problem point a hollow circle; both are drawn last so no neighbour's hover target
// covers them.
function pointMarks(t, segments, metric, options) {
  const lone = new Set(segments.filter((segment) => segment.length === 1).map((segment) => segment[0]));
  const markOf = (point) => (point.flagged ? MARKS.flagged : lone.has(point) ? MARKS.lone : MARKS.hit);
  return segments
    .flat()
    .map((point) => ({ point, mark: markOf(point) }))
    .sort((a, b) => a.mark.layer - b.mark.layer)
    .map(({ point, mark }) => {
      const attrs = { cx: point.x.toFixed(1), cy: point.y.toFixed(1), r: mark.radius, class: mark.className };
      return svg("circle", attrs, svg("title", {}, pointTitle(t, point, metric, options)));
    });
}

// One polyline per run of points; the line is never drawn across a gap in the data.
function lines(segments) {
  const coordinates = (segment) => segment.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  return segments.filter((segment) => segment.length > 1).map((segment) => svg("polyline", { class: "chart-line", points: coordinates(segment) }));
}

// The scale beside the plot: top, middle and bottom value, each placed at its own height.
function yTicks(series, metric, options) {
  const [lo, hi] = series.domain;
  const total = HEIGHT + 2 * PAD;
  const labels = [hi, (lo + hi) / 2, lo].map((value, index) => {
    const label = h("span", { class: "chart-tick", text: formatNumber(value, metric.precision, options.lang) });
    label.style.top = `${(((PAD + (index * HEIGHT) / 2) / total) * 100).toFixed(2)}%`; // CSSOM: the CSP refuses style attributes
    return label;
  });
  return h("div", { class: "chart-yticks", attrs: { "aria-hidden": "true" } }, labels);
}

function xTicks(span, options) {
  return h(
    "div",
    { class: "chart-xticks", attrs: { "aria-hidden": "true" } },
    h("span", { class: "chart-tick", text: timeLabel(span.start, options.timeZone, options.lang, options.now) }),
    h("span", { class: "chart-tick", text: timeLabel(span.end, options.timeZone, options.lang, options.now) }),
  );
}

function dataTable(t, series, metric, options) {
  const columns = [
    { label: t("chart.table.time"), cell: (point) => timeLabel(point.t, options.timeZone, options.lang, options.now) },
    { label: t("chart.table.value"), cell: (point) => valueLabel(point.v, metric, options.lang) },
  ];
  return h(
    "details",
    { class: "chart-fold", attrs: { "data-fold": `${metric.key}:table` } },
    h("summary", { text: t("chart.table.title") }),
    table(columns, series.points, { label: t("chart.table.title") }),
  );
}

function plot(t, series, segments, metric, options) {
  const { points } = series;
  const summary = t("chart.summary", {
    metric: t(`metric.${metric.key}`),
    count: points.length,
    min: valueLabel(series.min, metric, options.lang),
    max: valueLabel(series.max, metric, options.lang),
  });
  return svg(
    "svg",
    { class: "chart-plot", viewBox: `0 0 ${WIDTH + 2 * PAD} ${HEIGHT + 2 * PAD}`, role: "img", "aria-label": summary },
    svg(
      "g",
      { transform: `translate(${PAD} ${PAD})` },
      svg("line", { class: "chart-rule", x1: 0, y1: 0, x2: WIDTH, y2: 0 }),
      svg("line", { class: "chart-rule", x1: 0, y1: HEIGHT, x2: WIDTH, y2: HEIGHT }),
      lines(segments),
      pointMarks(t, segments, metric, options),
    ),
  );
}

// The latest value is the current reading; its time and any problem with it are said beside it.
function chartHead(t, series, metric, options) {
  const latest = series.points[series.points.length - 1];
  const when = t("chart.latestAt", { time: timeLabel(latest.t, options.timeZone, options.lang, options.now) });
  const range = t("chart.range", {
    min: formatNumber(series.min, metric.precision, options.lang),
    max: formatNumber(series.max, metric.precision, options.lang),
    unit: metric.unit,
  });
  return h(
    "figcaption",
    { class: "chart-head" },
    h("span", { class: "chart-name", text: t(`metric.${metric.key}`) }),
    h("span", { class: "chart-value", text: valueLabel(latest.v, metric, options.lang) }),
    h("span", { class: "chart-meta", text: latest.flagged ? `${when} · ${t("chart.flaggedPoint")}` : when }),
    h("span", { class: "chart-meta", text: range }),
  );
}

// One line says what is drawn; what the marks mean is folded under "Legend".
function notes(t, readings, samples, options, hasGaps) {
  const said = [];
  const { start, end } = span(readings, samples);
  said.push(t("chart.window", { start: timeLabel(start, options.timeZone, options.lang, options.now), end: timeLabel(end, options.timeZone, options.lang, options.now) }));
  if (readings.downsampled) {
    said.push(t("chart.downsampled", { shown: samples.length, total: readings.total_samples }));
  }
  if (readings.flagged_total > 0) said.push(t("chart.flagged", { count: readings.flagged_total }));
  if (hasGaps) said.push(t("chart.gaps"));
  return h(
    "div",
    { class: "chart-notes" },
    h("p", { class: "chart-count", text: t("chart.count", { count: samples.length }) }),
    h("details", { class: "chart-fold", attrs: { "data-fold": `${options.scope}:legend` } }, h("summary", { text: t("chart.legend") }), said.map((line) => h("p", { text: line }))),
  );
}

function domainOf(series, metric) {
  const fixed = DEFAULT_LEVEL_RANGES[metric.key];
  if (fixed) return fixed;
  return paddedRange(series.min, series.max, MIN_SPAN[metric.key] ?? 0);
}

// now: ctx.now when the page has one. scope: names this chart among several on a page (for the folds).
// readingsChart(t, readings, { timeZone, lang, sampleSeconds, metrics, empty }) -> Element
// sampleSeconds: the run sheet's sampling interval, when known; it widens the gap limit so a series
// sampled more slowly than the bucket width is not cut into dots. metrics: the readings to draw
// (default the sensors; LEVELS draws the channel levels); empty: the text when nothing is drawn.
export function readingsChart(
  t,
  readings,
  { timeZone = "UTC", lang = "en", sampleSeconds = null, metrics = METRICS, empty = "chart.empty", now, scope = "readings" } = {},
) {
  const samples = readings && Array.isArray(readings.samples) ? readings.samples : [];
  const options = { timeZone, lang, now, scope };
  if (samples.length === 0) return h("p", { class: "chart-empty", text: t(empty) });
  const box = { width: WIDTH, height: HEIGHT, ...span(readings, samples) };
  const maxGap = gapLimit(readings.window, sampleSeconds);
  const figures = [];
  let hasGaps = false;
  for (const metric of metrics) {
    const own = seriesPoints(samples, metric.key, box);
    if (own.points.length === 0) continue;
    const series = seriesPoints(samples, metric.key, { ...box, domain: domainOf(own, metric) });
    const segments = splitAtGaps(series.points, maxGap);
    hasGaps = hasGaps || segments.length > 1;
    const body = h("div", { class: "chart-body" }, yTicks(series, metric, options), plot(t, series, segments, metric, options));
    const figure = h("figure", { class: "chart" }, chartHead(t, series, metric, options), body, xTicks(box, options), dataTable(t, series, metric, options));
    figures.push(figure);
  }
  if (figures.length === 0) return h("p", { class: "chart-empty", text: t(empty) });
  return h("div", { class: "readings" }, notes(t, readings, samples, options, hasGaps), h("div", { class: "chart-grid" }, figures));
}

// Which of a rebuilt chart's folds were open, and how far each open data table was scrolled, so a
// live refresh can put them back: { key -> scrollTop }.
export function openChartFolds(root) {
  const saved = new Map();
  const visit = (node) => {
    if (node.localName === "details" && node.getAttribute("data-fold") && node.hasAttribute("open")) {
      const wrap = node.children.find((child) => (child.getAttribute("class") || "").split(/\s+/).includes("table-wrap"));
      saved.set(node.getAttribute("data-fold"), wrap ? wrap.scrollTop : 0);
    }
    node.children.forEach(visit);
  };
  visit(root);
  return saved;
}

export function restoreChartFolds(root, saved) {
  const visit = (node) => {
    const key = node.localName === "details" ? node.getAttribute("data-fold") : null;
    if (key && saved.has(key)) {
      node.setAttribute("open", "");
      const wrap = node.children.find((child) => (child.getAttribute("class") || "").split(/\s+/).includes("table-wrap"));
      if (wrap) wrap.scrollTop = saved.get(key);
    }
    node.children.forEach(visit);
  };
  visit(root);
}
