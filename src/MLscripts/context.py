import json
import re
import sys

try:
    from identifiers import (
        CARD,
        GREEK_ID,
        IBAN,
        IPV4,
        PASSPORT,
        credential_matches,
        iban_score,
        id_score,
        ipv4_score,
        is_valid_luhn,
        passport_score,
    )
    from text_chunks import embedded, lines
except ImportError:
    from .identifiers import (
        CARD,
        GREEK_ID,
        IBAN,
        IPV4,
        PASSPORT,
        credential_matches,
        iban_score,
        id_score,
        ipv4_score,
        is_valid_luhn,
        passport_score,
    )
    from .text_chunks import embedded, lines

LABELS = [
    "computer source code",
    "legal contract or NDA",
    "internal company financial data",
    "confidential HR, payroll, or customer records",
    "general educational or technical question about business, law, or software",
    "leaked internal company document or confidential record",
    "normal everyday question",
]
SAFE_LABEL = "normal everyday question"
CODE_LABEL = "computer source code"
BLOCKED_LABELS = {
    "leaked internal company document or confidential record",
    "legal contract or NDA",
    "internal company financial data",
    "confidential HR, payroll, or customer records",
    "credentials or banking data",
}
THRESHOLD = 0.55

# Strict indicators describe records, not merely their subject matter.
FINANCE_PATTERNS = re.compile(
    r"\b(?:strictly confidential|do not distribute|internal use only|strictly private|"
    r"(?:our|unannounced) (?:q[1-4] )?(?:revenue|financials|earnings|valuation)|"
    r"(?:q[1-4] (?:revenue|earnings)|arr of|series [a-e])\b.{0,60}?[€$£]\s*\d)|"
    r"απόρρητ[οαη]|εμπιστευτικ[όάή]", re.I)
LEGAL_PATTERNS = re.compile(
    r"\b(?:hereby agree|proprietary trade secrets|(?:governing law|non-disclosure agreement)"
    r".{0,160}\bindemnification|indemnification.{0,160}\bgoverning law)\b", re.I)
HR_CUSTOMER_PATTERNS = re.compile(
    r"\b(?:layoff list|crm export|(?:attached|exported|our)\b.{0,35}\b(?:payroll|customer database)|"
    r"dump (?:all )?client data)\b", re.I)
_TOPICS = re.compile(r"\b(?:ebitda|valuation|balance sheet|cash flow|runway|nda|personal data|full name|surname|"
                     r"id card|payroll|salary|customer database|μισθός|ταυτότητα|έσοδα|κέρδη|σύμβαση|πνευματικά δικαιώματα)\b", re.I)
_EDUCATIONAL = re.compile(r"^(?:what (?:is|are|does)|explain|compare|describe|how (?:does|do|is)|write a sql (?:table|schema)|"
                          r"τι είναι|πώς (?:εκδίδεται|ορίζεται|λειτουργεί))\b", re.I)


# 5. Fast Source Code Syntax check
CODE_SYNTAX = re.compile(
    r"^\s*(def\s+\w+|class\s+\w+|import\s+\w+|from\s+\w+\s+import|return\s+|"
    r"if\s+.*:|elif\s+.*:|else:|for\s+.*:|while\s+.*:|try:|except\b|"
    r"(const|let|var|function)\s+\w+|#include\s*<|public\s+static\s+void|"
    r"\w+\s*=\s*[\[\{\(]|print\(.*\)|console\.log\(|"
    r"(?:export\s+(?:default\s+)?)?(?:interface|type)\s+\w+\s*[={<]|"
    r"func\s+(?:\([^)]+\)\s*)?\w+\s*\(|package\s+[a-z_]\w*\s*$|"
    r"(?:pub\s+)?(?:fn|struct|impl|enum)\s+\w+|#!\s*/(?:usr/)?bin/(?:env\s+)?(?:ba|z|fi)?sh\b|"
    r"(?i:SELECT\s+.+\s+FROM\b|INSERT\s+INTO\b|UPDATE\s+\w+\s+SET\b|DELETE\s+FROM\b|"
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|INDEX|FUNCTION)\b|ALTER\s+TABLE\b))"
)

try:
    from model_cache import DETAIL_LINES, classify_batched
