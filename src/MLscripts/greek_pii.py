import json
import re
import sys
import warnings

warnings.filterwarnings("ignore")

try:
    from model_cache import get_taggers
except ImportError:  # pragma: no cover - standalone use from another cwd
    from .model_cache import get_taggers

PATTERNS = {
    "GREEK_AFM": r"\b\d{9}\b",
    "GREEK_AMKA": r"\b(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])\d{7}\b",
    "GREEK_PHONE": r"(?:\+30[\s-]?)?(?:2\d[\s-]?\d{8}|69\d[\s-]?\d{7})\b",
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "API_KEY": r"\b(sk-[a-zA-Z0-9]{10,}|AKIA[0-9A-Z]{16})\b",
    "COMPANY": r"\b[Α-ΩΆΈΉΊΌΎΏA-Z][α-ωάέήίόύώa-zA-Z0-9\s\-&]{2,35}\s+(?:Ε\.?Π\.?Ε\.?|Α\.?Ε\.?|Ι\.?Κ\.?Ε\.?|Ο\.?Ε\.?|Ε\.?Ε\.?|Ltd\.?|Inc\.?|Corp\.?|LLC)",
}


def is_valid_afm(afm):
    total = sum(int(afm[i]) * (2 ** (8 - i)) for i in range(8))
    return (total % 11) % 10 == int(afm[8]) and afm != "000000000"


def has_afm_context(text, start, end):
    window = (
        text[max(0, start - 80) : min(len(text), end + 80)]
        .lower()
        .replace(".", "")
    )
    return any(
        w in window
        for w in [
            "αφμ",
            "afm",
            "tax",
            "vat",
            "εφορία",
            "εφορια",
            "τιμολόγιο",
            "τιμολογιο",
            "invoice",
            "δού",
            "δου",
        ]
    )


def get_line_number(text, char_offset):
    return text.count("\n", 0, char_offset) + 1


def analyze(raw_text):
    if not raw_text.strip():
        return {
            "blocked": False,
            "score": 0.0,
            "main_cause": None,
            "matches": [],
        }

    matches = []

    # 1. Check Regex + Greek Math & Context Rules
    for label, pattern in PATTERNS.items():
        for match in re.finditer(pattern, raw_text):
            val = match.group().strip()
            start, end = match.start(), match.end()

            if label == "GREEK_AFM":
                if is_valid_afm(val):
                    score = 1.0
                elif has_afm_context(raw_text, start, end):
                    score = 0.90
                else:
                    score = 0.50
            else:
                score = 0.95

            matches.append(
                {
                    "cause": label,
                    "score": score,
                    "line": get_line_number(raw_text, start),
                    "start_offset": start,
                    "end_offset": end,
                    "snippet": val,
                }
            )

    # 2. Check ML (spaCy) for Full Person Names (First + Last name, >= 2 words).
    #    The pipelines are loaded here, not at import, so importing this module
    #    stays cheap and the cost lands on a prompt that actually needs it.
    seen_spans = {(m["start_offset"], m["end_offset"]) for m in matches}
    nlp_en, nlp_el = get_taggers()
    for nlp, script_regex in [
        (nlp_en, r"^[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+$"),
        (
            nlp_el,
            r"^[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+(?:\s+[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+)+$",
        ),
    ]:
        for ent in nlp(raw_text).ents:
            if ent.label_ == "PERSON":
                name = ent.text.strip()
                span = (ent.start_char, ent.end_char)
                overlaps = any(
                    not (end <= s or start >= e)
                    for s, e in seen_spans
                    for start, end in [span]
                )
                if (
                    not overlaps
                    and len(name.split()) >= 2
                    and re.match(script_regex, name)
                ):
                    seen_spans.add(span)
                    matches.append(
                        {
                            "cause": "PERSON",
                            "score": 0.85,
                            "line": get_line_number(raw_text, ent.start_char),
                            "start_offset": ent.start_char,
                            "end_offset": ent.end_char,
                            "snippet": name,
                        }
                    )

    matches.sort(key=lambda x: x["start_offset"])

    response = {
        "blocked": False,
        "score": 0.0,
        "main_cause": None,
        "line": None,
        "start_offset": None,
        "end_offset": None,
        "snippet": None,
        "matches": matches,
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

    if (
        response["main_cause"]
        in [
            "GREEK_AFM",
            "GREEK_AMKA",
            "GREEK_PHONE",
            "EMAIL",
            "API_KEY",
            "COMPANY",
            "PERSON",
        ]
        and response["score"] >= 0.8
    ):
        response["blocked"] = True

    return response


def analyze_stdin():
    """CLI entry point: read the prompt from stdin and return the verdict."""
    return analyze(sys.stdin.read())


if __name__ == "__main__":
    print(json.dumps(analyze_stdin(), indent=2, ensure_ascii=False))
