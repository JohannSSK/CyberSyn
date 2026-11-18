"""In-process scanner registry.

Each check used to run as a separate `python greek_pii.py` subprocess, so
every prompt paid three interpreter start-ups and re-imported torch and
spaCy from scratch — seconds of latency that had nothing to do with the
actual work.

This module imports the scanners once and calls them directly. The
subprocess path survives as a fallback: if a scanner cannot be imported
(a missing model, a broken dependency), we still try to run it as a script
before giving up, so behaviour degrades rather than breaks.
"""

import importlib
import inspect
import sys
from pathlib import Path

from config import CHECKS, ML_DIR, PATHS

# Import the scanner named by the same registry as the subprocess runner.
SCANNERS = {stage: Path(PATHS[key]).stem for stage, key in CHECKS}

_cache = {}
_failures = {}


def _ensure_importable():
    if str(ML_DIR) not in sys.path:
        sys.path.insert(0, str(ML_DIR))


def get_scanner(stage):
    """Return the scanner's analyze() callable, or None if it cannot load."""
    if stage in _failures:
        return None
    if stage in _cache:
        return _cache[stage]

    module_name = SCANNERS.get(stage)
    if module_name is None:
        _failures[stage] = "unknown stage"
        return None

    _ensure_importable()
    try:
        module = importlib.import_module(module_name)
        fn = getattr(module, "analyze", None)
        if not callable(fn):
            raise AttributeError(f"{module_name}.analyze is not callable")
    except Exception as exc:
        _failures[stage] = f"{type(exc).__name__}: {exc}"
        return None

    _cache[stage] = fn
    return fn


def available(stage):
    """True when this check can run in-process."""
    return get_scanner(stage) is not None


def disabled_reason(stage):
    return _failures.get(stage)


def run(stage, prompt, stop=None, **policy):
    """Run one check and return its verdict dict.

    Raises RuntimeError if the check cannot run at all, so the caller can
    keep the fail-closed guarantee: a scanner that will not run must stop
    the prompt rather than wave it through.

    `stop` is passed through to scanners that accept it. It means "another
    check has already refused this prompt", and lets a scanner drop the rest
    of a long paste instead of pricing out work that cannot change the
    answer. Scanners that do not accept it simply scan in full.
    """
    fn = get_scanner(stage)
    if fn is None:
        raise RuntimeError(
            f"{stage} is unavailable: {_failures.get(stage, 'not loaded')}"
        )
    if stop is not None and _accepts_stop(fn):
        policy["stop"] = stop
    return fn(prompt, **policy)


def _accepts_stop(fn):
    """True when a scanner understands the stop flag.

    Decided from the signature rather than by trying the call and catching
    TypeError, so a genuine TypeError raised inside a scanner is still a
    failure instead of being mistaken for an old signature.
    """
    try:
        return "stop" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def preload():
    """Import every scanner module now.

    Importing is cheap once the models are lazy — it only binds the
    functions and compiles the regexes. The models themselves are loaded
    by model_cache.warm() on a background thread.
    """
    return {stage: get_scanner(stage) is not None for stage in SCANNERS}
