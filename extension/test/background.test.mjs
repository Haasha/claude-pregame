// Runs the real background.js against a fake chrome.* and a fake claude.ai.
import { test } from "node:test";
import assert from "node:assert/strict";

const listeners = {};
const on = (name) => ({ addListener: (fn) => { listeners[name] = fn; } });
const store = { sync: {}, local: {} };
const area = (name) => ({
  get: async (key) => ({ [key]: store[name][key] }),
  set: async (obj) => { Object.assign(store[name], obj); },
});
const badge = {};
const calls = [];
let rules = [];

globalThis.chrome = {
  storage: { sync: area("sync"), local: area("local") },
  runtime: { onInstalled: on("installed"), onStartup: on("startup"), onMessage: on("message") },
  alarms: { create: async () => {}, onAlarm: on("alarm") },
  action: { setBadgeText: async ({ text }) => { badge.text = text; }, setBadgeBackgroundColor: async () => {} },
  tabs: { TAB_ID_NONE: -1, create: (o) => calls.push({ tab: o.url }) },
  notifications: { create: () => {} },
  declarativeNetRequest: { updateSessionRules: async ({ addRules }) => { rules = addRules; } },
};

// Fake claude.ai
const server = { signedIn: true, resetsAt: null, utilization: 0 };
globalThis.fetch = async (url, opts = {}) => {
  const path = new URL(url).pathname;
  const method = opts.method || "GET";
  calls.push({ method, path, body: opts.body && JSON.parse(opts.body) });
  const json = (status, body) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) });
  if (!server.signedIn) return json(403, { error: "permission_error" });
  if (path === "/api/organizations") return json(200, [{ uuid: "api-org", capabilities: ["api"] }, { uuid: "org1", capabilities: ["chat"] }]);
  if (path === "/api/organizations/org1/usage") {
    return json(200, { five_hour: { utilization: server.utilization, resets_at: server.resetsAt && new Date(server.resetsAt).toISOString() } });
  }
  if (method === "POST" && path === "/api/organizations/org1/chat_conversations") return json(201, { uuid: opts.body.uuid });
  if (method === "POST" && path.endsWith("/completion")) {
    server.resetsAt = Date.now() + 5 * 3600e3;
    server.utilization = 1;
    return { ok: true, status: 200, text: async () => "event: completion\ndata: {}\n\n" };
  }
  return json(404, {});
};

const message = (type) => new Promise((resolve) => listeners.message({ type }, {}, resolve));
const pings = () => calls.filter((c) => c.path && c.path.endsWith("/completion")).length;

await import("../background.js");
store.sync.settings = { enabled: true, activeStart: "00:00", activeEnd: "00:00" }; // always active

test("installs a header rule scoped to the extension's own requests", () => {
  assert.equal(rules[0].condition.tabIds[0], -1);
  assert.deepEqual(rules[0].condition.requestDomains, ["claude.ai"]);
});

test("signed out: shows ! and does not ping", async () => {
  server.signedIn = false;
  await listeners.installed({ reason: "install" });
  const { state } = await message("refresh");
  assert.equal(state.status, "signed_out");
  assert.equal(badge.text, "!");
  assert.equal(pings(), 0);
  assert.ok(calls.some((c) => c.tab === "welcome.html"));
});

test("signed in with no window: starts one in an incognito chat", async () => {
  server.signedIn = true;
  const { state } = await message("refresh");
  assert.equal(pings(), 1);
  assert.equal(state.status, "ok");
  assert.equal(state.orgId, "org1");
  assert.ok(state.usage.resetsAt > Date.now() + 4.9 * 3600e3);
  const create = calls.find((c) => c.method === "POST" && c.path.endsWith("/chat_conversations"));
  assert.equal(create.body.is_temporary, true);
  assert.equal(badge.text, "5h");
});

test("window running: alarm ticks don't touch the network", async () => {
  const before = calls.length;
  await listeners.alarm({ name: "tick" });
  await listeners.alarm({ name: "tick" });
  assert.equal(calls.length, before);
});

test("after the reset passes, the next tick starts a new window", async () => {
  server.resetsAt = Date.now() - 1000;
  store.local.state.nextCheck = Date.now() - 1;
  await listeners.alarm({ name: "tick" });
  assert.equal(pings(), 2);
});

test("outside your hours: reads usage but doesn't ping", async () => {
  server.resetsAt = null;
  const h = new Date().getHours();
  const off = `${String((h + 2) % 24).padStart(2, "0")}:00`;
  const off2 = `${String((h + 3) % 24).padStart(2, "0")}:00`;
  store.sync.settings = { enabled: true, activeStart: off, activeEnd: off2 };
  const { state } = await message("settingsChanged");
  assert.equal(pings(), 2);
  assert.ok(state.nextCheck > Date.now());
});

test("Start a window now forces a ping", async () => {
  await message("startNow");
  assert.equal(pings(), 3);
});
