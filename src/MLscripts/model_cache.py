"""Shared, lazy model loading for the three scanners.

The checks used to each pay for their own model: greek_pii.py called
spacy.load() at import time, injection.py built a zero-shot pipeline at
import time, and context.py built the *same* zero-shot model again. Loading
that classifier twice costs a second load of the same weights.

Everything here is lazy and cached. A scanner that never runs never pays for
a model, and the first prompt pays once rather than three times over.
"""

import os
import threading

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")

ZERO_SHOT_MODEL = "valhalla/distilbart-mnli-12-1"


def env_int(name, default):
    """Read an int tuning knob, falling back to `default` on anything odd."""
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


# Once a cheap regex has already refused the prompt, the neural net is only
# buying extra highlights for a verdict that is already made. Below these the
# leftover is cheap, so it is still examined and the report stays complete;
# above them the paste stops paying for detail nobody is going to read.
#
# Lines for the classifier (its cost is per chunk), characters for spaCy (its
# cost is per document). Smaller limits skip detail sooner after a block.
DETAIL_LINES = env_int("CYBERSYN_DETAIL_LINES", 12)
DETAIL_CHARS = env_int("CYBERSYN_DETAIL_CHARS", 1000)

_EN = "en_core_web_sm"
_EL = "el_core_news_sm"

_lock = threading.RLock()
_spacy = {}
_zero_shot = None


_ner_locks = {name: threading.RLock() for name in (_EN, _EL)}


def get_spacy(model_name):
    with _ner_locks[model_name]:
        if model_name not in _spacy:
            import spacy
            _spacy[model_name] = spacy.load(model_name, exclude=[
                "tagger", "parser", "attribute_ruler", "lemmatizer", "morphologizer", "senter",
            ])
        return _spacy[model_name]


def run_ner(model_name, text):
    with _ner_locks[model_name]:
        return get_spacy(model_name)(text)


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

            from huggingface_hub import snapshot_download

            logging.set_verbosity_error()
            try:
                model = snapshot_download(ZERO_SHOT_MODEL, local_files_only=True)
            except OSError:
                if local_only:
                    raise
                model = ZERO_SHOT_MODEL
            _zero_shot = pipeline("zero-shot-classification", model=model, device=-1)
        return _zero_shot


def classify(texts, labels, **kwargs):
    """Run the shared classifier.

    Serialised behind the cache lock: transformers pipelines are not safe to
    call concurrently from several request threads.
    """
    clf = get_zero_shot()
    with _lock:
        return clf(texts, candidate_labels=labels, **kwargs)


# The classifier is fed in batches so a scan can be abandoned part way
# through. Each sequence is scored on its own, so batching changes nothing
# about the answers — only how many are computed before we stop asking.
CLASSIFY_BATCH = max(1, env_int("CYBERSYN_CLASSIFY_BATCH", 8))


def classify_batched(texts, labels, stop=None, **kwargs):
    """Like classify(), but checking `stop` between batches.

    `stop` is a callable returning True once the answer no longer matters —
    another check has already refused the prompt, so finishing this scan
    cannot change what the user is told. The remaining lines are dropped and
    what has been computed so far is returned.

    Only ever called with a stop flag that means "this prompt is already
    refused". A prompt that is still going to be sent to a model is always
    classified in full.
    """
    if stop is None:
        return classify(texts, labels, **kwargs)

    if stop():
        return []
    clf = get_zero_shot()
    out = []
    for start in range(0, len(texts), CLASSIFY_BATCH):
        if stop():
            break
        batch = texts[start:start + CLASSIFY_BATCH]
        with _lock:
            if stop():
                break
            got = clf(batch, candidate_labels=labels, **kwargs)
        out.extend(got if isinstance(got, list) else [got])
    return out


def warm(names=("spacy", "zero-shot")):
    """Eagerly load models so the first real prompt is not the slow one.

    Called from a background thread at start-up, while the container is
    already serving requests. It only loads what is already on disk: a
    download here would hold the cache lock, and every prompt behind it,
    for as long as the transfer takes. Models that are not present yet are
    reported as skipped rather than fetched.
    """
    done, skipped = [], []
    loaders = {"spacy": get_taggers, "zero-shot": lambda: get_zero_shot(local_only=True)}
    for name in names:
        try:
            loaders[name]()
        except Exception:
            skipped.append(name)
        else:
            done.append(name)
    return {"loaded": done, "skipped": skipped}


def verify():
    """Used by both installers: importability alone cannot verify model weights."""
    import torch

    if torch.version.cuda is not None:
        raise RuntimeError("Expected the CPU build of PyTorch, not a CUDA wheel.")
    for name in (_EN, _EL):
        if "ner" not in get_spacy(name).pipe_names:
            raise RuntimeError(f"{name}: missing NER pipeline")
        run_ner(name, "A short model check.")
    result = get_zero_shot()("A friendly greeting.", candidate_labels=["greeting", "question"])
    if len(result["scores"]) != 2:
        raise RuntimeError("DistilBART did not return classification scores.")
    print(f"Verified CPU inference: {_EN}, {_EL}, {ZERO_SHOT_MODEL}")


if __name__ == "__main__":
    verify()
