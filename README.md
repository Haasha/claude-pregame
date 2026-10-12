# claude-pregame

**Start your Claude usage window before you start working.**

Claude's usage limit (Pro / Max) runs on a 5-hour window that starts with your first message.
Open Claude at 9:00 and you're locked into a window that ends at 14:00. If you burn through it by 11:00, you wait.

pregame runs quietly on your computer. As soon as a window resets, it sends one tiny message through
Claude Code so the next window is already running. When you sit down, your reset is hours closer.

```
without pregame:   you start 09:00 ───────────────────── reset 14:00
with pregame:      ping 06:00 ──── you start 09:00 ──── reset 11:00 ──── fresh window
```

## Install

One command. No repo to fork, no tokens to copy, no cron to write.

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/Haasha/claude-pregame/main/install.sh | sh
```

**Windows** (PowerShell)

```powershell
irm https://raw.githubusercontent.com/Haasha/claude-pregame/main/install.ps1 | iex
```

That's it. The installer sets up a background job (launchd, Task Scheduler, or systemd/cron),
starts your first window right away, and adds a `pregame` command.

**Needs:** [Claude Code](https://claude.com/claude-code) signed in with your Claude subscription
(run `claude` once and `/login`), and Python 3.8+ (already on most Macs and Linux machines;
on Windows: `winget install Python.Python.3.12`).

## Commands

```
pregame status      current window, last ping, next action
pregame logs        recent activity
pregame config      show settings file
pregame ping        start a window now
pregame uninstall   remove everything
```

## How it works

- Every 5 minutes, the background job asks: has the window reset?
- If yes, it runs `claude -p "Reply with only the word: ok" --model haiku` with tools, MCP servers,
  hooks and session history turned off. Cost: a few tokens on the smallest model.
- Claude Code reports the exact reset time, and pregame waits until then.
  Because that time comes from Anthropic's servers, it's right even if *you* started the window by chatting.
- Usage is shared across claude.ai, the desktop app and Claude Code, so this starts the window you use everywhere.

pregame never reads or stores your credentials. It only runs the `claude` command you're already signed in to.

**Why not a fixed cron job?** A single 6am ping only helps your first window. pregame chains windows
all day, follows the real reset time, and catches up after your laptop wakes from sleep.

## Settings

`pregame config` shows the file's location. Edit it to change:

| Key | Default | Meaning |
| --- | --- | --- |
| `active_hours` | `"06:00-23:00"` | Only ping in this local-time range (can wrap past midnight; `null` = always). **Set the start 2–4 hours before you usually begin work.** |
| `only_when_app_running` | `false` | Only ping while the Claude desktop app is open |
| `model` | `"haiku"` | Model used for the ping |
| `prompt` | `"Reply with only the word: ok"` | Message sent |
| `notify_on_ping` / `notify_on_error` | `false` / `true` | Desktop notifications |
| `retry_minutes` | `15` | Wait after a failed ping |

Example: you start at 09:00. With the default `06:00-23:00`, windows run 06–11, 11–16, 16–21 and 21–02,
so a fresh quota is ready at 11:00.

## Good to know

- **Your computer has to be awake.** Background jobs don't run during sleep; pregame catches up on wake.
  To ping while the lid is closed on a Mac, schedule a wake: `sudo pmset repeat wake MTWRFSU 05:58:00`.
- **It doesn't add usage.** It shifts *when* your 5-hour window resets. Weekly limits are unchanged.
- If `ANTHROPIC_API_KEY` is set, pregame hides it from the ping so the ping uses your subscription.
- Linux: systemd user timers stop when you log out unless you run `loginctl enable-linger`.

## Other ways to install

```bash
pipx install claude-pregame && pregame install   # once published to PyPI
git clone https://github.com/Haasha/claude-pregame && cd claude-pregame && ./install.sh
```

## Development

```bash
python3 -m unittest discover -s tests -v
python3 pregame.py install --dry-run    # show what would be written, change nothing
```

CI runs the tests and the one-line installer on macOS, Windows and Linux against a fake `claude`.

## Disclaimer

An unofficial community tool, not affiliated with or endorsed by Anthropic. Use in line with your plan's terms.

## License

MIT
