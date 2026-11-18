"""Running the three privacy checks.

The fast path calls each scanner in this process, so the models stay loaded
between prompts. The subprocess protocol survives as a fallback for when a
scanner cannot be imported — slower, but it keeps the app working on a
checkout whose models are missing.

Two rules hold everything else up:

*Fail closed.* A check that produces no verdict refuses the prompt. A scanner
that will not start must never look like a scanner that found nothing.

*Bounded.* The enabled checks share a size-aware deadline. Long pastes get
more time, up to a configured ceiling. Late verdicts are discarded and any
work still running is asked to stop cooperatively.

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

SCREEN_BUDGET = float(os.environ.get("CYBERSYN_SCREEN_BUDGET", 45))
MAX_SCREEN_BUDGET = float(os.environ.get("CYBERSYN_MAX_SCREEN_BUDGET", 180))
if not 0 < SCREEN_BUDGET <= MAX_SCREEN_BUDGET < float("inf"):
    raise ValueError("Set finite, positive screening budgets with the maximum at least the base.")


def screening_budget(prompt):
    """Keep the short-prompt budget; allow more work for longer pastes."""
    lines = sum(1 for line in prompt.splitlines() if line.strip())
    extra = max(0, (lines - 12) * 2, (len(prompt) - 2000) / 250)
    return min(MAX_SCREEN_BUDGET, SCREEN_BUDGET + extra)


class _ScannerFailure(ChatError):
    """A runner failure with a reason authored here, never copied from a scanner."""

    def __init__(self, stage, reason):
        super().__init__(f"{stage}: {reason}", 503)
        self.reason = reason


_DEPENDENCIES = "missing dependencies — ask your administrator to check the scanner installation"
_SETUP = "ask your administrator to check the gateway setup"


def _timeout_reason(seconds):
    return f"did not finish within {seconds:.4g}s — try a smaller paste"


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


def _missing_dependencies(text):
    return any(kind + ":" in (text or "") for kind in ("ModuleNotFoundError", "ImportError"))


def _why(text):
    """Explain a subprocess failure without copying arbitrary scanner output."""
    if _missing_dependencies(text):
        return _DEPENDENCIES
    return f"scanner exited without a usable verdict — {_SETUP}"


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
        raise _ScannerFailure(stage, "fallback scanner busy — try again")
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _ScannerFailure(stage, _timeout_reason(timeout))
        return _spawn(stage, prompt, remaining, policy)
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
    try:
        script = ROOT_DIR / PATHS[dict(CHECKS)[stage]]
    except KeyError:
        raise _ScannerFailure(stage, f"configured scanner not found — {_SETUP}") from None
    if not script.is_file():
        raise _ScannerFailure(stage, f"configured scanner not found — {_SETUP}")

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
        raise _ScannerFailure(stage, _timeout_reason(timeout)) from None
    except OSError:
        raise _ScannerFailure(stage, f"scanner could not be started — {_SETUP}") from None
    except UnicodeError:
        raise _ScannerFailure(stage, f"scanner exited without a usable verdict — {_SETUP}") from None

    result = find_result_json(proc.stdout or "")
    if result is None or proc.returncode:
        # Fail closed: no verdict means no permission to send. The reason is
        # carried through so the message says what to fix rather than just
        # that something broke.
        raise _ScannerFailure(stage, _why(proc.stderr or proc.stdout))
    return result


def run_check(stage, prompt, timeout=CHECK_TIMEOUT, stop=None, **policy):
    """Run one check and return its verdict dict.

    Raises ChatError when the check cannot produce a verdict, so the caller
    can keep the fail-closed guarantee.

    `stop` lets in-process scanners skip remaining detail after a decisive
    block or after the deadline. See scanners.run().
    """
    deadline = time.monotonic() + timeout
    available = registry.available(stage)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _ScannerFailure(stage, _timeout_reason(timeout))
    if not available:
        if SCANNER_FALLBACK:
            return _run_subprocess(stage, prompt, remaining, **policy)
        reason = _DEPENDENCIES if _missing_dependencies(registry.disabled_reason(stage)) else (
            f"scanner could not be loaded — {_SETUP}")
        raise _ScannerFailure(stage, reason)
    try:
        return registry.run(stage, prompt, stop=stop, **policy)
    except ImportError:
        raise _ScannerFailure(stage, _DEPENDENCIES) from None
    except OSError:
        raise _ScannerFailure(stage, f"scanner could not load its model files — {_SETUP}") from None
    except Exception:
        raise _ScannerFailure(stage, f"scanner failed — {_SETUP}") from None


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
        raise ChatError(f"Not sent — invalid saved screening policy. Please {_SETUP}.",
                        503, error_code="screening_failed")
    enabled = [stage for stage, _ in CHECKS if actions[stage] != "allow" or
               (stage == "check2" and actions["block_code"] != "allow")]
    if not enabled:
        return None

    budget = screening_budget(prompt)
    deadline = time.monotonic() + budget
    outcomes = {}
    blocked = threading.Event()

    def stopped():
        return blocked.is_set() or time.monotonic() >= deadline

    def work(stage):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        hits = failure = None
        try:
            policy = {}
            stage_actions = {actions[stage]}
            if stage == "check2" and actions["block_code"] != "allow":
                policy = {"block_code": True, "context_enabled": actions["check2"] != "allow"}
                stage_actions.add(actions["block_code"])
            if stage_actions & {"warn", "redact"}:
                policy["full_detail"] = True
            result = run_check(stage, prompt, remaining, stop=stopped, **policy)
            hits = _hits(stage, prompt, result, actions, legacy=legacy)
        except _ScannerFailure as exc:
            failure = exc.reason
        except Exception:
            # Don't echo prompt snippets, scanner output or arbitrary exceptions.
            failure = f"scanner returned an invalid result — {_SETUP}"
        finished = time.monotonic()
        outcomes[stage] = (finished, hits, failure)
        # A successful block can cut short extra detail. A check failure does
        # not cancel its peers: let them report any failures of their own.
        if finished < deadline and hits and "block" in hits:
            blocked.set()

    threads = []
    for stage in enabled:
        thread = threading.Thread(target=work, args=(stage,), daemon=True, name=f"cybersyn-{stage}")
        try:
            thread.start()
        except RuntimeError:
            outcomes[stage] = (time.monotonic(), None, "scanner worker could not be started — try again")
        else:
            threads.append(thread)
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))

    results, failures = {}, {}
    for stage in enabled:
        outcome = outcomes.get(stage)
        # A scanner can return a partial result on cancellation. Accept that
        # only after a block, never if it stopped because the clock ran out.
        if outcome is None or outcome[0] >= deadline:
            failures[stage] = _timeout_reason(budget)
        elif outcome[2]:
            failures[stage] = outcome[2]
        else:
            results[stage] = outcome[1]

    if failures:
        detail = "; ".join(f"{stage}: {reason}" for stage, reason in failures.items())
        prefix = "a check could not run" if len(failures) == 1 else "checks could not run"
        raise ChatError(f"Not sent — {prefix} ({detail}).", 503, error_code="screening_failed")

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
