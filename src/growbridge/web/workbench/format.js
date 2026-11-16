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

const MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DIGEST_SHORT_LENGTH = 8;
const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const HOURS_PER_DAY = 24;
const SHORT_SECONDS_LIMIT = 120;
const MINUTES_LIMIT = 120;
const HOURS_LIMIT = 48;

export const DEFAULT_LEVEL_RANGES = { light: [0, 100], exhaust: [0, 100], fan: [0, 10] };

// Human duration: the unit follows the size (seconds, minutes, hours, days).
export function formatDuration(t, seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return DASH;
  const s = Math.round(seconds);
  if (s < SHORT_SECONDS_LIMIT) return t("duration.seconds", { n: s });
  const totalMinutes = Math.round(s / SECONDS_PER_MINUTE);
  if (totalMinutes < MINUTES_LIMIT) return t("duration.minutes", { n: totalMinutes });
  const totalHours = Math.round(s / (SECONDS_PER_MINUTE * MINUTES_PER_HOUR));
  if (totalHours < HOURS_LIMIT) {
    const h = Math.floor(totalMinutes / MINUTES_PER_HOUR);
    const m = totalMinutes % MINUTES_PER_HOUR;
    return m === 0 ? t("duration.hours", { h }) : t("duration.hoursMinutes", { h, m });
  }
  const d = Math.floor(totalHours / HOURS_PER_DAY);
  const h = totalHours % HOURS_PER_DAY;
  return h === 0 ? t("duration.days", { d }) : t("duration.daysHours", { d, h });
}

// Date and time in the site zone; the year appears only when it is not the current year.
export function formatDateTime(epochSeconds, timeZone, lang, nowSeconds = Date.now() / 1000) {
  if (typeof epochSeconds !== "number" || !Number.isFinite(epochSeconds)) return DASH;
  const p = wallParts(epochSeconds, timeZone);
  const showYear = p.year !== wallParts(nowSeconds, timeZone).year;
  const month = Number(p.month);
  const day = Number(p.day);
  const clock = `${p.hour}:${p.minute}`;
  if (lang === "zh") return `${showYear ? `${p.year}年` : ""}${month}月${day}日 ${clock}`;
  return `${day} ${MONTHS_EN[month - 1]}${showYear ? ` ${p.year}` : ""} ${clock}`;
}

// A level written as value over full scale; pumps are on or off.
export function levelText(t, channel, level, range = DEFAULT_LEVEL_RANGES[channel]) {
  if (level === null || level === undefined) return DASH;
  if (channel === "pump") return level > 0 ? t("level.on") : t("level.off");
  if (channel === "light" || channel === "exhaust") return t("level.percent", { level });
  if (range) return t("level.steps", { level, max: range[1] });
  return String(level);
}

export function formatMoney(value, lang) {
  return formatNumber(value, 2, lang);
}

export function shortDigest(hex) {
  if (typeof hex !== "string" || hex === "") return DASH;
  return `${hex.slice(0, DIGEST_SHORT_LENGTH)}…`;
}
