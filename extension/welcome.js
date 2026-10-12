const box = document.getElementById("status");

async function refresh() {
  const res = await chrome.runtime.sendMessage({ type: "refresh" });
  const state = (res && res.state) || {};
  if (state.status === "signed_out") {
    box.className = "alert";
    box.innerHTML = 'One more step: <a href="https://claude.ai/login" target="_blank">sign in to claude.ai</a> in this browser. This page updates once you do.';
    setTimeout(refresh, 5000);
  } else if (state.status === "error") {
    box.className = "alert";
    box.textContent = `Couldn't reach claude.ai yet (${state.error}). Pregame will keep trying.`;
  } else if (state.status === "ok") {
    box.className = "card";
    const { settings } = res;
    const resetsAt = state.usage && state.usage.resetsAt;
    box.innerHTML = resetsAt && resetsAt > Date.now()
      ? `<strong>You're all set.</strong> Your current window resets at ${new Date(resetsAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}.`
      : `<strong>You're all set.</strong> Pregame will start your next window at ${settings.activeStart}.`;
  } else {
    setTimeout(refresh, 2000);
  }
}
refresh();
