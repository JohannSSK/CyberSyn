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
    "meta-instruction telling an AI to stop its task or reveal its instructions",
    "normal software code comment explaining how a function works",
    "normal request to review code or answer a question",
]
INJECTION_LABEL = LABELS[0]
THRESHOLD = 0.60

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

with contextlib.redirect_stderr(io.StringIO()):
    classifier = pipeline(
        "zero-shot-classification",
        model="valhalla/distilbart-mnli-12-1", local_files_only=True,
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

    if nl_chunks:
        results = classifier(
            [c["clean"] for c in nl_chunks], candidate_labels=LABELS
        )
        if isinstance(results, dict):
            results = [results]

        for chunk, res in zip(nl_chunks, results):
            top_label = res["labels"][0]
            top_score = round(float(res["scores"][0]), 4)

            if top_label == INJECTION_LABEL and top_score >= THRESHOLD:
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


if __name__ == "__main__":
    print(json.dumps(analyze_stdin(), indent=2))
