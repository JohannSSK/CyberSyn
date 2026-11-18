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

import scanners as registry

from config import BLOCK_KEYS, CHECKS, CHECK_TIMEOUT, PATHS, ROOT_DIR, SCANNER_FALLBACK
from errors import ChatError
from policy import ACTIONS, ACTION_FIELDS, rule_actions
from redaction import RedactionError, offsets, redact

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


def _why(text):
    """Explain an import failure without copying arbitrary scanner output."""
    if "ModuleNotFoundError:" in (text or ""):
        return "ModuleNotFoundError: install the scanner dependencies"
    return "scanner exited without a usable verdict"


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
            if isinstance(obj.get(key), bool):
                result = dict(obj)
                result["blocked"] = obj[key]
                return result
    return None


_fallback_slot = threading.BoundedSemaphore(1)


def _run_subprocess(stage, prompt, timeout=CHECK_TIMEOUT, **policy):
    deadline = time.monotonic() + timeout
    if not _fallback_slot.acquire(timeout=timeout):
        raise ChatError(f"{stage}: fallback scanner busy.")
    try:
        return _spawn(stage, prompt, max(0.001, deadline - time.monotonic()), policy)
    finally:
        _fallback_slot.release()


def _spawn(stage, prompt, timeout, policy):
    """Run a scanner as a script and read its verdict from stdout.

    The prompt goes in on stdin, which is the only input these scripts read.
    There used to be a second attempt passing it as a command-line argument;
    the scripts never look at argv, so that attempt scored an empty string
    and reported it as clean. It cost an extra interpreter start-up on every
    check and turned any scanner that failed to load its model into one that
    waved everything through.
    """
    key = dict(CHECKS)[stage]
    script = ROOT_DIR / PATHS[key]
    if not script.is_file():
        raise ChatError(f"Configured scanner for {stage} not found.")

    try:
        args = [sys.executable, str(script)]
        if policy.get("block_code"):
            args.append("--block-code")
        if not policy.get("context_enabled", True):
            args.append("--code-only")
        if policy.get("full_detail"):
            args.append("--full-detail")
        proc = subprocess.run(
            args, input=prompt,
            capture_output=True, text=True, encoding="utf-8",
            timeout=timeout, cwd=str(script.parent),
        )
    except subprocess.TimeoutExpired:
        raise ChatError(f"{stage} did not finish within {timeout:.0f}s.")
    except OSError:
        raise ChatError(f"{stage} could not be started.") from None

    result = find_result_json(proc.stdout or "")
    if result is None or proc.returncode:
        # Fail closed: no verdict means no permission to send. The reason is
        # carried through so the message says what to fix rather than just
        # that something broke.
        raise ChatError(
            f"{stage} could not be run: "
            + _why(proc.stderr or proc.stdout or "")
        )
    return result


def run_check(stage, prompt, timeout=CHECK_TIMEOUT, stop=None, **policy):
    """Run one check and return its verdict dict.

    Raises ChatError when the check cannot produce a verdict, so the caller
    can keep the fail-closed guarantee.

    `stop` is set by screen() the moment any check refuses the prompt, so
    the checks still running can abandon a long paste instead of pricing out
    the rest of it. See scanners.run().
    """
    if not registry.available(stage) and SCANNER_FALLBACK:
        return _run_subprocess(stage, prompt, timeout, **policy)
    try:
        return registry.run(stage, prompt, stop=stop, **policy)
    except Exception as exc:
        raise ChatError(f"{stage} failed: {type(exc).__name__}") from exc


def _screening_deadline():
    return time.monotonic() + SCREEN_BUDGET


CODE_CAUSE = "computer source code"
DETAIL_KEYS = ("line", "start_offset", "end_offset", "snippet")


