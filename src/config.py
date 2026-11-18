"""Configuration for CyberSyn: the constants file plus environment overrides.

Nothing here talks to Flask or the database, so every other module can
import it without worrying about cycles.
"""

import json
import os
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent


def find_constants_file():
    """Walk up from this file looking for includes/constants.json."""
    for folder in [SRC_DIR, *SRC_DIR.parents]:
        for d in ("includes", "include"):
            for n in ("constants.json", "constant.json"):
                p = folder / d / n
                if p.is_file():
                    return p
    raise FileNotFoundError(
        "Could not find includes/constants.json in any parent folder of " + str(SRC_DIR)
    )


CONSTANTS_FILE = find_constants_file()
ROOT_DIR = CONSTANTS_FILE.parent.parent

try:
    with CONSTANTS_FILE.open(encoding="utf-8") as fh:
        CONSTANTS = json.load(fh)
except (OSError, ValueError) as exc:
    raise SystemExit(f"CyberSyn: cannot read {CONSTANTS_FILE}: {exc}") from None

PATHS = CONSTANTS["PATHS"]
ROUTES = CONSTANTS["ROUTES"]


def repo_path(key):
    """A path from the PATHS table, relative to the repository root.

    Every directory and file the app touches is named in constants.json and
    resolved here, in one place. A path written directly into a module is a
    second answer to a question the constants file has already answered.
    """
    return ROOT_DIR / PATHS[key]


STATIC_DIR = repo_path("FRONTEND_DIR")
TEMPLATES_DIR = repo_path("TEMPLATES_DIR")
ML_DIR = repo_path("ML_DIR")
ASSETS_DIR = repo_path("ASSETS_DIR")
BACKEND_DIR = repo_path("BACKEND_DIR")
# An explicit path for Hugging Face's hub cache keeps the installed model
# independent of HOME, XDG_CACHE_HOME and HF_* from the installing shell.
MODEL_CACHE = ROOT_DIR / Path(os.environ.get("CYBERSYN_MODEL_CACHE") or PATHS["MODEL_CACHE"]).expanduser()


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# LiteLLM can fetch a remote price catalogue on import. Serving local pages
# and preparing the provider client do not need that fetch. This flag only
# controls the catalogue; actual model discovery and completions still call
# the configured provider.
if not _env_flag("CYBERSYN_LITELLM_NETWORK"):
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"


# A container must be able to bind 0.0.0.0 and pick its own database path
# without editing a tracked file, so the environment always wins.
HOST = os.environ.get("CYBERSYN_HOST") or CONSTANTS.get("HOST", "127.0.0.1")
try:
    PORT = int(os.environ.get("CYBERSYN_PORT") or CONSTANTS.get("PORT", 5000))
    if not 0 <= PORT <= 65535:
        raise ValueError
except (TypeError, ValueError):
    raise SystemExit("CyberSyn: set CYBERSYN_PORT (or PORT in includes/constants.json) "
                     "to an integer from 0 to 65535.") from None
DEBUG = _env_flag("CYBERSYN_DEBUG")
LOG_PROMPT_PREVIEW = _env_flag("CYBERSYN_LOG_PROMPT_PREVIEW", False)
MAX_PROMPT_CHARS = int(os.environ.get("CYBERSYN_MAX_PROMPT_CHARS", 16000))
ALLOW_PRIVATE_BASE = _env_flag("CYBERSYN_ALLOW_PRIVATE_BASE", True)

# Tests (and a container with a mounted volume) point this somewhere else.
DB_FILE = Path(os.environ.get("CYBERSYN_DB_FILE") or repo_path("DB_FILE"))
DB_FILE.parent.mkdir(parents=True, exist_ok=True)
# The store named in the constants file, which is where DB_FILE lives unless
# the environment has pointed the database somewhere else.
BACKEND_DIR.mkdir(parents=True, exist_ok=True)

# "NULL" is the wire format this API has always used for an absent value.
# It is a string, not JSON null, because the front end was built against it.
NULL = "NULL"

DEFAULT_MODEL = "gpt-4o-mini"
OPENAI_URL = os.environ.get(
    "OPENAI_URL", "https://api.openai.com/v1/chat/completions"
)
OPENAI_TIMEOUT = int(os.environ.get("CYBERSYN_AI_TIMEOUT", 60))
CHECK_TIMEOUT = int(os.environ.get("CYBERSYN_CHECK_TIMEOUT", 60))

# Run the checks in this process so the models stay loaded between prompts.
# Set CYBERSYN_SCANNER_FALLBACK=0 to disable the slower subprocess fallback.
SCANNER_FALLBACK = _env_flag("CYBERSYN_SCANNER_FALLBACK", True)

# Load the models on a background thread at start-up rather than on the
# first prompt, so nobody's first message waits for torch to start.
WARM_MODELS = _env_flag("CYBERSYN_WARM_MODELS", True)

CHECKS = [
    ("check1", "CHECK1_SCRIPT"),
    ("check2", "CHECK2_SCRIPT"),
    ("check3", "CHECK3_SCRIPT"),
]

# Names a scanner may use for its "blocked" field.
BLOCK_KEYS = ("blocked", "is_blocked", "block", "flagged")
