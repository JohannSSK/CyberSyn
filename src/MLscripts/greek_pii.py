import json
import re
import sys

try:
    from identifiers import (
        CARD,
        GREEK_ID,
        IBAN,
        INTL_PHONE,
        IPV4,
        PASSPORT,
        credential_matches,
        iban_score,
        id_score,
        ipv4_score,
        is_valid_intl_phone,
        is_valid_luhn,
        passport_score,
        valid_amka,
    )
    from model_cache import DETAIL_CHARS, run_ner
except ImportError:  # pragma: no cover - standalone use from another cwd
    from .identifiers import (
        CARD,
        GREEK_ID,
        IBAN,
        INTL_PHONE,
        IPV4,
        PASSPORT,
        credential_matches,
        iban_score,
        id_score,
        ipv4_score,
        is_valid_intl_phone,
        is_valid_luhn,
        passport_score,
        valid_amka,
    )
    from .model_cache import DETAIL_CHARS, run_ner

PATTERNS = {
    "PASSPORT": PASSPORT,
    "GREEK_AFM": r"\b\d{9}\b",
    "GREEK_AMKA": r"\b(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])\d{7}\b",
    "GREEK_PHONE": (
        r"(?<!\w)(?<!\d[ \t.-])"
        r"(?:(?:\+30|0030|\(\+30\)|\(0030\))[\s.-]*)?"
        r"(?:(?:\((?:2[\s.-]*\d[\s.-]*\d|6[\s.-]*9[\s.-]*\d)\))(?:[\s.-]*\d){7}"
        r"|\(2[\s.-]*\d[\s.-]*\d[\s.-]*\d\)(?:[\s.-]*\d){6}"
        r"|2(?:[\s.-]*\d){9}"
        r"|6[\s.-]*9(?:[\s.-]*\d){8})"
        r"\b(?![ \t.-]*\d)"
    ),
    "INTL_PHONE": INTL_PHONE,
    "GREEK_ID": GREEK_ID,
    "IBAN": IBAN,
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "CARD": CARD,
    "IPV4": IPV4,
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


# Causes that refuse a prompt once they score high enough. Shared by the
# verdict at the end and by the short-circuit below, so the two can never
# disagree about what counts as blocking.
BLOCKING_CAUSES = (
    "GREEK_AFM",
    "GREEK_AMKA",
    "GREEK_PHONE",
    "INTL_PHONE",
    "GREEK_ID",
    "GREEK_ID_CARD",
    "ID_CARD",
    "PASSPORT",
    "IBAN",
    "GREEK_IBAN",
    "EMAIL",
    "API_KEY",
    "CARD",
    "IPV4",
    "COMPANY",
    "PERSON",
)
BLOCK_SCORE = 0.8

TITLE_NAME_PATTERN = re.compile(
    r"\b(?:(?:[Ηη]|[Οο])\s+)?(?:[Κκ]α|[Κκ]|[Κκ]ος|[Κκ]υρία|[Κκ]ύριος|[Δδ]ις|[Δδ]ρ|Dr|Mr|Mrs|Ms|Prof)\.?\s+"
    r"((?:[Α-ΩΆΈΉΊΌΎΏ]\.\s+)?[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+(?:-[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+)*"
    r"(?:\s+[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+(?:-[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+)*)*)\b"
)

GREEK_SURNAME_REGEX = re.compile(
    r"\b[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]*(?:"
    r"όπουλος|οπούλου|όπουλου|όπουλο|οπουλος|οπουλου|οπουλο|"
    r"ίδης|ίδου|ίδη|ιδης|ιδου|ιδη|"
    r"άδης|άδου|άδη|αδης|αδου|αδη|"
    r"άκης|άκη|ακης|ακη|"
    r"άκος|άκου|άκο|ακος|ακου|ακο|"
    r"όγλου|ογλου|"
    r"έας|εας|"
    r"ούλης|ούλη|ουλης|ουλη|"
    r"άτος|άτου|άτο|ατος|ατου|ατο"
    r")\b"
)

INITIAL_SURNAME_PATTERN = re.compile(
    r"\b([Α-ΩΆΈΉΊΌΎΏ]\.\s+[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]{2,}(?:-[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+)*)\b"
)

TITLE_STRIP_REGEX = re.compile(
    r"^(?:(?:[Ηη]|[Οο])\s+)?(?:[Κκ]α|[Κκ]|[Κκ]ος|[Κκ]υρία|[Κκ]ύριος|[Δδ]ις|[Δδ]ρ|Dr|Mr|Mrs|Ms|Prof)\.?\s+",
    re.IGNORECASE,
)


def is_blocking(cause, score):
    return cause in BLOCKING_CAUSES and score >= BLOCK_SCORE


_COMMON = set("Αριστοτέλης Θουκυδίδης Ευριπίδης Σωκράτης Αλκιβιάδης Πολίτης Φορέας Τομέας Συγγραφέας "
              "Γραμματέας Εισαγγελέας Τραπεζίτης Στρατιώτης Ιδιώτης Μεσίτης Διαβήτης Πλανήτης Μαγνήτης "
              "Αθηναίος Κρητικός Γιατρός".casefold().split())
_PUBLIC = {"albert einstein", "alan turing", "isaac newton", "marie curie"}


def _not_private_name(name, text):
    return (name.casefold() in _COMMON or
            (name.casefold() in _PUBLIC and re.search(r"\b(who (was|is)|explain|describe|biography)\b", text, re.I)))


def analyze(raw_text, stop=None, full_detail=False):
    if not raw_text.strip():
        return {
            "blocked": False,
            "score": 0.0,
            "main_cause": None,
            "matches": [],
            "classifier_ran": False,
        }

    matches = [
        {"cause": "API_KEY", "score": 0.95, "line": get_line_number(raw_text, hit.start()),
         "start_offset": hit.start(), "end_offset": hit.end(), "snippet": hit[0]}
        for hit in credential_matches(raw_text)
    ]

    # 1. Check Regex + Greek Math & Context Rules
    claimed_spans = set()
    for label, pattern in PATTERNS.items():
        for match in re.finditer(pattern, raw_text):
            val = match.group().strip()
            start, end = match.start(), match.end()

            if label == "PASSPORT":
                score = passport_score(raw_text, match)
                if not score:
                    continue
                claimed_spans.add((start, end))
            elif label == "GREEK_AFM":
                if (start, end) in claimed_spans:
                    continue
                if is_valid_afm(val):
                    score = 1.0
                elif has_afm_context(raw_text, start, end):
                    score = 0.90
                else:
                    score = 0.50
            elif label == "IBAN":
                score = iban_score(raw_text, match)
                if not score:
                    continue
            elif label == "GREEK_ID":
                if (start, end) in claimed_spans:
                    continue
                score = id_score(raw_text, match)
            elif label == "INTL_PHONE":
                if not is_valid_intl_phone(val):
                    continue
                score = 0.90
            elif label == "IPV4":
                score = ipv4_score(raw_text, match)
                if not score:
                    continue
            elif label == "CARD":
                if not is_valid_luhn(val):
                    continue
                score = 0.95
            elif label == "GREEK_AMKA":
                if not valid_amka(val):
                    continue
                score = 0.98 if re.search("αμκα|amka", raw_text[max(0,start-80):end+80], re.I) else 0.85
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

    seen_spans = {(m["start_offset"], m["end_offset"]) for m in matches}

    def seen(start, end):
        if full_detail:
            # Keep partially overlapping names; the redactor will cover the
            # union rather than exposing the part outside a previous hit.
            return (start, end) in seen_spans
        return any(not (end <= s or start >= e) for s, e in seen_spans)

    # Detect titled person names (e.g. "Η κα. Ελένη Παπαδοπούλου") and Greek surnames
    for match in TITLE_NAME_PATTERN.finditer(raw_text):
        val = match.group(1).strip()
        start, end = match.start(1), match.end(1)
        span = (start, end)
        if not seen(start, end) and not _not_private_name(val, raw_text):
            seen_spans.add(span)
            matches.append(
                {
                    "cause": "PERSON",
                    "score": 0.85,
                    "line": get_line_number(raw_text, start),
                    "start_offset": start,
                    "end_offset": end,
                    "snippet": val,
                }
            )

    for match in INITIAL_SURNAME_PATTERN.finditer(raw_text):
        val = match.group(1).strip()
        start, end = match.start(1), match.end(1)
        span = (start, end)
        surname = val.split()[-1]
        if not seen(start, end) and not _not_private_name(val, raw_text) and not _not_private_name(surname, raw_text):
            seen_spans.add(span)
            matches.append(
                {
                    "cause": "PERSON",
                    "score": 0.85,
                    "line": get_line_number(raw_text, start),
                    "start_offset": start,
                    "end_offset": end,
                    "snippet": val,
                }
            )

    for match in GREEK_SURNAME_REGEX.finditer(raw_text):
        val = match.group().strip()
        start, end = match.start(), match.end()
        span = (start, end)
        if not seen(start, end) and not _not_private_name(val, raw_text):
            seen_spans.add(span)
            matches.append(
                {
                    "cause": "PERSON",
                    "score": 0.85,
                    "line": get_line_number(raw_text, start),
                    "start_offset": start,
                    "end_offset": end,
                    "snippet": val,
                }
            )

    # 2. Check ML (spaCy) for Full Person Names (First + Last name, >= 2 words) or Surnames.
    #    The pipelines are loaded here, not at import, so importing this module
    #    stays cheap and the cost lands on a prompt that actually needs it.
    #
    #    Skipped once a regex has already refused the prompt and the document
    #    is long enough for the pass to be worth skipping. NER can only add
    #    names to the report, never overturn the verdict, and it costs a full
    #    pass of both pipelines over the whole text.
    #
    #    A weak AFM hit at 0.50 does not settle anything - that is not
    #    blocking on its own, and a name found here could be - so the
    #    short-circuit needs a score at or above the block threshold.
    settled = (
        not full_detail and any(is_blocking(m["cause"], m["score"]) for m in matches)
        and len(raw_text) > DETAIL_CHARS
    )
    classifier_ran = False
    if not settled:
        for model, script_regex in [
            ("en_core_web_sm", r"^[A-Z][a-zA-Z-]+(?:\s+[A-Z][a-zA-Z-]+)+$"),
            (
                "el_core_news_sm",
                r"^[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+(?:-[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+)*"
                r"(?:\s+[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+(?:-[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+)*)+$",
            ),
        ]:
            if stop is not None and stop():
                break
            classifier_ran = True
            for ent in run_ner(model, raw_text).ents:
                if ent.label_ in ("PERSON", "PER"):
                    raw_name = ent.text.strip()
                    start_char = ent.start_char
                    end_char = ent.end_char
                    tm = TITLE_STRIP_REGEX.match(raw_name)
                    if tm:
                        prefix_len = tm.end()
                        name = raw_name[prefix_len:].strip()
                        start_char += prefix_len
                    else:
                        name = raw_name
                    span = (start_char, end_char)
                    is_full_name = (
                        len(name.split()) >= 2
                        and re.match(script_regex, name)
                    )
                    is_surname = (
                        len(name.split()) == 1
                        and (tm is not None or GREEK_SURNAME_REGEX.match(name))
                    )
                    if not seen(start_char, end_char) and (is_full_name or is_surname) and not _not_private_name(name, raw_text):
                        seen_spans.add(span)
                        matches.append(
                            {
                                "cause": "PERSON",
                                "score": 0.85,
                                "line": get_line_number(raw_text, start_char),
                                "start_offset": start_char,
                                "end_offset": end_char,
                                "snippet": raw_text[start_char:end_char],
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
        # False means a regex had already refused the prompt, so the spaCy
        # name pass was skipped. Never false on a prompt that is allowed
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

    if is_blocking(response["main_cause"], response["score"]):
        response["blocked"] = True
        response["matches"] = [m for m in matches if is_blocking(m["cause"], m["score"])]

    return response


def analyze_stdin():
    """CLI entry point: read the prompt from stdin and return the verdict."""
    return analyze(sys.stdin.read(), full_detail="--full-detail" in sys.argv)


if __name__ == "__main__":
    print(json.dumps(analyze_stdin(), indent=2, ensure_ascii=False))
