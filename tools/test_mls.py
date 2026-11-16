#!/usr/bin/env python3
"""Interactive debugger for the three scanners in src/MLscripts.

Pick a scanner, give it a prompt, read the JSON it hands back. That is the
whole tool — it exists so that "why did that get blocked?" is a question you
can answer in ten seconds instead of by adding print statements.

    python3 tools/test_mls.py                       # interactive menu
    python3 tools/test_mls.py context "sk-abc..."   # one shot, straight to JSON
    python3 tools/test_mls.py all -                 # all three, prompt on stdin
    python3 tools/test_mls.py --list                # what can run here

Importing a scanner is the first thing that pulls in torch and spaCy, so on
a machine without the models this says so plainly instead of dumping a
traceback. The scanners are loaded through src/scanners.py, which is exactly
how the app loads them, so what you see here is what a request would get.

Nothing here runs at import time. The file is named test_* so it sits with
the other checks, but it is a debugging tool, not an assertion: it takes no
part in a test run and always exits 0 unless something is genuinely broken.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import scanners  # noqa: E402

# The stage each scanner is wired to in src/scanners.py, in the order the
# checks run. The filename is what you picked in the menu; the stage is what
# the app calls it, and what appears in a block log.
CHOICES = [
    ("context", "check2"),
    ("greek_pii", "check1"),
    ("injection", "check3"),
]

BY_NAME = dict(CHOICES)
NAMES = [name for name, _ in CHOICES]

RULE = "-" * 66


# ---------------------------------------------------------------------------
# Running one scanner
# ---------------------------------------------------------------------------

def load(name):
    """Return the scanner's analyze(), or None with a printed reason."""
    stage = BY_NAME[name]
    fn = scanners.get_scanner(stage)
    if fn is None:
        reason = scanners.disabled_reason(stage) or "not loaded"
        print(f"  {name}.py is unavailable: {reason}")
        print("  Run ./setup.sh, or check that torch and spaCy are installed.")
        return None
    return fn


def summarise(result):
    """The few fields worth reading before the whole document."""
    keys = [
        ("blocked", "blocked"),
        ("main_cause", "main cause"),
        ("score", "score"),
        ("line", "line"),
        ("start_offset", "start"),
        ("end_offset", "end"),
        ("classifier_ran", "classifier ran"),
    ]
    out = []
    for key, label in keys:
        if key in result:
            out.append(f"  {label:>15} : {result[key]}")
    matches = result.get("matches")
    if isinstance(matches, list):
        out.append(f"  {'matches':>15} : {len(matches)}")
        for match in matches[:5]:
            where = f"line {match.get('line')}" if match.get("line") else "?"
            out.append(f"                   - {match.get('cause')} "
                       f"({match.get('score')}) {where}: "
                       f"{str(match.get('snippet'))[:60]}")
        if len(matches) > 5:
            out.append(f"                   ... and {len(matches) - 5} more")
    return "\n".join(out)

# A missing import is the usual reason a scanner will not run on a fresh
# checkout, and the module name is all it takes to say what to do about it.
DEPENDENCIES = {
    "transformers": "torch and transformers are not installed. Run ./setup.sh,",
    "torch": "torch is not installed. Run ./setup.sh, or:",
    "spacy": "spaCy is not installed. Run ./setup.sh, or:",
    "en_core_web_sm": "the English spaCy model is missing. Install it with:",
    "el_core_news_sm": "the Greek spaCy model is missing. Install it with:",
}

PIP_FIXES = {
    "transformers": "pip install torch transformers",
    "torch": "pip install torch",
    "spacy": "pip install spacy",
    "en_core_web_sm": ("pip install https://github.com/explosion/spacy-models/"
                       "releases/download/en_core_web_sm-3.8.0/"
                       "en_core_web_sm-3.8.0-py3-none-any.whl"),
    "el_core_news_sm": ("pip install https://github.com/explosion/spacy-models/"
                        "releases/download/el_core_news_sm-3.8.0/"
                        "el_core_news_sm-3.8.0-py3-none-any.whl"),
}


def dependency_hint(exc):
    """What to do about a ModuleNotFoundError, or None for anything else."""
    if not isinstance(exc, ModuleNotFoundError):
        return None
    missing = getattr(exc, "name", "") or str(exc)
    missing = missing.split(".")[0]
    install = PIP_FIXES.get(missing)
    if not install:
        return None
    return DEPENDENCIES[missing] + "\n\n      " + install