def _hits(stage, prompt, result, actions, *, legacy=False):
    """Separate code and confidential votes from the shared context scanner."""
    if not isinstance(result, dict) or not isinstance(result.get("blocked"), bool):
        raise ValueError("Missing scanner verdict.")
    matches = result.get("matches", [])
    if not isinstance(matches, list):
        raise ValueError("Invalid scanner matches.")
    for match in matches:
        if not isinstance(match, dict) or not isinstance(match.get("cause"), str) or not match["cause"]:
            raise ValueError("Invalid scanner match.")
        score = match.get("score", 0)
        if type(score) not in (int, float) or not 0 <= score <= 1:
            raise ValueError("Invalid scanner match score.")
        line = match.get("line")
        if line is not None and (type(line) is not int or line < 1):
            raise ValueError("Invalid scanner match line.")
        start, end = offsets(prompt, match)
        if match.get("snippet") != prompt[start:end]:
            raise ValueError("Scanner match does not point to its snippet.")
    if not result["blocked"]:
        # A clean verdict can include non-violating diagnostics, such as a
        # weak identifier candidate or code where that rule is set to allow.
        return {}

    if not matches:
        # The legacy boolean-only scanner interface also accepted a primary
        # finding. Action-aware scanners must supply an actual match list.
        rule = "block_code" if stage == "check2" and result.get("main_cause") == CODE_CAUSE else stage
        if legacy and actions[rule] == "block" and isinstance(result.get("main_cause"), str):
            return {"block": build_block_info(stage, result)}
        raise ValueError("A triggered rule lacks matches.")

    grouped = {}
    for match in matches:
        rule = "block_code" if stage == "check2" and match["cause"] == CODE_CAUSE else stage
        action = actions[rule]
        if action != "allow":
            grouped.setdefault(action, []).append(match)
    if not grouped:
        raise ValueError("A triggered scanner has no enabled rule matches.")
    verdicts = {}
    for action, found in grouped.items():
        if action == "redact":
            verdicts[action] = found
        else:
            worst = max(found, key=lambda hit: hit.get("score", 0))
            verdicts[action] = build_block_info(stage, {
                "main_cause": worst["cause"], "matches": found,
                **{key: worst.get(key) for key in DETAIL_KEYS},
            })
    return verdicts


def screen(prompt, flags):
    """Run the enabled scanners in parallel against one deadline.

    Legacy flag callers still get None or the first block_info. New rules
    can also return a warning and/or a list of spans to redact. No scanner
    can shorten the others unless the prompt cannot go out.
    """
    actions = rule_actions(flags)
    legacy = not any(field in flags.keys() for field in ACTION_FIELDS.values())
    if any(action not in ACTIONS for action in actions.values()) or actions["check3"] == "redact":
        raise ChatError("Not sent — invalid saved screening policy.", 503)
    enabled = [stage for stage, _ in CHECKS if actions[stage] != "allow" or
               (stage == "check2" and actions["block_code"] != "allow")]
    if not enabled:
        return None

    deadline = _screening_deadline()
    results = {}
    failures = {}
    refused = threading.Event()

    def work(stage):
        remaining = max(0.001, deadline - time.monotonic())
        try:
            policy = {}
            stage_actions = {actions[stage]}
            if stage == "check2" and actions["block_code"] != "allow":
                policy = {"block_code": True, "context_enabled": actions["check2"] != "allow"}
                stage_actions.add(actions["block_code"])
            if stage_actions & {"warn", "redact"}:
                policy["full_detail"] = True
            result = run_check(stage, prompt, remaining, stop=refused.is_set, **policy)
            hits = _hits(stage, prompt, result, actions, legacy=legacy)
            results[stage] = hits
            if "block" in hits:
                refused.set()
        except Exception as exc:
            # An exception string may contain arbitrary scanner output. Only
            # report the stage and error type, never the original exception.
            failures.setdefault(stage, type(exc).__name__)
            refused.set()

    threads = [(stage, threading.Thread(target=work, args=(stage,), daemon=True, name=f"cybersyn-{stage}"))
               for stage in enabled]
    for _, thread in threads:
        thread.start()
    for stage, thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            refused.set()
            failures[stage] = f"did not finish within {SCREEN_BUDGET:.0f}s"

    if failures:
        detail = "; ".join(f"{stage}: {failures[stage]}" for stage in enabled if stage in failures)
        raise ChatError("Not sent — " + ("a check could not run" if len(failures) == 1
                                        else "checks could not run") + f" ({detail}).", 503)

    # Scanner order, not completion order, determines the primary finding.
    ordered = [results[stage] for stage in enabled]
    for hits in ordered:
        if "block" in hits:
            return hits["block"]
    redactions = [match for hits in ordered for match in hits.get("redact", [])]
    warnings = [hits["warn"] for hits in ordered if "warn" in hits]
    if warnings:
        primary = {key: value for key, value in warnings[0].items() if key != "blocked"}
        primary["matches"] = [dict(match, stage=info["stage"]) for info in warnings for match in info["matches"]]
        return {"action": "warn", "warn_info": dict(primary, will_redact=bool(redactions)), "redact_matches": redactions}
    if redactions:
        return {"action": "redact", "redact_matches": redactions}
    return None


def apply_redactions(prompt, matches):
    """Refuse instead of falling back to raw text if a span cannot be masked."""
    if not matches:
        return None
    try:
        return redact(prompt, matches)
    except RedactionError as exc:
        raise ChatError(f"Not sent — {exc}", 503) from None
