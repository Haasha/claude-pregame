import { test } from "node:test";
import assert from "node:assert/strict";
import {
  inActiveHours, parseUsage, windowActive, pickOrg, formatRemaining, badgeFor,
  nextActiveStart, plan, DEFAULT_SETTINGS, RESET_GRACE_MS,
} from "../core.js";

const at = (hhmm) => { const d = new Date(2026, 9, 12); const [h, m] = hhmm.split(":"); d.setHours(+h, +m, 0, 0); return d; };

test("active hours, including ranges that wrap midnight", () => {
  const day = { activeStart: "06:00", activeEnd: "23:00" };
  const night = { activeStart: "22:00", activeEnd: "06:00" };
  assert.equal(inActiveHours(day, at("06:00")), true);
  assert.equal(inActiveHours(day, at("05:59")), false);
  assert.equal(inActiveHours(day, at("23:00")), false);
  assert.equal(inActiveHours(night, at("23:30")), true);
  assert.equal(inActiveHours(night, at("05:59")), true);
  assert.equal(inActiveHours(night, at("12:00")), false);
  assert.equal(inActiveHours({ activeStart: "", activeEnd: "" }, at("03:00")), true);
});

test("parseUsage handles running, idle and missing windows", () => {
  const r = parseUsage({ five_hour: { utilization: 23.5, resets_at: "2026-10-12T16:00:00.000Z" } });
  assert.equal(r.utilization, 23.5);
  assert.equal(r.resetsAt, Date.parse("2026-10-12T16:00:00Z"));
  assert.deepEqual(parseUsage({ five_hour: { utilization: 0, resets_at: null } }), { utilization: 0, resetsAt: null });
  assert.deepEqual(parseUsage({}), { utilization: 0, resetsAt: null });
  assert.deepEqual(parseUsage(null), { utilization: 0, resetsAt: null });
});

test("windowActive", () => {
  assert.equal(windowActive({ resetsAt: Date.now() + 1000 }), true);
  assert.equal(windowActive({ resetsAt: Date.now() - 1000 }), false);
  assert.equal(windowActive({ resetsAt: null }), false);
});

test("pickOrg prefers a chat org over an API-only org", () => {
  const orgs = [{ uuid: "api", capabilities: ["api"] }, { uuid: "me", capabilities: ["chat", "claude_max"] }];
  assert.equal(pickOrg(orgs), "me");
  assert.equal(pickOrg([{ uuid: "only" }]), "only");
  assert.equal(pickOrg([]), null);
});

test("formatRemaining and badge text", () => {
  assert.equal(formatRemaining(2 * 3600e3 + 14 * 60e3), "2h 14m");
  assert.equal(formatRemaining(38 * 60e3), "38m");
  assert.equal(formatRemaining(10e3), "<1m");
  const now = Date.now();
  const s = DEFAULT_SETTINGS;
  assert.equal(badgeFor({ usage: { resetsAt: now + 3 * 3600e3 } }, s, now).text, "3h");
  assert.equal(badgeFor({ usage: { resetsAt: now + 45 * 60e3 } }, s, now).text, "45m");
  assert.equal(badgeFor({ status: "signed_out" }, s, now).text, "!");
  assert.equal(badgeFor({}, { ...s, enabled: false }, now).text, "off");
});

test("nextActiveStart rolls to tomorrow when today's start has passed", () => {
  const s = { activeStart: "06:00", activeEnd: "23:00" };
  assert.equal(nextActiveStart(s, at("23:30")), at("06:00").getTime() + 24 * 3600e3);
  assert.equal(nextActiveStart(s, at("05:00")), at("06:00").getTime());
  assert.equal(nextActiveStart(s, at("10:00")), at("10:00").getTime());
});

test("plan: wait for a running window, ping when idle inside hours", () => {
  const s = { ...DEFAULT_SETTINGS, activeStart: "06:00", activeEnd: "23:00" };
  const now = at("10:00").getTime();
  const running = { resetsAt: now + 3600e3 };
  assert.deepEqual(plan(running, s, now), { action: "wait", nextCheck: running.resetsAt + RESET_GRACE_MS });
  assert.deepEqual(plan({ resetsAt: null }, s, now), { action: "ping" });
  assert.equal(plan({ resetsAt: null }, { ...s, enabled: false }, now).action, "wait");
  // 05:50 outside hours: wake exactly at 06:00
  const early = at("05:50").getTime();
  assert.deepEqual(plan({ resetsAt: null }, s, early), { action: "wait", nextCheck: at("06:00").getTime() });
});
