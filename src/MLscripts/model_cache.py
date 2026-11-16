"""Shared, lazy model loading for the three scanners.

The checks used to each pay for their own model: greek_pii.py called
spacy.load() at import time, injection.py built a zero-shot pipeline at
import time, and context.py built the *same* zero-shot model again. Loading
that classifier twice costs a second load of the same weights.

Everything here is lazy and cached. A scanner that never runs never pays for
a model, and the first prompt pays once rather than three times over.
"""

import contextlib
import io
import os
import threading
import warnings

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")

warnings.filterwarnings("ignore")

ZERO_SHOT_MODEL = "valhalla/distilbart-mnli-12-1"

_EN = "en_core_web_sm"
_EL = "el_core_news_sm"

_lock = threading.RLock()
_spacy = {}
_zero_shot = None


@contextlib.contextmanager
def _quiet():
    """Model downloads chatter on stderr; the scanner protocol owns stdout."""
    with contextlib.redirect_stderr(io.StringIO()):
        yield


def get_spacy(model_name):
    """Return a loaded spaCy pipeline, loading it at most once."""
    with _lock:
        if model_name not in _spacy:
            import spacy

            with _quiet():
                _spacy[model_name] = spacy.load(model_name)
        return _spacy[model_name]


def get_taggers():
    """The two spaCy pipelines used for person names (English + Greek)."""
    return get_spacy(_EN), get_spacy(_EL)


def get_zero_shot(local_only=False):
    """The one zero-shot classifier shared by the context and injection checks.

    Prefer the copy baked into the container image; fall back to a download
    when running from a plain checkout where setup.sh did the fetching.

    `local_only` never reaches the network. Warm-up uses it: loading weights
    holds the cache lock, and every prompt queues behind that lock, so a
    start-up download would stall the first minute of conversation behind a
    transfer nobody asked for yet.
    """
    global _zero_shot
    with _lock:
        if _zero_shot is None:
            from transformers import logging, pipeline

            with _quiet():
                logging.set_verbosity_error()
                try:
                    _zero_shot = pipeline(
                        "zero-shot-classification",
                        model=ZERO_SHOT_MODEL,
                        local_files_only=True,
                    )
                except Exception:
                    if local_only:
                        raise
                    _zero_shot = pipeline(
                        "zero-shot-classification", model=ZERO_SHOT_MODEL
                    )
        return _zero_shot


def classify(texts, labels, **kwargs):
    """Run the shared classifier.

    Serialised behind the cache lock: transformers pipelines are not safe to
    call concurrently from several request threads.
    """
    clf = get_zero_shot()
    with _lock:
        return clf(texts, candidate_labels=labels, **kwargs)


def warm(names=("spacy", "zero-shot")):
    """Eagerly load models so the first real prompt is not the slow one.

    Called from a background thread at start-up, while the container is
    already serving requests. It only loads what is already on disk: a
    download here would hold the cache lock, and every prompt behind it,
    for as long as the transfer takes. Models that are not present yet are
    reported as skipped rather than fetched.
    """
    done, skipped = [], []
    try:
        if "spacy" in names:
            get_taggers()
            done.append("spacy")
        if "zero-shot" in names:
            try:
                get_zero_shot(local_only=True)
                done.append("zero-shot")
            except Exception:
                skipped.append("zero-shot")
    except Exception:
        skipped.append("spacy")
    return {"loaded": done, "skipped": skipped}
