"""Stand-in for the `claude` CLI that prints stream-json like the real one.

FAKE_CLAUDE_MODE: ok (default) | auth | rejected
FAKE_CLAUDE_LOG:  if set, append {"argv": [...], "api_key_set": bool} per call
"""
import json
import os
import sys
import time

mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "api_key_set": "ANTHROPIC_API_KEY" in os.environ}) + "\n")


def emit(obj):
    print(json.dumps(obj), flush=True)


emit({"type": "system", "subtype": "init", "model": "claude-haiku-4-5", "apiKeySource": "none"})
if mode == "auth":
    emit({"type": "result", "is_error": True, "result": "Failed to authenticate: OAuth session expired and could not be refreshed"})
    sys.exit(1)

resets_at = int(time.time()) + 3 * 3600
status = "rejected" if mode == "rejected" else "allowed"
emit({"type": "rate_limit_event", "rate_limit_info": {
    "status": status, "resetsAt": resets_at, "rateLimitType": "five_hour", "utilization": 0.1}})
if mode == "rejected":
    emit({"type": "result", "is_error": True, "result": "Claude usage limit reached"})
    sys.exit(1)
emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}})
emit({"type": "result", "is_error": False, "result": "ok"})