except ImportError:  # pragma: no cover - standalone use from another cwd
    from .model_cache import DETAIL_LINES, classify_batched


def get_classifier():
    """Kept for callers that want the pipeline itself."""
    from model_cache import get_zero_shot

    return get_zero_shot()


def analyze(raw_text, stop=None, block_code=False, context_enabled=True, full_detail=False):
    """Analyse a prompt.

    `stop` is a callable that returns True once the verdict is already
    settled by another check. It is polled between classifier batches
    so a long paste can be dropped mid-scan; it never reduces the
    scrutiny given to a prompt that is going to be sent anywhere.
    """
    if not raw_text.strip():
        return {"blocked": False, "score": 0.0, "main_cause": None,
                "matches": [], "classifier_ran": False}

    matches = []
    unknown_chunks = []
    blocked_labels = BLOCKED_LABELS.copy() if context_enabled else set()
    if block_code:
        blocked_labels.add(CODE_LABEL)

    def hit(part, cause, score):
        matches.append({**part, "cause": cause, "score": score, "snippet": part["text"]})

    def identifier(match, score, tag):
        hit({"text": match[0], "line": raw_text.count("\n", 0, match.start()) + 1,
             "start_offset": match.start(), "end_offset": match.end(), "redaction_tag": tag},
            "credentials or banking data", score)

    # Inspect the full span first: an identifier and its context can cross a
    # line break. A code hit never suppresses a confidential hit on that line.
    if context_enabled:
        for pattern, score, tag in (
            (PASSPORT, passport_score, "PASSPORT"),
            (GREEK_ID, id_score, "GREEK_ID"),
            (IBAN, iban_score, "IBAN"),
            (IPV4, ipv4_score, "IPV4"),
        ):
            for m in re.finditer(pattern, raw_text):
                confidence = score(raw_text, m)
                if confidence >= 0.8:
                    identifier(m, confidence, tag)
        for m in credential_matches(raw_text):
            identifier(m, 0.96, "API_KEY")
        for m in CARD.finditer(raw_text):
            if is_valid_luhn(m[0]):
                identifier(m, 0.96, "CARD")

    # Inspect multi-line comments/docstrings as unified spans so split
    # confidential phrases are not lost across line breaks.
    multiline_spans = []
    if context_enabled:
        for fragment in embedded(raw_text):
            if "\n" not in fragment["text"]:
                continue
            multiline_spans.append((fragment["start_offset"], fragment["end_offset"]))
            merged = re.sub(r"\s+", " ", fragment["clean"]).strip()
            if len(merged) <= 3:
                continue
            if LEGAL_PATTERNS.search(merged):
                hit(fragment, "legal contract or NDA", 0.92)
            elif FINANCE_PATTERNS.search(merged):
                hit(fragment, "internal company financial data", 0.92)
            elif HR_CUSTOMER_PATTERNS.search(merged):
                hit(fragment, "confidential HR, payroll, or customer records", 0.92)
            else:
                unknown_chunks.append({**fragment, "classify_text": merged})

    secret_lines = {m["line"] for m in matches}
    for part in lines(raw_text):
        text = part["text"]
        if len(text) <= 3:
            continue
        is_code = bool(CODE_SYNTAX.search(text))
        if is_code:
            hit(part, CODE_LABEL, 0.90)
        if any(s <= part["start_offset"] and part["end_offset"] <= e for s, e in multiline_spans):
            continue
        if not context_enabled and is_code:
            continue
        if not full_detail and not block_code and part["line"] in secret_lines:
            continue  # the legacy context-only block already covers this line
        if context_enabled and LEGAL_PATTERNS.search(text):
            hit(part, "legal contract or NDA", 0.92)
        elif context_enabled and FINANCE_PATTERNS.search(text):
            hit(part, "internal company financial data", 0.92)
        elif context_enabled and HR_CUSTOMER_PATTERNS.search(text):
            hit(part, "confidential HR, payroll, or customer records", 0.92)
        elif is_code:
            for fragment in embedded(text):
                unknown_chunks.append({**fragment, "line": part["line"],
                                       "start_offset": part["start_offset"] + fragment["start_offset"],
                                       "end_offset": part["start_offset"] + fragment["end_offset"]})
        else:
            topics = set(t.casefold() for t in _TOPICS.findall(text))
            if (topics and len(text) <= 140 and _EDUCATIONAL.match(text) and
                    re.fullmatch(r"[\w ,?;;.'’-]+", text) and not re.search(r"\d|\bour\b", text, re.I)):
                continue  # a short definition/schema question without records or figures
            if context_enabled and len(topics) >= 2 and re.search(r"(?:[€$£]\s*\d|\d[\d.,]*\s*(?:%|EUR|USD))", text, re.I):
                hit(part, "leaked internal company document or confidential record", 0.90)
            else:
                unknown_chunks.append(part)

    for m in matches:
        m.pop("text", None)
        m.pop("clean", None)

    # Only load & run the heavy neural network on lines not already caught above
    default_score = 0.0
    classifier_ran = False
    if unknown_chunks:
        # Two lines with the same text always get the same verdict, so each
        # distinct line is classified once and the result is copied back onto
        # every copy of it. A pasted invoice, log or export collapses from
        # hundreds of repeated lines to a handful of calls, and nothing that
        # would have been caught is missed: the lines skipped here are
        # duplicates of lines that were examined.
        distinct = {}
        for chunk in unknown_chunks:
            distinct.setdefault(chunk.get("classify_text", chunk["text"]), []).append(chunk)
        keys = list(distinct)

        # Stop early only once the verdict is settled *and* the leftover is
        # big enough to be worth stopping for. A short prompt still gets the
        # complete report, because finishing it costs almost nothing.
        settled = (not full_detail and any(m["cause"] in blocked_labels for m in matches)
                   and len(keys) > DETAIL_LINES)
        if not settled:
            results = classify_batched(
                keys,
                LABELS,
                stop=stop,
                hypothesis_template="This text is {}.",
            )
            if isinstance(results, dict):
                results = [results]
            if len(results) != len(keys) and not (stop is not None and stop()):
                raise ValueError("Incomplete context verdict.")

            # Another check can refuse the prompt before the first batch is
            # even submitted, and then there is nothing computed to report.
            if results:
                classifier_ran = True
                default_score = round(float(results[0]["scores"][0]), 4)

            for text, res in zip(keys, results):
                top_label = res["labels"][0]
                top_score = round(float(res["scores"][0]), 4)
                if top_label not in LABELS or not 0 <= top_score <= 1:
                    raise ValueError("Invalid context classification.")
                if top_label != SAFE_LABEL and top_score >= THRESHOLD:
                    for chunk in distinct[text]:
                        matches.append({
                            "cause": top_label,
                            "score": top_score,
                            "line": chunk["line"],
                            "start_offset": chunk["start_offset"],
                            "end_offset": chunk["end_offset"],
                            "snippet": chunk["text"],
                        })

    matches.sort(key=lambda x: x["start_offset"])

    response = {
        "blocked": False,
        "score": default_score,
        "main_cause": SAFE_LABEL,
        "line": None,
        "start_offset": None,
        "end_offset": None,
        "snippet": None,
        "matches": matches,
        # False means the regexes had already refused the prompt, so the
        # neural net was skipped rather than paid for. Never false on a
        # prompt that is allowed through.
        "classifier_ran": classifier_ran,
    }

    if matches:
        blocking_matches = [m for m in matches if m["cause"] in blocked_labels]
        pool = blocking_matches if blocking_matches else matches
        worst = max(pool, key=lambda x: x["score"])
        response.update({
            "score": worst["score"],
            "main_cause": worst["cause"],
            "line": worst["line"],
            "start_offset": worst["start_offset"],
            "end_offset": worst["end_offset"],
            "snippet": worst["snippet"],
        })

    if response["main_cause"] in blocked_labels:
        response["matches"] = blocking_matches
        response["blocked"] = True

    return response


def analyze_stdin():
    """CLI entry point: read the prompt from stdin and return the verdict."""
    return analyze(sys.stdin.read(), block_code="--block-code" in sys.argv,
                   context_enabled="--code-only" not in sys.argv, full_detail="--full-detail" in sys.argv)


if __name__ == "__main__":
    print(json.dumps(analyze_stdin(), indent=2, ensure_ascii=False))
