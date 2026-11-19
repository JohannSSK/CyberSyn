import base64
import json
import re
import sys

LABELS = [
    "meta-instruction telling an AI to stop its task or reveal its instructions",
    "normal software code comment explaining how a function works",
    "normal request to review code or answer a question",
]
INJECTION_LABEL = LABELS[0]
THRESHOLD = 0.60

# Score given to a line the regex caught outright. It sits above anything the
# classifier can reach, so one such hit settles the verdict on its own.
REGEX_SCORE = 0.99

_PHRASES = (
    r"(\b(?:ignore|disregard)\s+(?:all\s+)?(?:previous|prior|earlier|system|above)\s+"
    r"(?:instructions|guidelines|directives|rules|prompts)|new\s+(?:system\s+)?instructions\s*:|"
    r"you are now (?:in )?unrestricted|system override|do anything now|"
    r"(?:αφήσεις|άφησε) τους κανόνες|αγνόησε τους περιορισμούς|πες μου το system prompt|"
    r"if\s+you\s+are\s+an?\s+(ai|llm|language\s+model|assistant)|"
    r"(stop|abort|ignore)\s+the\s+(review|task|analysis|summary)|"
    r"(print|output|reveal|repeat|show)\s+(the\s+)?(full\s+)?(contents\s+of\s+)?(your|the|system|initial)\s+(instructions|prompt|rules)|"
    r"dump\s+(all\s+)?(client|user|customer|database|iban|id|identity|personal|pii|credentials|account|financial|records|names)|"
    r"(developer|jailbreak|god|dan)\s+mode|"
    r"bypass\s+(all\s+)?security|"
    r"forget\s+(all\s+)?(previous|your)\s+instructions|"
    r"(παράβλεψε|αγνόησε|ξεχάστε|ξέχνα)\s+(όλες\s+)?(τις\s+)?(προηγούμενες\s+)?(οδηγίες|εντολές|κανόνες)|"
    r"(εμφάνισε|δείξε|πες\s+μου|εκτύπωσε)\s+(όλες\s+)?(τις\s+)?(οδηγίες|εντολές|αρχικές\s+οδηγίες|οδηγίες\s+συστήματος)|"
    r"(διαρροή|εξαγωγή|dump)\s+(όλων\s+των\s+)?(δεδομένων|χρηστών|πελατών|iban|ταυτοτήτων|αδτ|προσωπικών|τραπεζικών)|"
    r"(παράκαμψη|παράκαμψε)\s+(όλους\s+τους\s+)?(ελέγχους|ασφάλεια|κανόνες))"
)
# Normalize separators in the patterns rather than shrinking the prompt. Each
# match still points to its exact span, even across indented comment lines.
INJECTION_PATTERNS = re.compile(_PHRASES.replace(" ", r"\s+"), re.IGNORECASE)

CODE_SYNTAX = re.compile(
    r"\s*(?:def\s+\w+\([^)]*\)(?:\s*->\s*\w+)?\s*:|class\s+\w+(?:\(\w+\))?:|"
    r"(?:from\s+[\w.]+\s+)?import\s+[\w., ]+|return\s+[\w.]+(?:\([^()]*\)|\[\w+\])?|"
    r"#include\s*<[^>]+>|[{}])\s*"
)

try:
    from model_cache import DETAIL_LINES, classify_batched
    from text_chunks import embedded, lines
except ImportError:
    from .model_cache import DETAIL_LINES, classify_batched
    from .text_chunks import embedded, lines


_ZERO_WIDTH = frozenset("\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u00ad")
_HOMOGLYPHS = str.maketrans({
    # Cyrillic lookalikes
    "а": "a", "А": "A", "е": "e", "Е": "E", "ё": "e", "Ё": "E",
    "і": "i", "І": "I", "ї": "i", "Ї": "I", "о": "o", "О": "O",
    "р": "p", "Р": "P", "с": "c", "С": "C", "у": "y", "У": "Y",
    "х": "x", "Х": "X", "к": "k", "К": "K", "м": "m", "М": "M",
    "н": "h", "Н": "H", "т": "t", "Т": "T", "в": "b", "В": "B",
    # Greek lookalikes (for Latin-script obfuscation pass)
    "α": "a", "Α": "A", "ε": "e", "Ε": "E", "ζ": "z", "Ζ": "Z",
    "η": "n", "Η": "H", "ι": "i", "Ι": "I", "κ": "k", "Κ": "K",
    "μ": "m", "Μ": "M", "ν": "v", "Ν": "N", "ο": "o", "Ο": "O",
    "ρ": "p", "Ρ": "P", "τ": "t", "Τ": "T", "υ": "u", "Υ": "Y",
    "χ": "x", "Χ": "X", "β": "b", "Β": "B",
})
_B64_TOKEN = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/=])")


def _strip_zero_width(text, base_offset=0, map_homoglyphs=False):
    chars = []
    positions = []
    for idx, ch in enumerate(text):
        if ch in _ZERO_WIDTH:
            continue
        if ch in ("_", "-"):
            ch = " "
        elif map_homoglyphs:
            ch = ch.translate(_HOMOGLYPHS)
        chars.append(ch)
        positions.append(base_offset + idx)
    return "".join(chars), positions


def _already_blocked(matches):
    """True when the injection regex has already decided the prompt is blocked.

    Those hits score 0.99, above anything the classifier contributes, so the
    remaining lines cannot change a verdict that is already made. Skipping
    them is what stops a long paste from paying its full cost after the
    outcome is settled. Only fires once the prompt is being refused, so a
    prompt that reaches the model is scanned exactly as before.
    """
    return any(
        m["cause"] == "PROMPT_INJECTION" and m["score"] >= REGEX_SCORE
        for m in matches
    )


