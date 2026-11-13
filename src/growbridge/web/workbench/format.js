// Site-time-zone helpers built on Intl (full ICU ships with Node and browsers).

const DASH = "—";
const LOCAL_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;
const HALF_DAY_SECONDS = 12 * 3600;
const formatters = new Map();

function partsFormatter(timeZone) {
  if (!formatters.has(timeZone)) {
    formatters.set(
      timeZone,
      new Intl.DateTimeFormat("en-US", {
        timeZone,
        hourCycle: "h23",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
  }
  return formatters.get(timeZone);
}

function wallParts(epochSeconds, timeZone) {
  const parts = {};
  for (const { type, value } of partsFormatter(timeZone).formatToParts(new Date(epochSeconds * 1000))) {
    parts[type] = value;
  }
  return parts;
}

// The zone's wall clock for an instant, expressed as if it were UTC milliseconds.
function wallAsUtcMs(epochSeconds, timeZone) {
  const p = wallParts(epochSeconds, timeZone);
  return Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute));
}

export function offsetMinutes(epochSeconds, timeZone) {
  const whole = Math.floor(epochSeconds / 60) * 60;
  return (wallAsUtcMs(whole, timeZone) - whole * 1000) / 60000;
}

export function formatTime(epochSeconds, timeZone, lang) {
  void lang;
  const p = wallParts(epochSeconds, timeZone);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

export function zonedToEpoch(local, timeZone) {
  const match = LOCAL_PATTERN.exec(local);
  if (!match) throw new RangeError(`Invalid local time: ${local}`);
  const [year, month, day, hour, minute] = match.slice(1).map(Number);
  const localMs = Date.UTC(year, month - 1, day, hour, minute);
  // Date.UTC normalises out-of-range fields, so compare the parts back.
  const check = new Date(localMs);
  const exact =
    check.getUTCFullYear() === year &&
    check.getUTCMonth() === month - 1 &&
    check.getUTCDate() === day &&
    check.getUTCHours() === hour &&
    check.getUTCMinutes() === minute;
  if (!exact) throw new RangeError(`Invalid local time: ${local}`);
  const guess = localMs / 1000;
  const offsets = new Set([
    offsetMinutes(guess - HALF_DAY_SECONDS, timeZone),
    offsetMinutes(guess + HALF_DAY_SECONDS, timeZone),
  ]);
  const matches = [];
  for (const offset of offsets) {
    const epoch = guess - offset * 60;
    if (wallAsUtcMs(epoch, timeZone) === localMs) matches.push(epoch);
  }
  if (matches.length === 0) throw new RangeError(`Time does not exist in ${timeZone}: ${local}`);
  const epoch = Math.min(...matches);
  return { epoch, offsetMinutes: offsetMinutes(epoch, timeZone) };
}

export function formatNumber(value, precision, lang) {
  if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
  return value.toLocaleString(lang, {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  });
}
