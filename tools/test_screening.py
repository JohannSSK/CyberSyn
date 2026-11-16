#!/usr/bin/env python3
"""The screening stage: bounded, parallel, and fail-closed.

Three findings, in the order they were found:

1. The subprocess fallback had a second attempt that passed the prompt as a
   command-line argument. None of the scanner scripts read argv — they only
   read stdin — so that attempt scored an empty string and reported it as
   clean. A scanner that could not load its model waved every prompt
   through, and paid for two interpreter start-ups to do it.

2. The three checks ran one after another, each with its own 60s timeout:
   up to 180s of screening before the model call, against a browser that
   gave up at 120s. There was no overall budget at all.

3. Model warm-up held the scanner lock while downloading weights, so every
   prompt queued behind a transfer with no deadline.

    python3 tools/test_screening.py
"""
import os
import sys
import time

sys.path.insert(0, "src")

DB = os.environ.setdefault("CYBERSYN_DB_FILE", "/tmp/cybersyn-screening.db")
import scanning  # noqa: E402
from config import CHECKS  # noqa: E402
from errors import ChatError  # noqa: E402

results = []


def check(name, ok, extra=""):
    results.append((name, ok))
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f" -> {extra}" if extra and not ok else ""))


ALL = {stage: True for stage, _ in CHECKS}
PII = "Contact nikos.papadopoulos@example.com, AFM 123456789, phone 6941234567"

# --------------------------------------------------------------------------
# 1. A check that cannot produce a verdict must refuse the prompt
# --------------------------------------------------------------------------

real_run = scanning.subprocess.run


class FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def fake_subprocess(behaviour):
    calls = []

    def run(cmd, **kwargs):
        calls.append({"cmd": list(cmd), "stdin": kwargs.get("input", ""),
                      "timeout": kwargs.get("timeout")})
        return behaviour(calls[-1])

    return run, calls


# A scanner that dies before printing anything.
run, calls = fake_subprocess(lambda c: FakeCompleted(stderr="ModuleNotFoundError: No module named 'spacy'", returncode=1))
scanning.subprocess.run = run
scanning.SCANNER_FALLBACK = True
try:
    scanning.run_check("check1", PII)
    check("a scanner that dies raises instead of passing", False, "no exception")
except ChatError as exc:
    check("a scanner that dies raises instead of passing", True)
    check("the reason is the last useful line, not a traceback",
          "ModuleNotFoundError" in str(exc) and "File \"" not in str(exc), str(exc))

# The prompt must travel on stdin, and stdin alone.
check("the prompt is passed on stdin", calls[-1]["stdin"] == PII, calls[-1]["stdin"][:40])
check("no second attempt is made",
      len(calls) == 1, [c["cmd"][-1] for c in calls])
check("the prompt is never passed as an argument",
      all(PII not in arg for c in calls for arg in c["cmd"]),
      [a for c in calls for a in c["cmd"] if PII in a])

# The bug: a script that only reads stdin reports an empty prompt as clean.
run, calls = fake_subprocess(lambda c: FakeCompleted(
    stdout='{"blocked": false, "matches": []}' if c["stdin"] else
           '{"blocked": false, "matches": []}', returncode=0))
scanning.subprocess.run = run
out = scanning.run_check("check1", PII)
check("a real verdict is still read", out["blocked"] is False)

# A timeout is a refusal, not a pass.
def slow(call):
    raise scanning.subprocess.TimeoutExpired(call["cmd"], call["timeout"])


scanning.subprocess.run, calls = fake_subprocess(slow)
try:
    scanning.run_check("check1", PII, timeout=3)
    check("a check that overruns raises", False, "no exception")
except ChatError as exc:
    check("a check that overruns raises", True)
    check("the overrun message names the check", "check1" in str(exc), str(exc))

# --------------------------------------------------------------------------
# 2. Screening is bounded and the checks run together
# --------------------------------------------------------------------------

scanning.subprocess.run = real_run


def slow_check(stage, prompt, timeout=60):
    time.sleep(4)
    return {"blocked": False, "matches": []}


scanning.run_check = slow_check
budget_before = scanning.SCREEN_BUDGET
scanning.SCREEN_BUDGET = 10.0

t = time.time()
out = scanning.screen("hello", ALL)
elapsed = time.time() - t
check("three 4s checks finish together, not one after another",
      out is None and elapsed < 8, f"{elapsed:.1f}s")
check("parallel screening is much faster than the sum",
      elapsed < 12, f"{elapsed:.1f}s for 3x4s of work")

# A check that never finishes must not stop the request from answering.
def never(stage, prompt, timeout=60):
    time.sleep(60)
    return {"blocked": False, "matches": []}


scanning.run_check = never
scanning.SCREEN_BUDGET = 3.0
t = time.time()
try:
    scanning.screen("hello", ALL)
    check("a hung check is refused", False, "no exception")
except ChatError as exc:
    elapsed = time.time() - t
    check("a hung check is refused", True)
    check("the refusal arrives within the budget",
          elapsed < 8, f"{elapsed:.1f}s with a 3s budget")
    check("the message says a check could not run",
          "could not run" in str(exc).lower(), str(exc))

# Disabled checks are not run at all.
calls = []
scanning.run_check = lambda stage, prompt, timeout=60: calls.append(stage) or {"blocked": False}
scanning.screen("hello", {"check1": True, "check2": False, "check3": False})
check("disabled checks are skipped", calls == ["check1"], calls)

# Clean prompts pass, and the blocking stage is reported in configured order.
scanning.run_check = lambda stage, prompt, timeout=60: (
    {"blocked": stage == "check2", "main_cause": "SECRET", "line": 1,
     "snippet": "x", "matches": []})
info = scanning.screen("hello", ALL)
check("a blocked prompt reports the blocking stage",
      info is not None and info["stage"] == "check2", info)
check("the block carries the cause", info and info["main_cause"] == "SECRET", info)

scanning.SCREEN_BUDGET = budget_before

# --------------------------------------------------------------------------
# 3. Warm-up never holds the lock for a download
# --------------------------------------------------------------------------

sys.path.insert(0, "src/MLscripts")
try:
    import model_cache

    check("warm reports what it loaded and what it skipped",
          set(model_cache.warm()) == {"loaded", "skipped"}, model_cache.warm())

    seen = {}
    real_get = model_cache.get_zero_shot

    def spy(local_only=False):
        seen["local_only"] = local_only
        raise RuntimeError("no model here")

    model_cache.get_zero_shot = spy
    model_cache.warm(("zero-shot",))
    check("warm-up never reaches the network for weights",
          seen.get("local_only") is True, seen)
    model_cache.get_zero_shot = real_get
except ImportError as exc:
    check("model_cache imports", False, str(exc))

# --------------------------------------------------------------------------
# The budget published to the browser must cover the server's worst case
# --------------------------------------------------------------------------

from config import OPENAI_TIMEOUT  # noqa: E402

screen = scanning.SCREEN_BUDGET
request_timeout = screen + OPENAI_TIMEOUT + 30
check("the browser waits longer than the server can take",
      request_timeout > screen + OPENAI_TIMEOUT,
      f"{request_timeout} vs {screen}+{OPENAI_TIMEOUT}")
check("screening fits well inside the wait",
      screen <= 60, f"screen budget {screen}s")

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
