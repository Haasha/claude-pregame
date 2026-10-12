// Pure logic shared by the background worker and popup (no chrome.* calls),
// so it can be unit-tested with plain Node.

export const DEFAULT_SETTINGS = {
  enabled: true,
  activeStart: "06:00", // only auto-start windows between these local times
  activeEnd: "23:00",
  notifyOnStart: false,
};

export const PING_PROMPT = "hi";
export const RESET_GRACE_MS = 30_000; // wait this long past the reset before pinging
export const RETRY_SIGNED_OUT_MS = 5 * 60_000;
export const RETRY_ERROR_MS = 10 * 60_000;
export const FALLBACK_WINDOW_MS = 5 * 60 * 60_000;

function minutesOf(hhmm) {
  const [h, m] = String(hhmm).split(":").map(Number);
  return h * 60 + m;
}

/** Is `date` inside the active range? Ranges may wrap past midnight. */
export function inActiveHours(settings, date = new Date()) {
  if (!settings.activeStart || !settings.activeEnd) return true;
  const start = minutesOf(settings.activeStart);
  const end = minutesOf(settings.activeEnd);
  const now = date.getHours() * 60 + date.getMinutes();
  if (start === end) return true;
  return start < end ? now >= start && now < end : now >= start || now < end;
}

/**
 * Normalize claude.ai's /usage response to {utilization, resetsAt (ms) | null}.
 * A window is running only when resets_at is set and in the future.
 */
export function parseUsage(json) {
  const five = json && json.five_hour;
  if (!five) return { utilization: 0, resetsAt: null };
  const resetsAt = five.resets_at ? Date.parse(five.resets_at) : NaN;
  return {
    utilization: typeof five.utilization === "number" ? five.utilization : 0,
    resetsAt: Number.isFinite(resetsAt) ? resetsAt : null,
  };
}

export function windowActive(usage, now = Date.now()) {
  return Boolean(usage && usage.resetsAt && usage.resetsAt > now);
}

/** Pick the claude.ai organization that has chat (skip API-only orgs). */
export function pickOrg(orgs) {
  if (!Array.isArray(orgs) || orgs.length === 0) return null;
  const chat = orgs.find((o) => Array.isArray(o.capabilities) && o.capabilities.includes("chat"));
  return (chat || orgs[0]).uuid || null;
}

/** "2h 14m", "38m", "<1m" */
export function formatRemaining(ms) {
  if (ms <= 0) return "now";
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "<1m";
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h ? `${h}h ${m}m` : `${m}m`;
}

/** Short text for the toolbar badge (max ~4 chars). */
export function badgeFor(state, settings, now = Date.now()) {
  if (!settings.enabled) return { text: "off", color: "#8a8a8a" };
  if (state.status === "signed_out") return { text: "!", color: "#d14343" };
  if (state.status === "error") return { text: "!", color: "#d98a1c" };
  const usage = state.usage;
  if (windowActive(usage, now)) {
    const mins = Math.ceil((usage.resetsAt - now) / 60_000);
    return { text: mins >= 60 ? `${Math.floor(mins / 60)}h` : `${mins}m`, color: "#2f8f5b" };
  }
  return { text: "", color: "#2f8f5b" };
}

/** The next moment the active range opens (now if already inside it). */
export function nextActiveStart(settings, date = new Date()) {
  if (inActiveHours(settings, date)) return date.getTime();
  const [h, m] = String(settings.activeStart).split(":").map(Number);
  const next = new Date(date);
  next.setHours(h, m, 0, 0);
  if (next <= date) next.setDate(next.getDate() + 1);
  return next.getTime();
}

export const IDLE_RECHECK_MS = 30 * 60_000;

/**
 * Given fresh usage, decide what to do: "ping" now, or "wait" until `nextCheck`.
 * Your hours and the on/off switch only gate pinging; usage is always readable.
 */
export function plan(usage, settings, now = Date.now()) {
  if (windowActive(usage, now)) return { action: "wait", nextCheck: usage.resetsAt + RESET_GRACE_MS };
  if (!settings.enabled) return { action: "wait", nextCheck: now + IDLE_RECHECK_MS };
  const opens = nextActiveStart(settings, new Date(now));
  if (opens > now) return { action: "wait", nextCheck: Math.min(opens, now + IDLE_RECHECK_MS) };
  return { action: "ping" };
}
