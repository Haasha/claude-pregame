import contextlib
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pregame-test-"))
os.environ["PREGAME_CONFIG_DIR"] = str(TMP / "config")
os.environ["PREGAME_STATE_DIR"] = str(TMP / "state")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pregame  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_claude.py"


def make_fake_claude() -> str:
    """A `claude` launcher for the fake, the same shape real installs use."""
    bindir = TMP / "bin"
    bindir.mkdir(exist_ok=True)
    if pregame.IS_WINDOWS:
        path = bindir / "claude.cmd"
        path.write_text(f'@"{sys.executable}" "{FAKE}" %*\r\n', encoding="utf-8")
    else:
        path = bindir / "claude"
        path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
        path.chmod(0o755)
    return str(path)


class Base(unittest.TestCase):
    def setUp(self):
        for d in (pregame.CONFIG_DIR, pregame.STATE_DIR):
            shutil.rmtree(d, ignore_errors=True)
        self.fake_log = TMP / "fake_calls.jsonl"
        self.fake_log.unlink(missing_ok=True)
        os.environ["FAKE_CLAUDE_LOG"] = str(self.fake_log)
        os.environ["FAKE_CLAUDE_MODE"] = "ok"
        self.cfg = pregame.load_config()
        self.cfg.update(claude_path=make_fake_claude(), active_hours=None, notify_on_error=False)
        pregame.save_json(pregame.CONFIG_PATH, self.cfg)


class TestHelpers(unittest.TestCase):
    def at(self, hhmm):
        return dt.datetime.combine(dt.date.today(), pregame.parse_hhmm(hhmm))

    def test_active_hours(self):
        day = {"active_hours": "06:00-23:00"}
        night = {"active_hours": "22:00-06:00"}
        self.assertTrue(pregame.in_active_hours(day, self.at("06:00")))
        self.assertFalse(pregame.in_active_hours(day, self.at("23:00")))
        self.assertTrue(pregame.in_active_hours(night, self.at("23:30")))
        self.assertTrue(pregame.in_active_hours(night, self.at("05:59")))
        self.assertFalse(pregame.in_active_hours(night, self.at("12:00")))
        self.assertTrue(pregame.in_active_hours({"active_hours": None}, self.at("03:00")))

    def test_find_limit_and_epoch(self):
        info = {"status": "allowed", "resetsAt": 1760300000, "rateLimitType": "five_hour"}
        event = {"type": "rate_limit_event", "rate_limit_info": info}
        self.assertEqual(pregame.find_five_hour_limit(event), info)
        self.assertIsNone(pregame.find_five_hour_limit({"rate_limit_info": {**info, "rateLimitType": "seven_day"}}))
        self.assertEqual(pregame.to_epoch_seconds(1760300000000), 1760300000)
        self.assertEqual(pregame.to_epoch_seconds("1760300000"), 1760300000)

    def test_decide(self):
        cfg = {**pregame.DEFAULT_CONFIG, "active_hours": None}
        now = time.time()
        self.assertTrue(pregame.decide(cfg, {}, now)[0])
        self.assertFalse(pregame.decide(cfg, {"window_end": now + 60}, now)[0])
        self.assertFalse(pregame.decide(cfg, {"retry_after": now + 60}, now)[0])
        self.assertTrue(pregame.decide(cfg, {"window_end": now - 1}, now)[0])


class TestPing(Base):
    def calls(self):
        return [json.loads(l) for l in self.fake_log.read_text(encoding="utf-8").splitlines()]

    def test_ping_ok_uses_server_reset_time(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-should-be-stripped"
        try:
            self.assertEqual(pregame.do_ping(self.cfg, {}), 0)
        finally:
            del os.environ["ANTHROPIC_API_KEY"]
        state = pregame.load_state()
        expected = time.time() + 3 * 3600 + self.cfg["grace_seconds"]
        self.assertAlmostEqual(state["window_end"], expected, delta=30)
        self.assertTrue(state["last_result"]["ok"])

        call = self.calls()[-1]
        self.assertFalse(call["api_key_set"], "API key must not reach claude")
        argv = call["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "", "empty args must survive the launcher")
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")

    def test_auth_failure_backs_off(self):
        os.environ["FAKE_CLAUDE_MODE"] = "auth"
        self.assertEqual(pregame.do_ping(self.cfg, {}), 1)
        state = pregame.load_state()
        self.assertIn("authenticate", state["last_result"]["error"])
        self.assertGreater(state["retry_after"], time.time())
        self.assertFalse(pregame.decide(self.cfg, state, time.time())[0])

    def test_limit_reached_waits_for_reset(self):
        os.environ["FAKE_CLAUDE_MODE"] = "rejected"
        self.assertEqual(pregame.do_ping(self.cfg, {}), 0)
        self.assertGreater(pregame.load_state()["window_end"], time.time() + 3600)

    def test_check_skips_inside_window(self):
        pregame.do_ping(self.cfg, {})
        n = len(self.calls())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pregame.main(["check", "-v"])
        self.assertEqual(len(self.calls()), n)
        self.assertIn("window active", out.getvalue())


class TestSchedulers(Base):
    def run_quiet(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = pregame.main(argv)
        return code, out.getvalue()

    def test_install_and_uninstall_dry_run(self):
        code, out = self.run_quiet(["install", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("would", out)
        self.assertEqual(self.run_quiet(["uninstall", "--dry-run"])[0], 0)

    def test_windows_task_xml_is_valid(self):
        xml = pregame.TaskScheduler().task_xml()
        root = ET.fromstring(xml.encode("utf-16"))
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(root.find(".//t:Interval", ns).text, "PT5M")
        self.assertEqual(root.find(".//t:DisallowStartIfOnBatteries", ns).text, "false")
        self.assertTrue(root.find(".//t:Arguments", ns).text.endswith("check"))

    def test_systemd_units(self):
        _, out = self.run_quiet_call(lambda: pregame.Systemd(dry_run=True).install(self.cfg["claude_path"]))
        self.assertIn("OnCalendar=*:0/5", out)
        self.assertIn("ExecStart=", out)

    def run_quiet_call(self, fn):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = fn()
        return result, out.getvalue()

    @unittest.skipUnless(os.environ.get("PREGAME_REAL_INSTALL"), "real scheduler install only in CI")
    def test_real_install_cycle(self):
        code, out = self.run_quiet(["install"])
        self.assertEqual(code, 0, out)
        self.assertTrue(pregame.scheduler().is_installed(), out)
        self.assertTrue(pregame.load_state()["last_result"]["ok"], out)
        self.assertEqual(self.run_quiet(["uninstall"])[0], 0)
        self.assertFalse(pregame.scheduler().is_installed())


if __name__ == "__main__":
    unittest.main()