def run_one(name, prompt):
    """Run one scanner and print its verdict. Returns True if it ran."""
    fn = load(name)
    if fn is None:
        return False

    print(RULE)
    stage = BY_NAME[name]
    print(f"{name}.py  ({stage})")
    print(RULE)

    started = time.perf_counter()
    try:
        result = fn(prompt)
    except Exception as exc:  # noqa: BLE001 - a debugger shows the failure
        print(f"  raised {type(exc).__name__}: {exc}")
        print()
        hint = dependency_hint(exc)
        if hint:
            print(f"  {hint}")
            print()
        print("  The app treats a scanner that raises as fail-closed: the")
        print("  prompt would be refused, not waved through.")
        return False
    elapsed = (time.perf_counter() - started) * 1000

    print(summarise(result))
    print(f"  {'elapsed':>15} : {elapsed:.1f} ms")
    print()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()
    return True


# ---------------------------------------------------------------------------
# Reading a prompt
# ---------------------------------------------------------------------------

def read_prompt():
    """Read a multi-line prompt. A line with only a dot finishes it."""
    print("Type or paste the prompt. Finish with a line containing only .")
    print("(or Ctrl-D; blank lines are kept — the scanners see them too.)")
    lines = []
    try:
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == ".":
                break
            lines.append(line)
    except KeyboardInterrupt:
        print()
        return None
    return "\n".join(lines)


def describe(prompt):
    lines = prompt.splitlines()
    return f"{len(prompt)} chars, {len(lines)} line(s)"


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

def choose():
    """Ask which scanner. Returns a name, 'all', or None to quit."""
    print()
    print("Which scanner?")
    for index, (name, stage) in enumerate(CHOICES, start=1):
        print(f"  {index}) {name}.py  ({stage})")
    print("  a) all three")
    print("  q) quit")
    try:
        answer = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if answer in ("q", "quit", "exit", ""):
        return None
    if answer in ("a", "all"):
        return "all"
    if answer.isdigit() and 1 <= int(answer) <= len(CHOICES):
        return CHOICES[int(answer) - 1][0]
    if answer in BY_NAME or answer.rstrip(".py") in BY_NAME:
        return answer.rstrip(".py")
    print(f"  '{answer}' is not one of the options.")
    return choose()


def interactive():
    print("CyberSyn scanner debugger")
    print("Each scanner is loaded the way the app loads it, so the JSON below")
    print("is what a real request would be screened against.")
    print()
    print("The first prompt you run has to load the models — it is slow.")
    print("Ones after that are not.")

    while True:
        name = choose()
        if name is None:
            print("Bye.")
            return 0

        prompt = read_prompt()
        if prompt is None:
            continue
        if not prompt.strip():
            print("  (empty prompt: every scanner returns not-blocked)")
            print()

        print()
        print(f"Prompt: {describe(prompt)}")
        print()

        targets = NAMES if name == "all" else [name]
        for target in targets:
            run_one(target, prompt)


# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Give a prompt to one of the ML scanners and read the JSON.",
        epilog="With no arguments it asks you what to do.",
    )
    parser.add_argument(
        "scanner", nargs="?",
        help="one of: " + ", ".join(NAMES) + ", all",
    )
    parser.add_argument(
        "prompt", nargs="?",
        help="the prompt to screen; use - to read it from stdin",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="show which scanners can load on this machine, then exit",
    )
    args = parser.parse_args(argv)

    if args.list:
        print("Scanners on this machine:")
        for name, stage in CHOICES:
            ok = scanners.available(stage)
            note = "" if ok else f"  ({scanners.disabled_reason(stage)})"
            state = "imports" if ok else "cannot import"
            print(f"  {name + '.py':<16} {stage:<7} {state}{note}")
        print()
        print("That only means the module loads. The models themselves are")
        print("loaded on the first prompt, so run one to be certain.")
        return 0

    if args.scanner is None:
        return interactive()

    name = args.scanner.rstrip(".py")
    if name not in BY_NAME and name != "all":
        parser.error(f"unknown scanner '{args.scanner}'. "
                     f"Choose from: {', '.join(NAMES)}, all")

    if args.prompt is None:
        prompt = read_prompt()
        if prompt is None:
            return 0
    elif args.prompt == "-":
        prompt = sys.stdin.read()
    else:
        prompt = args.prompt

    targets = NAMES if name == "all" else [name]
    for target in targets:
        run_one(target, prompt)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
