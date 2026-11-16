import json
import os
import re
import sys
import warnings

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_VERBOSITY"] = "error"
warnings.filterwarnings("ignore")


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

INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|prompts)|"
    r"if\s+you\s+are\s+an?\s+(ai|llm|language\s+model|assistant)|"
    r"(stop|abort|ignore)\s+the\s+(review|task|analysis|summary)|"
    r"(print|output|reveal|repeat|show)\s+(the\s+)?(full\s+)?(contents\s+of\s+)?(your|the|system|initial)\s+(instructions|prompt|rules)|"
    r"dump\s+(all\s+)?(client|user|customer|database)|"
    r"(developer|jailbreak|god|dan)\s+mode|"
    r"bypass\s+(all\s+)?security|"
    r"forget\s+(all\s+)?(previous|your)\s+instructions)",
    re.IGNORECASE,
)

CODE_SYNTAX = re.compile(
    r"^\s*(def |class |import |from |return |if |elif |else:|for |while |try:|except|\w+\s*=\s*.+|print\(|.*[{}();].*)"
)

try:
    from model_cache import DETAIL_LINES, classify_batched
except ImportError:  # pragma: no cover - standalone use from another cwd
    from .model_cache import DETAIL_LINES, classify_batched


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


def analyze(raw_text, stop=None):
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
    nl_chunks = []
    offset = 0

    for line_num, line in enumerate(raw_text.splitlines(keepends=True), start=1):
        stripped = line.strip()
        if len(stripped) > 3:
            start_char = offset + line.find(stripped)
            end_char = start_char + len(stripped)
            normalized = re.sub(r"[_\-]+", " ", stripped)

            if INJECTION_PATTERNS.search(normalized):
                matches.append(
                    {
                        "cause": "PROMPT_INJECTION",
                        "score": 0.99,
                        "line": line_num,
                        "start_offset": start_char,
                        "end_offset": end_char,
                        "snippet": stripped,
                    }
                )
            elif stripped.startswith("#") or not CODE_SYNTAX.match(stripped):
                clean_text = stripped.lstrip("# ").strip()
                # Merge consecutive # comment lines so multi-line attacks stay together
                if (
                    stripped.startswith("#")
                    and nl_chunks
                    and nl_chunks[-1]["is_comment"]
                    and nl_chunks[-1]["end_line"] == line_num - 1
                ):
                    nl_chunks[-1]["end_line"] = line_num
                    nl_chunks[-1]["end_offset"] = end_char
                    nl_chunks[-1]["text"] += "\n" + stripped
                    nl_chunks[-1]["clean"] += " " + clean_text
                else:
                    nl_chunks.append(
                        {
                            "line": line_num,
                            "end_line": line_num,
                            "start_offset": start_char,
                            "end_offset": end_char,
                            "text": stripped,
                            "clean": clean_text,
                            "is_comment": stripped.startswith("#"),
                        }
                    )
        offset += len(line)

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
        settled = _already_blocked(matches) and len(keys) > DETAIL_LINES
        if not settled:
            results = classify_batched(keys, LABELS, stop=stop)
            if isinstance(results, dict):
                results = [results]
            # Nothing computed yet means another check refused the prompt
            # before the first batch went in.
            if results:
                classifier_ran = True

            for text, res in zip(keys, results):
                top_label = res["labels"][0]
                top_score = round(float(res["scores"][0]), 4)

                if top_label == INJECTION_LABEL and top_score >= THRESHOLD:
                    for chunk in distinct[text]:
                        matches.append(
                            {
                                "cause": "PROMPT_INJECTION",
                                "score": top_score,
                                "line": chunk["line"],
                                "start_offset": chunk["start_offset"],
                                "end_offset": chunk["end_offset"],
                                "snippet": chunk["text"],
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
    return analyze(sys.stdin.read())


if __name__ == "__main__":
    print(json.dumps(analyze_stdin(), indent=2))
