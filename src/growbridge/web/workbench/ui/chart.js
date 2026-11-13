// Environment curves of a stage: one small SVG line chart per reading that has data.
// Downsampling and problem samples are always stated, never hidden (design §2, anti-goals).
import { METRICS, seriesPoints } from "../chart-math.js";
import { formatNumber, formatTime } from "../format.js";
import { h, svg } from "./dom.js";

const WIDTH = 600;
const HEIGHT = 120;
const PAD = 8; // room for the markers at the edges
const HIT_RADIUS = 6; // the hover target is bigger than the mark
const FLAG_RADIUS = 3.5;

function timeLabel(epoch, timeZone, lang) {
  return `${formatTime(epoch, timeZone, lang)} ${timeZone}`;
}

function valueLabel(value, metric, lang) {
  return `${formatNumber(value, metric.precision, lang)} ${metric.unit}`;
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
  const text = `${valueLabel(point.v, metric, options.lang)} · ${timeLabel(point.t, options.timeZone, options.lang)}`;
  return point.flagged ? `${text} · ${t("chart.flaggedPoint")}` : text;
}

// Every point gets a hover target with its value and time; problem points are hollow circles,
// drawn last so no hover target of a neighbour covers them.
function pointMarks(t, points, metric, options) {
  const ordered = [...points.filter((point) => !point.flagged), ...points.filter((point) => point.flagged)];
  return ordered.map((point) => {
    const title = svg("title", {}, pointTitle(t, point, metric, options));
    const attrs = { cx: point.x.toFixed(1), cy: point.y.toFixed(1) };
    if (point.flagged) {
      return svg("circle", { ...attrs, r: FLAG_RADIUS, class: "chart-flagged" }, title);
    }
    return svg("circle", { ...attrs, r: HIT_RADIUS, class: "chart-hit" }, title);
  });
}

function plot(t, series, metric, options) {
  const { points } = series;
  const line = points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
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
      points.length > 1 ? svg("polyline", { class: "chart-line", points: line }) : null,
      pointMarks(t, points, metric, options),
    ),
  );
}

// The latest value is the current reading; its time and any problem with it are said beside it.
function chartHead(t, series, metric, options) {
  const latest = series.points[series.points.length - 1];
  const when = t("chart.latestAt", { time: timeLabel(latest.t, options.timeZone, options.lang) });
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

function notes(t, readings, samples, options) {
  const lines = [];
  const { start, end } = span(readings, samples);
  lines.push(t("chart.window", { start: timeLabel(start, options.timeZone, options.lang), end: timeLabel(end, options.timeZone, options.lang) }));
  if (readings.downsampled) {
    lines.push(t("chart.downsampled", { shown: samples.length, total: readings.total_samples }));
  }
  if (readings.flagged_total > 0) lines.push(t("chart.flagged", { count: readings.flagged_total }));
  return h("div", { class: "chart-notes" }, lines.map((line) => h("p", { text: line })));
}

// readingsChart(t, readings, { timeZone, lang }) -> Element
export function readingsChart(t, readings, { timeZone = "UTC", lang = "en" } = {}) {
  const samples = readings && Array.isArray(readings.samples) ? readings.samples : [];
  const options = { timeZone, lang };
  if (samples.length === 0) return h("p", { class: "chart-empty", text: t("chart.empty") });
  const box = { width: WIDTH, height: HEIGHT, ...span(readings, samples) };
  const figures = [];
  for (const metric of METRICS) {
    const series = seriesPoints(samples, metric.key, box);
    if (series.points.length === 0) continue;
    figures.push(h("figure", { class: "chart" }, chartHead(t, series, metric, options), plot(t, series, metric, options)));
  }
  if (figures.length === 0) return h("p", { class: "chart-empty", text: t("chart.empty") });
  return h("div", { class: "readings" }, notes(t, readings, samples, options), h("div", { class: "chart-grid" }, figures));
}
