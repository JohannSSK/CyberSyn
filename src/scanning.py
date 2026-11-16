"""Running the three privacy checks.

The fast path calls each scanner in this process, so the models stay loaded
between prompts. The subprocess protocol survives as a fallback for when a
scanner cannot be imported — slower, but it keeps the app working on a
checkout whose models are missing.

Two rules hold everything else up:

*Fail closed.* A check that produces no verdict refuses the prompt. A scanner
that will not start must never look like a scanner that found nothing.

*Bounded.* The three checks run together against one deadline, shared between
them, so a slow model cannot make the request outlast the browser's patience.
Whatever is still running when the deadline passes is abandoned: the request
answers, the work is dropped. A reply that arrives too late to be shown has
no value, and a hung check must not hang the conversation with it.

Either way the caller gets an answer: a verdict, or a refusal saying which
check could not be run.
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import scanners as registry

from config import BLOCK_KEYS, CHECKS, CHECK_TIMEOUT, PATHS, ROOT_DIR, SCANNER_FALLBACK
from errors import ChatError

# The whole screening stage shares this budget. It has to fit inside the
# browser's own timeout along with the model call that follows, otherwise a
# prompt can be refused by the clock while the server is still working.
#     python3 src/app.py   CYBERSYN_SCREEN_BUDGET=45
SCREEN_BUDGET = float(os.environ.get("CYBERSYN_SCREEN_BUDGET", 45))


def build_block_info(stage, result):
    matches = result.get("matches")
    return {
        "blocked": True,
        "stage": stage,
        "main_cause": result.get("main_cause") or "unknown",
        "line": result.get("line"),
        "start_offset": result.get("start_offset"),
        "end_offset": result.get("end_offset"),
        "snippet": result.get("snippet"),
        "matches": matches if isinstance(matches, list) else [],
    }


def _tail(text, n=300):
    return (text or "").strip()[-n:]


def _why(text):
    """The one line from a traceback that says what actually went wrong.

    A scanner that fails dumps a traceback on stderr. Showing 200 characters
    of it is noise; the last line is the answer ("ModuleNotFoundError: No
    module named 'spacy'"), and that is what tells someone what to install.
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return "no output"
    for line in reversed(lines):
        if line.startswith("File \"") or line.startswith("^") or line.startswith("+"):
            continue
        return line[:160]
    return lines[-1][:160]


def resolve_script(configured):
    """Find an ML script: configured path first, then src/MLscripts/<name>."""
    name = Path(configured).name
    candidates = [
        ROOT_DIR / configured,
        Path(__file__).resolve().parent / "MLscripts" / name,
        ROOT_DIR / "testenv" / "MLscripts" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c, candidates
    return None, candidates


def find_result_json(text):
    """Find the last JSON object in `text` carrying a blocked-like field.

    Handles one-line JSON, pretty-printed JSON, and JSON mixed into log
    output, which is what the fallback subprocess path produces.
    """
    decoder = json.JSONDecoder()
    found = []
    i = text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            found.append(obj)
        i = text.find("{", end)
    for obj in reversed(found):
        for key in BLOCK_KEYS:
            if key in obj:
                result = dict(obj)
                result["blocked"] = bool(obj[key])
                return result
    return None


def _run_subprocess(stage, prompt, timeout=CHECK_TIMEOUT):
    """Run a scanner as a script and read its verdict from stdout.

    The prompt goes in on stdin, which is the only input these scripts read.
    There used to be a second attempt passing it as a command-line argument;
    the scripts never look at argv, so that attempt scored an empty string
    and reported it as clean. It cost an extra interpreter start-up on every
    check and turned any scanner that failed to load its model into one that
    waved everything through.
    """
    key = dict(CHECKS)[stage]
    script, tried = resolve_script(PATHS[key])
    if script is None:
        raise ChatError(
            f"Script for {stage} not found. Tried: "
            + ", ".join(str(t) for t in tried)
        )

    try:
        proc = subprocess.run(
            [sys.executable, str(script)], input=prompt,
            capture_output=True, text=True, encoding="utf-8",
            timeout=timeout, cwd=str(script.parent),
        )
    except subprocess.TimeoutExpired:
        raise ChatError(f"{stage} did not finish within {timeout:.0f}s.")
    except OSError as exc:
        raise ChatError(f"{stage} could not be started: {exc}")

    result = find_result_json(proc.stdout or "")
    if result is None:
        # Fail closed: no verdict means no permission to send. The reason is
        # carried through so the message says what to fix rather than just
        # that something broke.
        raise ChatError(
            f"{stage} could not be run: "
            + _why(proc.stderr or proc.stdout or "")
        )
    return result


def run_check(stage, prompt, timeout=CHECK_TIMEOUT):
    """Run one check and return its verdict dict.

    Raises ChatError when the check cannot produce a verdict, so the caller
    can keep the fail-closed guarantee.
    """
    try:
        return registry.run(stage, prompt)
    except Exception as exc:
        if not SCANNER_FALLBACK:
            raise ChatError(f"{stage} failed: {exc}")
        return _run_subprocess(stage, prompt, timeout)


def _screening_deadline():
    return time.monotonic() + SCREEN_BUDGET


def screen(prompt, flags):
    """Run every enabled check, all at once, against one shared deadline.

    Returns None when the prompt is clean, or the block info for the first
    check that stops it. Raises ChatError — refusing the prompt — if any
    enabled check could not produce a verdict in time, because a check that
    did not run is not the same thing as a check that passed.
    """
    enabled = [stage for stage, _ in CHECKS if flags.get(stage, True)]
    if not enabled:
        return None

    deadline = _screening_deadline()
    results = {}
    failures = {}

    def work(stage):
        # Each check gets whatever is left of the shared budget, so three
        # slow checks cost one budget between them rather than three.
        remaining = max(1.0, deadline - time.monotonic())
        try:
            results[stage] = run_check(stage, prompt, remaining)
        except Exception as exc:  # noqa: BLE001 - recorded, then refused
            failures[stage] = exc

    # Daemon threads: if one is abandoned by the deadline it must not keep
    # the process from exiting.
    threads = [
        threading.Thread(target=work, args=(stage,), daemon=True,
                         name=f"cybersyn-{stage}")
        for stage in enabled
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            failures[thread.name.replace("cybersyn-", "")] = ChatError(
                f"did not finish within {SCREEN_BUDGET:.0f}s"
            )

    # Refuse rather than guess. Report every check that could not answer, so
    # the message says what to fix instead of blaming the prompt.
    if failures:
        detail = "; ".join(
            f"{stage}: {exc}" for stage, exc in sorted(failures.items())
        )
        raise ChatError(
            "Not sent — " + ("a check could not run" if len(failures) == 1
                             else "checks could not run") + f" ({detail}).",
            503,
        )

    # Checks are reported in their configured order, not in the order the
    # threads happened to finish, so the same prompt always names the same
    # stage.
    for stage, _ in CHECKS:
        if stage in results and results[stage].get("blocked"):
            return build_block_info(stage, results[stage])
    return None
