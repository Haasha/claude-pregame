import { DEFAULT_SETTINGS, formatRemaining, windowActive, inActiveHours } from "./core.js";

const $ = (id) => document.getElementById(id);
const timeOf = (ms) => new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

let state = {};
let settings = { ...DEFAULT_SETTINGS };

function render() {
  const now = Date.now();
  const usage = state.usage;
  const active = windowActive(usage, now);

  $("enabled").checked = settings.enabled;
  $("start").value = settings.activeStart;
  $("end").value = settings.activeEnd;
  $("notify").checked = settings.notifyOnStart;

  const alert = $("alert");
  if (state.status === "signed_out") {
    alert.innerHTML = 'You\'re signed out. <a href="https://claude.ai/login" target="_blank">Sign in to claude.ai</a> in this browser and Pregame will take it from there.';
    alert.classList.remove("hidden");
  } else if (state.status === "error") {
    alert.textContent = `Couldn't reach claude.ai: ${state.error}. Pregame will retry on its own.`;
    alert.classList.remove("hidden");
  } else {
    alert.classList.add("hidden");
  }

  const blocked = state.status === "signed_out" || state.status === "error";
  if (active) {
    $("headline-label").textContent = "Next reset";
    $("headline").textContent = formatRemaining(usage.resetsAt - now);
    $("subline").textContent = `at ${timeOf(usage.resetsAt)}`;
  } else if (blocked) {
    $("headline-label").textContent = "Status";
    $("headline").textContent = state.status === "signed_out" ? "Waiting for sign-in" : "Retrying soon";
    $("subline").textContent = " ";
  } else if (!settings.enabled) {
    $("headline-label").textContent = "Status";
    $("headline").textContent = "Paused";
    $("subline").textContent = "Turn on auto-start below.";
  } else if (!inActiveHours(settings)) {
    $("headline-label").textContent = "Status";
    $("headline").textContent = "Resting";
    $("subline").textContent = `Starts again at ${settings.activeStart}.`;
  } else {
    $("headline-label").textContent = "Status";
    $("headline").textContent = state.status ? "Starting…" : "Checking…";
    $("subline").textContent = " ";
  }

  const pct = Math.round(usage ? usage.utilization : 0);
  $("usage-bar").style.width = `${Math.min(100, pct)}%`;
  $("usage-text").textContent = active ? `${pct}% of this 5-hour window used` : "No window running";

  $("start-now").disabled = active || state.status === "signed_out";
  $("start-now").textContent = active ? "Window already running"
    : state.status === "signed_out" ? "Sign in to claude.ai first" : "Start a window now";
  $("foot").textContent = state.lastPing ? `Last auto-start: ${new Date(state.lastPing).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}` : " ";
}

async function send(type) {
  const res = await chrome.runtime.sendMessage({ type });
  if (res) ({ state, settings } = res);
  render();
}

async function saveSettings() {
  settings = {
    enabled: $("enabled").checked,
    activeStart: $("start").value || DEFAULT_SETTINGS.activeStart,
    activeEnd: $("end").value || DEFAULT_SETTINGS.activeEnd,
    notifyOnStart: $("notify").checked,
  };
  await chrome.storage.sync.set({ settings });
  render();
  send("settingsChanged");
}

for (const id of ["enabled", "start", "end", "notify"]) $(id).addEventListener("change", saveSettings);
$("start-now").addEventListener("click", async () => {
  $("start-now").disabled = true;
  $("start-now").textContent = "Starting…";
  await send("startNow");
});

// Show what we know instantly, then refresh from claude.ai.
({ state = {} } = await chrome.storage.local.get("state"));
({ settings = settings } = await chrome.storage.sync.get("settings"));
settings = { ...DEFAULT_SETTINGS, ...settings };
render();
send("refresh");
setInterval(render, 30_000);
