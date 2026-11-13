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

export function seriesPoints(samples, key, { width, height, start, end }) {
  const raw = [];
  for (const sample of samples) {
    const v = metricValue(sample, key);
    if (v !== null) raw.push({ t: sample.timestamp, v, flagged: isFlagged(sample) });
  }
  if (raw.length === 0) return { points: [], min: null, max: null };
  const min = Math.min(...raw.map((p) => p.v));
  const max = Math.max(...raw.map((p) => p.v));
  const timeSpan = end - start;
  const valueSpan = max - min;
  const points = raw.map(({ t, v, flagged }) => ({
    x: timeSpan > 0 ? ((t - start) / timeSpan) * width : width / 2,
    y: valueSpan > 0 ? height - ((v - min) / valueSpan) * height : height / 2,
    t,
    v,
    flagged,
  }));
  return { points, min, max };
}
