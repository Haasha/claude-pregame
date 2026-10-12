<p align="center"><img src="extension/icons/icon128.png" width="96" alt=""></p>

<h1 align="center">Pregame for Claude</h1>

<p align="center"><strong>Your Claude limit resets sooner, because the clock started before you did.</strong></p>

Claude's usage limit (Pro / Max) runs on a 5-hour window that starts with your first message.
Start at 9:00 and you're locked into a window that ends at 14:00. Use it up by 11:00 and you wait.

Pregame sends one tiny message for you as soon as each window resets, so when you sit down to work
your next reset is already on its way.

```
without Pregame:   you start 09:00 ───────────────────── reset 14:00
with Pregame:      auto 06:00 ──── you start 09:00 ──── reset 11:00 ──── fresh window
```

## Get it

### For everyone: browser extension

Works in Chrome, Edge, Brave and Arc on Mac, Windows and Linux. Nothing else to install.

**[Add to Chrome](#)** ← *Chrome Web Store listing coming soon*

1. Click **Add to Chrome**.
2. Make sure you're signed in to [claude.ai](https://claude.ai) in that browser.
3. Done. The toolbar icon shows how long until your next reset.

<details>
<summary>Install it manually before the store listing is live</summary>

1. Download `pregame-extension-*.zip` from the [latest release](https://github.com/Haasha/claude-pregame/releases/latest) and unzip it.
2. Open `chrome://extensions` and turn on **Developer mode** (top right).
3. Click **Load unpacked** and choose the unzipped folder.
</details>

### For developers: always-on command-line version

Runs as a background service, so it keeps going even when your browser is closed.
It uses [Claude Code](https://claude.com/claude-code) (signed in with your subscription) and Python 3.8+.

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/Haasha/claude-pregame/main/install.sh | sh
```

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/Haasha/claude-pregame/main/install.ps1 | iex
```

Then `pregame status`, `pregame logs`, `pregame uninstall`. Settings: `pregame config`.

Use one version or the other. Running both is harmless, just redundant.

## How it works

- Every minute it works out locally whether your window could have reset. It only contacts Claude when it might have.
- It reads your real reset time from Claude, the same number shown in Settings → Usage, so it stays correct even when *you* started the window by chatting.
- If no window is running and you're inside your chosen hours, it sends "hi":
  - the **extension** uses an incognito chat on claude.ai, so it never appears in your history;
  - the **command-line version** uses `claude -p` on the smallest model, with tools, hooks and history turned off.
- Usage is shared across claude.ai, the desktop app and Claude Code, so either way starts the window you use everywhere.

Pregame never sees your password and never sends data anywhere except claude.ai.

**Pick your hours.** By default Pregame works between 06:00 and 23:00. Set the start 2–4 hours before
you usually begin. Example: with 06:00 your windows run 06–11, 11–16, 16–21 and 21–02, so if you start at 09:00 a fresh quota is waiting at 11:00.

## Good to know

- **It doesn't add usage.** It shifts *when* your 5-hour window resets. Weekly limits are unchanged.
- **Your computer has to be awake.** The extension runs while your browser is open. The command-line version runs while your computer is awake, and both catch up when it wakes.
  On a Mac you can schedule a wake-up: `sudo pmset repeat wake MTWRFSU 05:58:00`.
- Each auto-start costs one tiny message.

## Project layout

```
extension/   browser extension (Manifest V3, no dependencies)
pregame.py   command-line version (Python standard library only)
install.sh   one-line installer for macOS / Linux
install.ps1  one-line installer for Windows
tests/       command-line tests (with a fake `claude`)
```

## Development

```bash
cd extension && npm test                  # extension logic + background worker against a fake claude.ai
python3 -m unittest discover -s tests -v  # command-line version
python3 scripts/package_extension.py      # build the Web Store zip into dist/
```

CI runs everything on macOS, Windows and Linux, including the one-line installers.

## Disclaimer

An unofficial community project, not affiliated with or endorsed by Anthropic.
It relies on claude.ai's web interface, which can change without notice. Use in line with your plan's terms.

## License

MIT
