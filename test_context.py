import contextlib
import io
import json
import os
import re
import sys
import warnings

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_VERBOSITY"] = "error"
warnings.filterwarnings("ignore")

from transformers import pipeline, logging

logging.set_verbosity_error()

LABELS = [
    "computer source code",
    "legal contract or NDA",
    "internal company financial data",
    "normal everyday question",
]
SAFE_LABEL = "normal everyday question"
THRESHOLD = 0.55

# Explicit high-risk markers for Finance & Legal/NDA
FINANCE_PATTERNS = re.compile(
    r"\b(confidential|do not distribute|internal only|series [a-e]|post-money|pre-money|"
    r"valuation|term sheet|ebitda|gross margin|net burn|runway|q[1-4] (revenue|financial|earnings)|"
    r"unannounced (revenue|merger|acquisition))\b",
    re.IGNORECASE,
)

LEGAL_PATTERNS = re.compile(
    r"\b(non-disclosure agreement|nda|hereby agree|party a and party b|governing law|"
    r"indemnification|breach of contract|proprietary trade secrets|memorandum of understanding)\b",
    re.IGNORECASE,
)

with contextlib.redirect_stderr(io.StringIO()):
    classifier = pipeline(
        "zero-shot-classification",
        model="valhalla/distilbart-mnli-12-1",
    )


def analyze_stdin():
    raw_text = sys.stdin.read()
    if not raw_text.strip():
        return {
            "blocked": False,
            "score": 0.0,
            "main_cause": None,
            "matches": [],
        }

    chunks = []
    offset = 0
    for line_num, line in enumerate(raw_text.splitlines(keepends=True), start=1):
        stripped = line.strip()
        if len(stripped) > 3:
            start_char = offset + line.find(stripped)
            end_char = start_char + len(stripped)
            chunks.append(
                {
                    "line": line_num,
                    "start_offset": start_char,
                    "end_offset": end_char,
                    "text": stripped,
                }
            )
        offset += len(line)

    if not chunks:
        return {
            "blocked": False,
            "score": 0.0,
            "main_cause": None,
            "matches": [],
        }

    results = classifier(
        [c["text"] for c in chunks],
        candidate_labels=LABELS,
        hypothesis_template="This text contains {}.",
    )
    if isinstance(results, dict):
        results = [results]

    matches = []
    for chunk, res in zip(chunks, results):
        top_label = res["labels"][0]
        top_score = round(float(res["scores"][0]), 4)

        # 1. Explicit Legal/Contract markers
        if LEGAL_PATTERNS.search(chunk["text"]):
            matches.append(
                {
                    "cause": "legal contract or NDA",
                    "score": max(top_score, 0.92),
                    "line": chunk["line"],
                    "start_offset": chunk["start_offset"],
                    "end_offset": chunk["end_offset"],
                    "snippet": chunk["text"],
                }
            )
        # 2. Explicit Financial/Confidential markers
        elif FINANCE_PATTERNS.search(chunk["text"]):
            matches.append(
                {
                    "cause": "internal company financial data",
                    "score": max(top_score, 0.92),
                    "line": chunk["line"],
                    "start_offset": chunk["start_offset"],
                    "end_offset": chunk["end_offset"],
                    "snippet": chunk["text"],
                }
            )
        # 3. Pure ML Zero-Shot classification
        elif top_label != SAFE_LABEL and top_score >= THRESHOLD:
            matches.append(
                {
                    "cause": top_label,
                    "score": top_score,
                    "line": chunk["line"],
                    "start_offset": chunk["start_offset"],
                    "end_offset": chunk["end_offset"],
                    "snippet": chunk["text"],
                }
            )

    response = {
        "blocked": False,
        "score": round(float(results[0]["scores"][0]), 4),
        "main_cause": SAFE_LABEL,
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

    # Check cause after detection: block contracts/finance, allow source code
    if response["main_cause"] in [
        "legal contract or NDA",
        "internal company financial data",
    ]:
        response["blocked"] = True

    return response


if __name__ == "__main__":
    print(json.dumps(analyze_stdin(), indent=2, ensure_ascii=False))
