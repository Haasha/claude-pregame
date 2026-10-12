#!/usr/bin/env python3
"""claude-pregame: start your Claude 5-hour usage window before you start working.

Claude's session limit is a 5-hour window that begins with your first message.
pregame runs in the background, notices when the window has reset, and sends
one tiny message through Claude Code so a fresh window is already ticking by
the time you sit down.

Works on macOS (launchd), Windows (Task Scheduler) and Linux (systemd or cron).
Standard library only. Run `pregame --help` for commands.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

__version__ = "0.1.0"

APP_NAME = "claude-pregame"
WINDOW_SECONDS = 5 * 60 * 60
CHECK_INTERVAL_MINUTES = 5

SYSTEM = platform.system()  # "Darwin", "Windows" or "Linux"
IS_MAC = SYSTEM == "Darwin"
IS_WINDOWS = SYSTEM == "Windows"
HOME = Path.home()

# Keep child processes (claude, tasklist, powershell) from flashing a console window.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0


def _default_dirs() -> tuple[Path, Path]:
    if IS_WINDOWS:
        config = Path(os.environ.get("APPDATA") or HOME / "AppData" / "Roaming") / APP_NAME
        state = Path(os.environ.get("LOCALAPPDATA") or HOME / "AppData" / "Local") / APP_NAME
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / APP_NAME
        state = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local" / "state") / APP_NAME
    return (
        Path(os.environ.get("PREGAME_CONFIG_DIR") or config),
        Path(os.environ.get("PREGAME_STATE_DIR") or state),
    )


CONFIG_DIR, STATE_DIR = _default_dirs()
# Where the one-line installers put this script, and the `pregame` command they add.
if IS_WINDOWS:
    INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA") or HOME / "AppData" / "Local") / APP_NAME
    SHIM_PATH = HOME / ".local" / "bin" / "pregame.cmd"
else:
    INSTALL_DIR = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share") / APP_NAME
    SHIM_PATH = HOME / ".local" / "bin" / "pregame"
CONFIG_PATH = CONFIG_DIR / "config.json"
STATE_PATH = STATE_DIR / "state.json"
LOG_PATH = STATE_DIR / "pregame.log"

LAUNCHD_LABEL = "io.github.claude-pregame"
LAUNCHD_PLIST = HOME / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
SYSTEMD_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "systemd" / "user"
SYSTEMD_UNIT = APP_NAME
CRON_MARKER = f"# {APP_NAME}"
WINDOWS_TASK = APP_NAME

DEFAULT_APP_PROCESSES = {"Darwin": ["Claude"], "Windows": ["Claude.exe"]}.get(SYSTEM, ["claude-desktop"])

DEFAULT_CONFIG = {
    # Path to the `claude` CLI. null = find it automatically (pinned at install time).
    "claude_path": None,
    # Cheapest model; the ping only needs to exist, not be smart.
    "model": "haiku",
    "prompt": "Reply with only the word: ok",
    # Only ping inside this local-time range ("HH:MM-HH:MM", may wrap past
    # midnight). null = any time. Set the start 2-4 hours before you usually
    # begin work so your first reset lands mid-morning.
    "active_hours": "06:00-23:00",
    # Only ping while one of these processes is running (e.g. the Claude app).
    "only_when_app_running": False,
    "app_process_names": DEFAULT_APP_PROCESSES,
    # Wait this long after the reported reset before pinging, to avoid racing it.
    "grace_seconds": 60,
    # After a failed ping, wait this long before trying again.
    "retry_minutes": 15,
    # Desktop notifications for new windows and errors.
    "notify_on_ping": False,
    "notify_on_error": True,
}

# Credentials that would make Claude Code bill an API key instead of your
# subscription; an API-billed ping would not start the subscription window.
API_KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


# --------------------------------------------------------------------------- io


def log(msg: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{dt.datetime.now().isoformat(timespec='seconds')}  {msg}"
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    if sys.stdout is not None and sys.stdout.isatty():  # stdout is None under pythonw
        print(line)


def load_json(path: Path, default: dict) -> dict:
    try:
        return {**default, **json.loads(path.read_text(encoding="utf-8"))}
    except FileNotFoundError:
        return dict(default)
    except json.JSONDecodeError as e:
        sys.exit(f"{path} is not valid JSON: {e}")


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        save_json(CONFIG_PATH, DEFAULT_CONFIG)
    return load_json(CONFIG_PATH, DEFAULT_CONFIG)


def load_state() -> dict:
    return load_json(STATE_PATH, {})


def fmt_ts(ts: float | None) -> str:
    if not ts:
        return "-"
    return dt.datetime.fromtimestamp(ts).strftime("%a %H:%M:%S")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=NO_WINDOW, **kwargs)


def notify(title: str, message: str) -> None:
    try:
        if IS_MAC:
            script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
            run(["osascript", "-e", script], timeout=10)
        elif IS_WINDOWS:
            ps_title, ps_msg = (s.replace("'", "''") for s in (title, message))
            script = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
                "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                "$n = $t.GetElementsByTagName('text');"
                f"$n.Item(0).AppendChild($t.CreateTextNode('{ps_title}')) > $null;"
                f"$n.Item(1).AppendChild($t.CreateTextNode('{ps_msg}')) > $null;"
                "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($t))"
            )
            run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=20)
        elif shutil.which("notify-send"):
            run(["notify-send", title, message], timeout=10)
    except Exception:
        pass


# ----------------------------------------------------------------------- checks


def parse_hhmm(s: str) -> dt.time:
    h, m = s.strip().split(":")
    return dt.time(int(h), int(m))


def in_active_hours(cfg: dict, now: dt.datetime) -> bool:
    spec = cfg.get("active_hours")
    if not spec:
        return True
    start_s, end_s = spec.split("-")
    start, end, t = parse_hhmm(start_s), parse_hhmm(end_s), now.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end  # range wraps past midnight


def app_running(names: list[str]) -> bool:
    for name in names:
        try:
            if IS_WINDOWS:
                out = run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH", "/FO", "CSV"]).stdout
                if f'"{name.lower()}"' in out.lower():
                    return True
            elif run(["pgrep", "-x", name]).returncode == 0:
                return True
        except FileNotFoundError:
            pass
    return False


def resolve_claude(cfg: dict) -> str | None:
    path = cfg.get("claude_path")
    if path and Path(path).exists():
        return path
    found = shutil.which("claude")
    if found:
        return found
    # Background jobs often get a minimal PATH; check the usual install spots.
    candidates = [HOME / ".local" / "bin" / "claude", HOME / ".claude" / "local" / "claude",
                  Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude")]
    if IS_WINDOWS:
        appdata = Path(os.environ.get("APPDATA") or HOME / "AppData" / "Roaming")
        candidates = [HOME / ".local" / "bin" / "claude.exe", appdata / "npm" / "claude.cmd"]
    return next((str(c) for c in candidates if c.exists()), None)


# ------------------------------------------------------------------------- ping


def find_five_hour_limit(obj) -> dict | None:
    """Find the rate-limit info dict for the five_hour window anywhere in an event."""
    if isinstance(obj, dict):
        if obj.get("rateLimitType") == "five_hour" and "resetsAt" in obj:
            return obj
        children = obj.values()
    elif isinstance(obj, list):
        children = obj
    else:
        return None
    for v in children:
        found = find_five_hour_limit(v)
        if found:
            return found
    return None


def to_epoch_seconds(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v / 1000 if v > 1e12 else v


def send_ping(cfg: dict) -> dict:
    """Send one minimal message via Claude Code. Returns a result summary."""
    claude = resolve_claude(cfg)
    if not claude:
        return {"ok": False, "error": "`claude` CLI not found. Install Claude Code or set claude_path."}

    cmd = [
        claude, "-p", cfg["prompt"],
        "--model", cfg["model"],
        "--max-turns", "1",
        "--tools", "",
        "--setting-sources", "",      # don't run your hooks/plugins for a ping
        "--strict-mcp-config",        # don't start MCP servers
        "--disable-slash-commands",
        "--no-session-persistence",   # keep pings out of your session history
        "--output-format", "stream-json", "--verbose",
    ]
    env = {k: v for k, v in os.environ.items() if k not in API_KEY_ENV_VARS}
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        proc = run(cmd, cwd=STATE_DIR, env=env, timeout=180)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "claude timed out after 180s"}
    except OSError as e:
        return {"ok": False, "error": f"could not run {claude}: {e}"}

    result, limit = None, None
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result = event
        limit = find_five_hour_limit(event) or limit

    resets_at = to_epoch_seconds(limit.get("resetsAt")) if limit else None
    summary = {
        "resets_at": resets_at,
        "limit_status": limit.get("status") if limit else None,
        "utilization": limit.get("utilization") if limit else None,
    }
    if result is None:
        err = (proc.stderr or proc.stdout).strip()[-300:] or f"exit code {proc.returncode}"
        return {"ok": False, "error": err, **summary}
    if result.get("is_error"):
        return {"ok": False, "error": str(result.get("result"))[:300], **summary}
    return {"ok": True, "reply": str(result.get("result"))[:100], **summary}


# --------------------------------------------------------------------- commands


def decide(cfg: dict, state: dict, now: float) -> tuple[bool, str]:
    """Return (should_ping, reason)."""
    if not in_active_hours(cfg, dt.datetime.fromtimestamp(now)):
        return False, f"outside active hours ({cfg['active_hours']})"
    if cfg.get("only_when_app_running") and not app_running(cfg["app_process_names"]):
        return False, "Claude app not running"
    window_end = state.get("window_end", 0)
    if now < window_end:
        return False, f"window active until {fmt_ts(window_end)}"
    retry_after = state.get("retry_after", 0)
    if now < retry_after:
        return False, f"backing off after error until {fmt_ts(retry_after)}"
    return True, "window has reset"


def do_ping(cfg: dict, state: dict, send=send_ping) -> int:
    now = time.time()
    res = send(cfg)
    state["last_ping"] = now
    state["last_result"] = res
    grace = cfg["grace_seconds"]
    resets_at = res.get("resets_at")

    if res["ok"]:
        # Prefer the server's reset time: it's correct even if you started this
        # window yourself before the ping.
        if resets_at and resets_at > now:
            state["window_end"] = resets_at + grace
            source = "server"
        else:
            state["window_end"] = now + WINDOW_SECONDS + grace
            source = "estimated"
        state.pop("retry_after", None)
        log(f"ping ok; window resets {fmt_ts(state['window_end'] - grace)} ({source})")
        if cfg.get("notify_on_ping"):
            notify("Claude Pregame", f"New window started. Resets at {fmt_ts(state['window_end'] - grace)}.")
        save_json(STATE_PATH, state)
        return 0

    if res.get("limit_status") == "rejected" and resets_at and resets_at > now:
        # Window is active and you've used it up; nothing to do until it resets.
        state["window_end"] = resets_at + grace
        log(f"limit reached; window resets {fmt_ts(resets_at)}")
        save_json(STATE_PATH, state)
        return 0

    state["retry_after"] = now + cfg["retry_minutes"] * 60
    log(f"ping failed: {res['error']}")
    if cfg.get("notify_on_error") and now - state.get("last_error_notify", 0) > 6 * 3600:
        hint = " Run `claude` in a terminal and /login." if "auth" in res["error"].lower() else ""
        notify("Claude Pregame: ping failed", res["error"][:120] + hint)
        state["last_error_notify"] = now
    save_json(STATE_PATH, state)
    return 1


def cmd_check(args) -> int:
    cfg, state = load_config(), load_state()
    should, reason = decide(cfg, state, time.time())
    if not should:
        if args.verbose or args.dry_run:
            print(f"skip: {reason}")
        return 0
    if args.dry_run:
        print(f"would ping: {reason}")
        return 0
    return do_ping(cfg, state)


def cmd_ping(args) -> int:
    return do_ping(load_config(), load_state())


def cmd_status(args) -> int:
    cfg, state = load_config(), load_state()
    should, reason = decide(cfg, state, time.time())
    last = state.get("last_result") or {}
    window_end = state.get("window_end")
    print(f"config:        {CONFIG_PATH}")
    print(f"claude CLI:    {resolve_claude(cfg) or 'NOT FOUND'}")
    print(f"active hours:  {cfg.get('active_hours') or 'always'}")
    print(f"background:    {scheduler().describe()}")
    print(f"last ping:     {fmt_ts(state.get('last_ping'))}  {'ok' if last.get('ok') else last.get('error', '')}")
    if last.get("utilization") is not None:
        print(f"5h usage:      {last['utilization']}")
    print(f"window ends:   {fmt_ts(window_end - cfg['grace_seconds'] if window_end else None)}")
    print(f"next check:    {'ping now' if should else reason}")
    return 0


def cmd_logs(args) -> int:
    if not LOG_PATH.exists():
        print("no log yet")
        return 0
    print("\n".join(LOG_PATH.read_text(encoding="utf-8").splitlines()[-args.n:]))
    return 0


def cmd_config(args) -> int:
    load_config()
    print(CONFIG_PATH)
    print(CONFIG_PATH.read_text(encoding="utf-8"))
    return 0


# ------------------------------------------------------------------ schedulers


def check_command() -> list[str]:
    """The command the background job runs."""
    python = Path(sys.executable)
    if IS_WINDOWS:  # pythonw has no console window
        pythonw = python.with_name("pythonw.exe")
        python = pythonw if pythonw.exists() else python
    return [str(python), str(Path(__file__).resolve()), "check"]


def background_path(claude: str) -> str:
    dirs = [str(Path(claude).parent), str(Path(sys.executable).parent),
            "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    return ":".join(dict.fromkeys(dirs))


class Scheduler:
    name = "none"

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def is_installed(self) -> bool:
        return False

    def describe(self) -> str:
        if self.is_installed():
            return f"installed ({self.name}, every {CHECK_INTERVAL_MINUTES} min)"
        return "not installed (run: pregame install)"

    def write(self, path: Path, content: str | bytes, encoding: str = "utf-8") -> None:
        if self.dry_run:
            text = content.decode() if isinstance(content, bytes) else content
            print(f"--- would write {path}\n{text.rstrip()}\n")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding=encoding)

    def exec(self, cmd: list[str], check: bool = True, stdin: str | None = None) -> subprocess.CompletedProcess:
        if self.dry_run:
            print(f"--- would run: {' '.join(shlex.quote(c) for c in cmd)}")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        r = run(cmd, input=stdin)
        if check and r.returncode != 0:
            sys.exit(f"{' '.join(cmd[:3])} failed: {(r.stderr or r.stdout).strip()}")
        return r


class Launchd(Scheduler):
    name = "launchd"

    def domain(self) -> str:
        return f"gui/{os.getuid()}"

    def is_installed(self) -> bool:
        return LAUNCHD_PLIST.exists()

    def install(self, claude: str) -> None:
        plist = {
            "Label": LAUNCHD_LABEL,
            "ProgramArguments": check_command(),
            "StartInterval": CHECK_INTERVAL_MINUTES * 60,
            "ProcessType": "Background",
            "EnvironmentVariables": {"PATH": background_path(claude), "HOME": str(HOME)},
            "StandardOutPath": str(STATE_DIR / "launchd.out.log"),
            "StandardErrorPath": str(STATE_DIR / "launchd.err.log"),
        }
        self.exec(["launchctl", "bootout", self.domain(), str(LAUNCHD_PLIST)], check=False)
        self.write(LAUNCHD_PLIST, plistlib.dumps(plist))
        self.exec(["launchctl", "bootstrap", self.domain(), str(LAUNCHD_PLIST)])

    def uninstall(self) -> None:
        self.exec(["launchctl", "bootout", self.domain(), str(LAUNCHD_PLIST)], check=False)
        if not self.dry_run:
            LAUNCHD_PLIST.unlink(missing_ok=True)


class Systemd(Scheduler):
    name = "systemd user timer"

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("systemctl")) and run(["systemctl", "--user", "show-environment"]).returncode == 0

    def is_installed(self) -> bool:
        return (SYSTEMD_DIR / f"{SYSTEMD_UNIT}.timer").exists()

    def install(self, claude: str) -> None:
        exec_start = " ".join(f'"{c}"' for c in check_command())
        service = (
            "[Unit]\nDescription=claude-pregame: start Claude's 5-hour window early\n\n"
            f"[Service]\nType=oneshot\nExecStart={exec_start}\nEnvironment=\"PATH={background_path(claude)}\"\n"
        )
        timer = (
            f"[Unit]\nDescription=Run claude-pregame every {CHECK_INTERVAL_MINUTES} minutes\n\n"
            f"[Timer]\nOnCalendar=*:0/{CHECK_INTERVAL_MINUTES}\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n"
        )
        self.write(SYSTEMD_DIR / f"{SYSTEMD_UNIT}.service", service)
        self.write(SYSTEMD_DIR / f"{SYSTEMD_UNIT}.timer", timer)
        self.exec(["systemctl", "--user", "daemon-reload"])
        self.exec(["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT}.timer"])

    def uninstall(self) -> None:
        self.exec(["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT}.timer"], check=False)
        if not self.dry_run:
            for ext in ("timer", "service"):
                (SYSTEMD_DIR / f"{SYSTEMD_UNIT}.{ext}").unlink(missing_ok=True)
        self.exec(["systemctl", "--user", "daemon-reload"], check=False)


class Cron(Scheduler):
    name = "cron"

    def current(self) -> list[str]:
        r = run(["crontab", "-l"])
        return r.stdout.splitlines() if r.returncode == 0 else []

    def is_installed(self) -> bool:
        return shutil.which("crontab") is not None and any(CRON_MARKER in l for l in self.current())

    def install(self, claude: str) -> None:
        cmd = " ".join(shlex.quote(c) for c in check_command())
        line = f"*/{CHECK_INTERVAL_MINUTES} * * * * PATH={shlex.quote(background_path(claude))} {cmd} {CRON_MARKER}"
        lines = [l for l in self.current() if CRON_MARKER not in l] + [line]
        self.exec(["crontab", "-"], stdin="\n".join(lines) + "\n")

    def uninstall(self) -> None:
        lines = [l for l in self.current() if CRON_MARKER not in l]
        self.exec(["crontab", "-"], stdin="\n".join(lines) + "\n" if lines else "")


class TaskScheduler(Scheduler):
    name = "Task Scheduler"

    def is_installed(self) -> bool:
        return run(["schtasks", "/Query", "/TN", WINDOWS_TASK]).returncode == 0

    def task_xml(self) -> str:
        exe, *args = check_command()
        start = dt.datetime.now().replace(second=0, microsecond=0).isoformat()
        # Built as XML (not schtasks flags) so it also runs on battery and
        # catches up after sleep; schtasks' defaults skip both.
        return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>claude-pregame: start Claude's 5-hour usage window early</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT{CHECK_INTERVAL_MINUTES}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{xml_escape(exe)}</Command>
      <Arguments>{xml_escape(subprocess.list2cmdline(args))}</Arguments>
      <WorkingDirectory>{xml_escape(str(STATE_DIR))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""

    def install(self, claude: str) -> None:
        xml_path = Path(tempfile.gettempdir()) / f"{APP_NAME}-task.xml"
        self.write(xml_path, self.task_xml(), encoding="utf-16")
        self.exec(["schtasks", "/Create", "/TN", WINDOWS_TASK, "/XML", str(xml_path), "/F"])
        if not self.dry_run:
            xml_path.unlink(missing_ok=True)

    def uninstall(self) -> None:
        self.exec(["schtasks", "/Delete", "/TN", WINDOWS_TASK, "/F"], check=False)


def scheduler(dry_run: bool = False) -> Scheduler:
    if IS_MAC:
        return Launchd(dry_run)
    if IS_WINDOWS:
        return TaskScheduler(dry_run)
    if Systemd.available():
        return Systemd(dry_run)
    if shutil.which("crontab"):
        return Cron(dry_run)
    return Scheduler(dry_run)


def installed_by_script() -> bool:
    return Path(__file__).resolve().parent == INSTALL_DIR.resolve()


def write_shim(dry_run: bool) -> None:
    """Add a `pregame` command next to `claude` (~/.local/bin)."""
    script = Path(__file__).resolve()
    if IS_WINDOWS:
        # One line ending in `exit /b`, so cmd never re-reads this file after
        # `pregame uninstall` deletes it ("The batch file cannot be found").
        content = f'@"{sys.executable}" "{script}" %* & exit /b\r\n'
    else:
        content = f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n'
    if dry_run:
        print(f"--- would write {SHIM_PATH}\n{content.rstrip()}\n")
        return
    SHIM_PATH.parent.mkdir(parents=True, exist_ok=True)
    SHIM_PATH.write_text(content, encoding="utf-8")
    if not IS_WINDOWS:
        SHIM_PATH.chmod(0o755)


def cmd_install(args) -> int:
    cfg = load_config()
    claude = resolve_claude(cfg)
    if not claude:
        sys.exit("`claude` CLI not found. Install Claude Code first: https://claude.com/claude-code")
    sched = scheduler(args.dry_run)
    if type(sched) is Scheduler:
        sys.exit("No supported scheduler found (need launchd, Task Scheduler, systemd or cron).\n"
                 f"Run this every {CHECK_INTERVAL_MINUTES} minutes yourself: {subprocess.list2cmdline(check_command())}")
    if not args.dry_run:
        cfg["claude_path"] = claude
        save_json(CONFIG_PATH, cfg)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
    sched.install(claude)
    if installed_by_script():
        write_shim(args.dry_run)
    if args.dry_run:
        return 0

    print(f"Installed with {sched.name}. Checking every {CHECK_INTERVAL_MINUTES} min.")
    state = load_state()
    should, reason = decide(cfg, state, time.time())
    if should:
        print("Starting your first window...")
        if do_ping(cfg, state) != 0:
            err = load_state().get("last_result", {}).get("error", "")
            print(f"\nFirst ping failed: {err}")
            if "auth" in err.lower() or "login" in err.lower():
                print("Sign in to Claude Code (run `claude`, then /login). pregame will retry on its own.")
    else:
        print(f"No ping needed yet: {reason}")
    print()
    return cmd_status(args)


def cmd_uninstall(args) -> int:
    sched = scheduler(args.dry_run)
    if sched.is_installed() or args.dry_run:
        sched.uninstall()
    paths = [STATE_DIR, CONFIG_DIR, SHIM_PATH] + ([INSTALL_DIR] if installed_by_script() else [])
    for path in dict.fromkeys(paths):
        if not path.exists():
            continue
        if args.dry_run:
            print(f"--- would remove {path}")
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    if not args.dry_run:
        print("Uninstalled. Your Claude usage window is no longer managed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pregame", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="ping if the 5h window has reset (what the background job runs)")
    c.add_argument("--dry-run", action="store_true", help="say what would happen, don't ping")
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(func=cmd_check)
    sub.add_parser("ping", help="send a ping now, regardless of state").set_defaults(func=cmd_ping)
    sub.add_parser("status", help="show the current window and next action").set_defaults(func=cmd_status)
    lg = sub.add_parser("logs", help="show recent log lines")
    lg.add_argument("-n", type=int, default=20)
    lg.set_defaults(func=cmd_logs)
    sub.add_parser("config", help="print config path and contents").set_defaults(func=cmd_config)
    for name, func, text in (("install", cmd_install, "run in the background"),
                             ("uninstall", cmd_uninstall, "remove the background job")):
        sp = sub.add_parser(name, help=text)
        sp.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
        sp.set_defaults(func=func)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
