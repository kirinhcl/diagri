// Pure chart geometry for the readings view.

export const METRICS = [
  { key: "temp", unit: "°C", precision: 1 },
  { key: "humi", unit: "% RH", precision: 1 },
  { key: "vpd", unit: "kPa", precision: 2 },
  { key: "co2", unit: "ppm", precision: 0 },
  { key: "ppfd", unit: "µmol/m²/s", precision: 0 },
  { key: "tempSoil", unit: "°C", precision: 1 },
];

export function metricValue(sample, key) {
  const value = sample?.data?.sensor?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function isFlagged(sample) {
  return sample.flagged > 0 || sample.quality !== "ok" || !sample.clock_synced;
}

// afterMissing: samples without this value lie between this point and the previous one.
export function seriesPoints(samples, key, { width, height, start, end }) {
  const raw = [];
  let missed = false;
  for (const sample of samples) {
    const v = metricValue(sample, key);
    if (v === null) {
      missed = raw.length > 0;
      continue;
    }
    raw.push({ t: sample.timestamp, v, flagged: isFlagged(sample), afterMissing: missed });
    missed = false;
  }
  if (raw.length === 0) return { points: [], min: null, max: null };
  const min = Math.min(...raw.map((p) => p.v));
  const max = Math.max(...raw.map((p) => p.v));
  const timeSpan = end - start;
  const valueSpan = max - min;
  const points = raw.map(({ t, v, flagged, afterMissing }) => ({
    x: timeSpan > 0 ? ((t - start) / timeSpan) * width : width / 2,
    y: valueSpan > 0 ? height - ((v - min) / valueSpan) * height : height / 2,
    t,
    v,
    flagged,
    afterMissing,
  }));
  return { points, min, max };
}

// A line may join two points only when they are at most this many expected steps apart.
export const GAP_FACTOR = 2.5;

// The expected step is the bucket width, or the run sheet's sampling interval when that is longer;
// with neither known only missing values split the line.
export function gapLimit(window, sampleSeconds) {
  const steps = [window && window.bucket_seconds, sampleSeconds].filter((s) => Number.isFinite(s) && s > 0);
  return steps.length ? GAP_FACTOR * Math.max(...steps) : Infinity;
}

// Consecutive points become one segment unless time between them exceeds the limit or values were
// missing in between; a segment may hold a single point.
export function splitAtGaps(points, maxGapSeconds) {
  const segments = [];
  for (const point of Array.isArray(points) ? points : []) {
    const current = segments[segments.length - 1];
    const previous = current && current[current.length - 1];
    const joined = previous && !point.afterMissing && point.t - previous.t <= maxGapSeconds;
    if (joined) current.push(point);
    else segments.push([point]);
  }
  return segments;
}
