// What the device accepts (level ranges, sensors with units) and the pump cap the control service
// enforces, read once per page load for the forms' hints and range checks.
//
// The cache is keyed on the page's ctx: main.js makes a fresh ctx for every page load (the api is
// shared by all of them), so one load reads once and the next load reads again.
const reads = new WeakMap();

async function read(ctx) {
  try {
    const body = await ctx.api.get("/capabilities");
    return body && typeof body === "object" ? body : null;
  } catch {
    return null; // a form without hints still works; no defaults are invented here
  }
}

// Resolves to {level_ranges, sensors, max_pump_seconds}, or null when the read failed. Never throws.
export function loadCapabilities(ctx) {
  if (!reads.has(ctx)) reads.set(ctx, read(ctx));
  return reads.get(ctx);
}