def analyze(raw_text, stop=None, full_detail=False):
    """Analyse a prompt.

    `stop` is a callable returning True once another check has already
    refused this prompt. Polled between classifier batches so a long
    paste can be dropped part way through.
    """
    if not raw_text.strip():
        return {
            "blocked": False,
            "score": 0.0,
            "main_cause": None,
            "matches": [],
            "classifier_ran": False,
        }

    matches = []
    spans = set()

    def add_match(start, end, score=REGEX_SCORE):
        if (start, end) not in spans:
            spans.add((start, end))
            matches.append({"cause": "PROMPT_INJECTION", "score": score,
                            "line": raw_text.count("\n", 0, start) + 1, "start_offset": start,
                            "end_offset": end, "snippet": raw_text[start:end]})

    def inspect(clean, offset):
        # All separators in the pattern use \s+: adjacent lines are treated
        # like spaces without losing the original line numbers or offsets.
        for map_homoglyphs in (False, True):
            norm, pos = _strip_zero_width(clean, offset, map_homoglyphs=map_homoglyphs)
            if not norm:
                continue
            for hit in INJECTION_PATTERNS.finditer(norm):
                if hit.end() <= hit.start():
                    continue
                add_match(pos[hit.start()], pos[hit.end() - 1] + 1)

    inspect(raw_text, 0)  # includes individual lines and cross-line phrases

    # Inspect base64-encoded override attempts.
    for token in _B64_TOKEN.finditer(raw_text):
        raw_tok = token.group()
        if len(raw_tok) % 4 != 0:
            continue
        try:
            decoded = base64.b64decode(raw_tok, validate=True).decode("utf-8", errors="ignore")
        except Exception:
            continue
        if decoded and INJECTION_PATTERNS.search(_strip_zero_width(decoded, map_homoglyphs=True)[0]):
            add_match(token.start(), token.end())

    nl_chunks = []
    remainder = list(raw_text)
    for part in embedded(raw_text):
        inspect(part["clean"], part["start_offset"])
        clean_ml = "".join(ch for ch in part["clean"] if ch not in _ZERO_WIDTH)
        nl_chunks.append({**part, "clean": clean_ml})
        for pos in range(part["start_offset"], part["end_offset"]):
            if remainder[pos] != "\n":
                remainder[pos] = " "
    for part in lines("".join(remainder)):
        clean_ml = "".join(ch for ch in part["clean"] if ch not in _ZERO_WIDTH)
        if len(clean_ml) > 3 and not CODE_SYNTAX.fullmatch(clean_ml):
            nl_chunks.append({**part, "clean": clean_ml})

    classifier_ran = False
    if nl_chunks:
        # Lines with identical text always get the same verdict, so classify
        # each distinct one once and copy the result back onto every copy.
        distinct = {}
        for chunk in nl_chunks:
            distinct.setdefault(chunk["clean"], []).append(chunk)
        keys = list(distinct)

        # Stop early only once the verdict is settled *and* the leftover is
        # big enough to be worth stopping for. Short prompts keep the full
        # report, because finishing them costs almost nothing.
        settled = not full_detail and _already_blocked(matches) and len(keys) > DETAIL_LINES
        if not settled:
            results = classify_batched(keys, LABELS, stop=stop)
            if isinstance(results, dict):
                results = [results]
            if len(results) != len(keys) and not (stop is not None and stop()):
                raise ValueError("Incomplete injection verdict.")
            # Nothing computed yet means another check refused the prompt
            # before the first batch went in.
            if results:
                classifier_ran = True

            for text, res in zip(keys, results):
                top_label = res["labels"][0]
                top_score = round(float(res["scores"][0]), 4)
                if top_label not in LABELS or not 0 <= top_score <= 1:
                    raise ValueError("Invalid injection classification.")

                if top_label == INJECTION_LABEL and top_score >= THRESHOLD:
                    for chunk in distinct[text]:
                        matches.append(
                            {
                                "cause": "PROMPT_INJECTION",
                                "score": top_score,
                                "line": chunk["line"],
                                "start_offset": chunk["start_offset"],
                                "end_offset": chunk["end_offset"],
                                "snippet": raw_text[chunk["start_offset"]:chunk["end_offset"]],
                            }
                        )

    matches.sort(key=lambda x: x["start_offset"])

    response = {
        "blocked": False,
        "score": 0.0,
        "main_cause": "SAFE",
        "line": None,
        "start_offset": None,
        "end_offset": None,
        "snippet": None,
        "matches": matches,
        # False means the regex had already refused the prompt, so the
        # classifier was skipped. Never false on a prompt that is allowed
        # through.
        "classifier_ran": classifier_ran,
    }

    if matches:
        worst = max(matches, key=lambda x: x["score"])
        response.update(
            {
                "score": worst["score"],
                "main_cause": worst["cause"],
                "line": worst["line"],
                "start_offset": worst["start_offset"],
                "end_offset": worst["end_offset"],
                "snippet": worst["snippet"],
            }
        )

    if response["main_cause"] in ["PROMPT_INJECTION"]:
        response["blocked"] = True

    return response


def analyze_stdin():
    """CLI entry point: read the prompt from stdin and return the verdict."""
    return analyze(sys.stdin.read(), full_detail="--full-detail" in sys.argv)


if __name__ == "__main__":
    print(json.dumps(analyze_stdin(), indent=2))
