"""Running the three privacy checks.

The fast path calls each scanner in this process, so the models stay loaded
between prompts. The subprocess protocol survives as a fallback for when a
scanner cannot be imported — slower, but it keeps the app working on a
checkout whose models are missing.

Either way, a check that produces no verdict raises. The chat route refuses
the prompt rather than forwarding it: fail closed.
"""

import json
import subprocess
import sys
from pathlib import Path

import scanners as registry

from config import BLOCK_KEYS, CHECKS, CHECK_TIMEOUT, PATHS, ROOT_DIR, SCANNER_FALLBACK
from errors import ChatError


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


def _run_subprocess(stage, prompt):
    key = dict(CHECKS)[stage]
    script, tried = resolve_script(PATHS[key])
    if script is None:
        raise ChatError(
            f"Script for {stage} not found. Tried: "
            + ", ".join(str(t) for t in tried)
        )

    attempts = []
    for mode in ("stdin", "argument"):
        cmd = [sys.executable, str(script)]
        if mode == "argument":
            cmd.append(prompt)
        try:
            proc = subprocess.run(
                cmd, input=prompt if mode == "stdin" else "",
                capture_output=True, text=True, encoding="utf-8",
                timeout=CHECK_TIMEOUT, cwd=str(script.parent),
            )
        except subprocess.TimeoutExpired:
            raise ChatError(f"{stage} timed out after {CHECK_TIMEOUT}s.")
        except OSError as exc:
            raise ChatError(f"{stage} could not be started: {exc}")

        if proc.returncode == 0:
            result = find_result_json(proc.stdout or "")
            if result is not None:
                return result
        attempts.append(
            f"[{mode}] exit={proc.returncode} "
            f"stdout={_tail(proc.stdout)!r} stderr={_tail(proc.stderr)!r}"
        )

    raise ChatError(
        f"{stage}: could not find a JSON result with a 'blocked' field in the "
        f"script output. " + " | ".join(attempts)
    )


def run_check(stage, prompt):
    """Run one check and return its verdict dict."""
    try:
        return registry.run(stage, prompt)
    except Exception as exc:
        if not SCANNER_FALLBACK:
            raise ChatError(f"{stage} failed: {exc}")
        return _run_subprocess(stage, prompt)


def screen(prompt, flags):
    """Run every enabled check in order.

    Returns None when the prompt is clean, or the block info for the first
    check that stops it.
    """
    for stage, _ in CHECKS:
        if not flags.get(stage, True):
            continue
        result = run_check(stage, prompt)
        if result.get("blocked"):
            return build_block_info(stage, result)
    return None
