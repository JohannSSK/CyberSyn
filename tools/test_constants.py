#!/usr/bin/env python3
"""includes/constants.json must be the only place these answers live.

The constants file names the host, the port, every directory the app
touches, and every API route. If a module writes one of those down for
itself, the two copies drift: someone edits the JSON, sees no effect, and
concludes the file is decoration.

This checks the file is not decoration — that each entry is real, and that
each one is what the app actually uses.

    python3 tools/test_constants.py
"""
import json
import os
import tempfile
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

CONSTANTS_FILE = ROOT / "includes" / "constants.json"

results = []


def check(name, ok, extra=""):
    results.append((name, ok))
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f" -> {extra}" if extra and not ok else ""))


# --------------------------------------------------------------------------
# The file itself
# --------------------------------------------------------------------------

check("constants.json exists", CONSTANTS_FILE.is_file(), str(CONSTANTS_FILE))
try:
    CONSTANTS = json.loads(CONSTANTS_FILE.read_text(encoding="utf-8"))
except Exception as exc:  # noqa: BLE001
    CONSTANTS = {}
    check("constants.json is valid JSON", False, f"{type(exc).__name__}: {exc}")

for key in ("HOST", "PORT", "PATHS", "ROUTES"):
    check(f"constants.json has {key}", key in CONSTANTS)

PATHS = CONSTANTS.get("PATHS", {})
ROUTES = CONSTANTS.get("ROUTES", {})
check("PORT is a number", isinstance(CONSTANTS.get("PORT"), int),
      repr(CONSTANTS.get("PORT")))

# --------------------------------------------------------------------------
# config.py reads it, and every path resolves to something real
# --------------------------------------------------------------------------

_tmp = tempfile.TemporaryDirectory()
os.environ.setdefault("CYBERSYN_DB_FILE", str(Path(_tmp.name) / "constants.db"))
import config  # noqa: E402

check("config reads the same file",
      config.CONSTANTS_FILE == CONSTANTS_FILE, str(config.CONSTANTS_FILE))
check("config.HOST comes from the file",
      config.HOST == CONSTANTS.get("HOST"), f"{config.HOST!r}")
check("config.PORT comes from the file",
      config.PORT == CONSTANTS.get("PORT"), f"{config.PORT!r}")

# The directories must exist. DB_FILE is the exception: it is a file that is
# created on first run, so what must exist is its parent.
for key in ("BACKEND_DIR", "FRONTEND_DIR", "TEMPLATES_DIR", "ML_DIR", "ASSETS_DIR"):
    if key in PATHS:
        p = config.repo_path(key)
        check(f"PATHS.{key} is a real directory ({PATHS[key]})", p.is_dir(), str(p))

if "DB_FILE" in PATHS:
    db = config.repo_path("DB_FILE")
    check("PATHS.DB_FILE sits in an existing directory", db.parent.is_dir(),
          str(db.parent))
    check("config.DB_FILE is that path unless the environment overrides it",
          config.DB_FILE == db or "CYBERSYN_DB_FILE" in __import__("os").environ,
          str(config.DB_FILE))

for stage, key in config.CHECKS:
    p = config.repo_path(key)
    check(f"PATHS.{key} names a real script", p.is_file(), str(p))


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


# --------------------------------------------------------------------------
# Every route is registered, and none is written down twice
# --------------------------------------------------------------------------

from app import create_app  # noqa: E402

app = create_app()
registered = {rule.rule for rule in app.url_map.iter_rules()}

missing = sorted(set(ROUTES.values()) - registered)
check("every ROUTES entry is registered in Flask", not missing, str(missing))

stray = sorted(r for r in registered
               if r.startswith("/api/") and r not in set(ROUTES.values()))
check("no API route exists outside constants.json", not stray, str(stray))

# A route written as a literal in Python is a second answer to a question
# the constants file has already answered.
hardcoded = []
for path in (ROOT / "src").rglob("*.py"):
    text = read(path)
    for m in re.finditer(r'\.post\(\s*"/api/|\.get\(\s*"/api/|add_url_rule\(\s*"/api/',
                         text):
        hardcoded.append(f"{path.relative_to(ROOT)}: {text[m.start():m.end()]}")
check("no Python module hardcodes an /api/ route", not hardcoded,
      "; ".join(hardcoded[:4]))

documented = set(re.findall(r'`POST (/api/[A-Za-z0-9_/-]+)`', read(ROOT / "API_Examples.md")))
check("API examples cover every registered endpoint", documented == set(ROUTES.values()),
      documented.symmetric_difference(ROUTES.values()))

# The browser uses symbolic keys; the template serializes this same registry.
js_routes = set()
for path in (ROOT / "src/static/js").rglob("*.js"):
    js_routes.update(re.findall(r'Api\.post\(\s*"([^"]+)"', read(path)))
check("every browser call uses a route key from constants.json", js_routes <= ROUTES.keys(), js_routes - ROUTES.keys())
check("every API route is wired into the browser", js_routes == ROUTES.keys(), ROUTES.keys() - js_routes)

# --------------------------------------------------------------------------
# The paths are used, not merely present
# --------------------------------------------------------------------------

sources = {}
for path in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tools").rglob("*.py")):
    sources[path] = read(path)
used = "\n".join(sources.values())

# Consumed by config: the entry is resolved, not merely present. The scanner
# scripts are resolved indirectly -- scanning.py looks the key up by stage --
# so those count as consumed through CHECKS.
indirect = {key for _, key in config.CHECKS}
for key in PATHS:
    consumed = (f'repo_path("{key}")' in used or f'PATHS["{key}"]' in used
                or key in indirect)
    check(f"PATHS.{key} is resolved by config, not just listed", consumed, key)

if indirect:
    check("the scanner scripts are looked up through CHECKS",
          "PATHS[" in read(ROOT / "src" / "scanning.py"))

# Taken up by the rest of the app: a directory constant nobody imports is a
# constant that has no effect. config.py itself does not count.
consumers = {name: [] for name in
             ("ML_DIR", "ASSETS_DIR", "STATIC_DIR", "TEMPLATES_DIR", "BACKEND_DIR")}
for path, text in sources.items():
    if path.name == "config.py":
        continue
    for name in consumers:
        # A wrapped `from config import (...)` splits the name onto its own
        # line, so match the name itself rather than the import line.
        if re.search(rf"\b{name}\b", text):
            consumers[name].append(path.name)

for name, importers in sorted(consumers.items()):
    check(f"{name} is imported by code outside config.py", bool(importers),
          f"importers: {sorted(set(importers))}")

check("ROUTES is referenced in the code", "ROUTES" in used)

# --------------------------------------------------------------------------

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
