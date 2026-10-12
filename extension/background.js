// Pregame for Claude: background worker.
//
// Once a minute it decides (without touching the network) whether your 5-hour
// window could have reset. Only then does it ask claude.ai for your usage, and
// if no window is running it sends one "hi" in an incognito chat to start one.

import {
  DEFAULT_SETTINGS, PING_PROMPT, RESET_GRACE_MS, RETRY_SIGNED_OUT_MS, RETRY_ERROR_MS,
  FALLBACK_WINDOW_MS, parseUsage, windowActive, pickOrg, badgeFor, plan,
} from "./core.js";

const API = "https://claude.ai/api";
const TICK_ALARM = "tick";

class SignedOutError extends Error {}

// ------------------------------------------------------------------ storage

async function getSettings() {
  const { settings } = await chrome.storage.sync.get("settings");
  return { ...DEFAULT_SETTINGS, ...settings };
}

async function getState() {
  const { state } = await chrome.storage.local.get("state");
  return state || {};
}

async function patchState(patch) {
  const state = { ...(await getState()), ...patch };
  await chrome.storage.local.set({ state });
  await updateBadge(state);
  return state;
}

// --------------------------------------------------------------- claude.ai

// Requests from an extension carry a chrome-extension:// Origin. Present them
// to claude.ai exactly like requests from a claude.ai tab.
async function installHeaderRule() {
  await chrome.declarativeNetRequest.updateSessionRules({
    removeRuleIds: [1],
    addRules: [{
      id: 1,
      priority: 1,
      action: {
        type: "modifyHeaders",
        requestHeaders: [
          { header: "origin", operation: "set", value: "https://claude.ai" },
          { header: "referer", operation: "set", value: "https://claude.ai/new" },
        ],
      },
      condition: {
        requestDomains: ["claude.ai"],
        tabIds: [chrome.tabs.TAB_ID_NONE], // only this extension's own requests, never your tabs
        resourceTypes: ["xmlhttprequest"],
      },
    }],
  });
}

async function api(path, { method = "GET", body, accept = "application/json" } = {}) {
  const res = await fetch(`${API}${path}`, {
    method,
    credentials: "include",
    headers: {
      accept,
      ...(body ? { "content-type": "application/json" } : {}),
      "anthropic-client-platform": "web_claude_ai",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 || res.status === 403) throw new SignedOutError(`claude.ai returned ${res.status}`);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`claude.ai ${method} ${path.split("/").slice(-1)[0]} failed: ${res.status} ${text.slice(0, 160)}`);
  }
  return accept === "application/json" ? res.json() : res.text();
}

async function getOrgId(state) {
  if (state.orgId) return state.orgId;
  const orgId = pickOrg(await api("/organizations"));
  if (!orgId) throw new SignedOutError("no claude.ai organization found");
  await patchState({ orgId });
  return orgId;
}

async function fetchUsage(orgId) {
  return parseUsage(await api(`/organizations/${orgId}/usage`));
}

/** Send one tiny message in an incognito chat, which never shows up in your history. */
async function sendPing(orgId) {
  const uuid = crypto.randomUUID();
  await api(`/organizations/${orgId}/chat_conversations`, {
    method: "POST",
    body: { uuid, name: "", is_temporary: true },
  });
  await api(`/organizations/${orgId}/chat_conversations/${uuid}/completion`, {
    method: "POST",
    accept: "text/event-stream",
    body: {
      prompt: PING_PROMPT,
      parent_message_uuid: "00000000-0000-4000-8000-000000000000",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      attachments: [],
      files: [],
      rendering_mode: "messages",
    },
  });
}

// -------------------------------------------------------------------- main

let running = null;

/**
 * Read usage and start a window if one is due.
 * `force` sends a ping right away (the "Start a window now" button).
 * `fresh` ignores the schedule and re-reads usage (popup opened, settings changed).
 */
async function check({ force = false, fresh = false } = {}) {
  if (running) return running; // never overlap two checks
  running = (async () => {
    const settings = await getSettings();
    let state = await getState();
    const now = Date.now();
    if (!force && !fresh && state.nextCheck && now < state.nextCheck) return updateBadge(state);

    try {
      let orgId = await getOrgId(state);
      let usage;
      try {
        usage = await fetchUsage(orgId);
      } catch (e) {
        if (!(e instanceof SignedOutError)) throw e;
        // Maybe you switched accounts: rediscover the org once.
        state = await patchState({ orgId: null });
        orgId = await getOrgId(state);
        usage = await fetchUsage(orgId);
      }

      const next = force ? { action: "ping" } : plan(usage, settings, now);
      if (next.action === "wait") {
        await patchState({ status: "ok", error: null, usage, lastCheck: now, nextCheck: next.nextCheck });
        return;
      }

      await sendPing(orgId);
      const after = await fetchUsage(orgId).catch(() => null);
      const resetsAt = windowActive(after) ? after.resetsAt : now + FALLBACK_WINDOW_MS;
      await patchState({
        status: "ok", error: null, lastCheck: now, lastPing: now,
        usage: after || { utilization: 0, resetsAt },
        nextCheck: resetsAt + RESET_GRACE_MS,
      });
      if (settings.notifyOnStart) {
        const at = new Date(resetsAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        chrome.notifications.create({
          type: "basic", iconUrl: "icons/icon128.png",
          title: "Claude window started", message: `Your next reset is at ${at}.`,
        });
      }
    } catch (e) {
      const signedOut = e instanceof SignedOutError;
      await patchState({
        status: signedOut ? "signed_out" : "error",
        error: signedOut ? "Sign in to claude.ai in this browser." : String(e.message || e),
        lastCheck: now,
        nextCheck: now + (signedOut ? RETRY_SIGNED_OUT_MS : RETRY_ERROR_MS),
      });
    }
  })().finally(() => { running = null; });
  return running;
}

async function updateBadge(state) {
  state = state || (await getState());
  const { text, color } = badgeFor(state, await getSettings());
  await chrome.action.setBadgeText({ text });
  await chrome.action.setBadgeBackgroundColor({ color });
}

async function start() {
  await installHeaderRule();
  await chrome.alarms.create(TICK_ALARM, { periodInMinutes: 1 });
  await check();
}

chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  await start();
  if (reason === "install") chrome.tabs.create({ url: "welcome.html" });
});
chrome.runtime.onStartup.addListener(start);
chrome.alarms.onAlarm.addListener((alarm) => (alarm.name === TICK_ALARM ? check() : undefined));

// The service worker can be restarted at any time; session rules are cleared
// with the browser session, so make sure ours exists whenever we wake up.
installHeaderRule();

// Messages from the popup and welcome page.
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    if (msg.type === "startNow") await check({ force: true });
    else if (msg.type === "refresh" || msg.type === "settingsChanged") await check({ fresh: true });
    reply({ state: await getState(), settings: await getSettings() });
  })();
  return true; // keep the channel open for the async reply
});
