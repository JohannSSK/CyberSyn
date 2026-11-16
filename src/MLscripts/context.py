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
    "computer source code",
    "legal contract or NDA",
    "internal company financial data",
    "confidential HR, payroll, or customer records",
    "normal everyday question",
]
SAFE_LABEL = "normal everyday question"
CODE_LABEL = "computer source code"
BLOCKED_LABELS = {
    "legal contract or NDA",
    "internal company financial data",
    "confidential HR, payroll, or customer records",
    "credentials or banking data",
}
THRESHOLD = 0.55

# 1. Financial, Revenue, Valuation, Accounting (English + Greek)
FINANCE_PATTERNS = re.compile(
    r"(\b(confidential|do not distribute|internal use only|strictly private|"
    r"series [a-e]|post-money|pre-money|valuation|term sheet|ebitda|gross margin|"
    r"net burn|burn rate|runway|p&l|profit and loss|balance sheet|cash flow|"
    r"cap table|revenue forecast|financial projection|audit report|tax return|"
    r"q[1-4]\s+(revenue|financial|earnings|results|numbers)|"
    r"unannounced\s+(revenue|merger|acquisition|deal|partnership)|"
    r"arr\s+of\s+[\$€£]\d+|[\$€£]\d+(\.\d+)?\s*(m|b|k|million|billion)\s+(revenue|valuation|arr|funding|profit|loss))\b|"
    r"(εμπιστευτικό|απόρρητο|ισολογισμός|έσοδα|κέρδη|ζημίες|προϋπολογισμός|οικονομικά στοιχεία|ρευστότητα))",
    re.IGNORECASE,
)

# 2. Legal, Contracts, NDAs, Board/M&A (English + Greek)
LEGAL_PATTERNS = re.compile(
    r"(\b(non-disclosure agreement|nda|hereby agree|party a and party b|governing law|"
    r"indemnification|breach of contract|proprietary trade secrets|memorandum of understanding|"
    r"exclusivity clause|arbitration clause|intellectual property assignment|settlement agreement|"
    r"board resolution|shareholder agreement|letter of intent|due diligence|liability waiver|"
    r"attorney-client privilege|legally binding)\b|"
    r"(σύμβαση|συμφωνητικό|ρήτρα|εχεμύθειας|πνευματικά δικαιώματα|νομικό τμήμα|διοικητικό συμβούλιο))",
    re.IGNORECASE,
)

# 3. HR, Payroll, Layoffs, Customer/Medical Dumps (English + Greek)
HR_CUSTOMER_PATTERNS = re.compile(
    r"(\b(payroll|base salary|bonus structure|compensation package|stock options|"
    r"layoff list|termination letter|severance package|performance improvement plan|"
    r"employee ssn|background check|patient record|medical diagnosis|hipaa|gdpr dump|"
    r"customer database|client list|crm export|lead list)\b|"
    r"(μισθοδοσία|μισθός|απόλυση|αποζημίωση|πελατολόγιο|ιατρικός φάκελος|προσωπικά δεδομένα))",
    re.IGNORECASE,
)

# 4. Credentials, DB Connection Strings, Private Keys, IBANs, Credit Cards
CREDENTIAL_PATTERNS = re.compile(
    r"((postgres|postgresql|mysql|mongodb|redis)://[^\s]+|"
    r"-----BEGIN\s+(RSA|OPENSSH|DSA|EC|PRIVATE)\s+KEY-----|"
    r"\b(password|passwd|pwd|secret_key|client_secret|access_token|auth_token)\s*[:=]\s*['\"]?[^\s'\"]{4,}|"
    r"\bGR\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{3}\b|"
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b|"
    r"\b(?:\d{4}[-\s]?){3}\d{4}\b)",
    re.IGNORECASE,
)

# 5. Fast Source Code Syntax check
CODE_SYNTAX = re.compile(
    r"^\s*(def\s+\w+|class\s+\w+|import\s+\w+|from\s+\w+\s+import|return\s+|"
    r"if\s+.*:|elif\s+.*:|else:|for\s+.*:|while\s+.*:|try:|except\b|"
    r"(const|let|var|function)\s+\w+|#include\s*<|public\s+static\s+void|"
    r"\w+\s*=\s*[\[\{\(]|print\(.*\)|console\.log\()"
)

try:
    from model_cache import classify
except ImportError:  # pragma: no cover - standalone use from another cwd
    from .model_cache import classify


def get_classifier():
    """Kept for callers that want the pipeline itself."""
    from model_cache import get_zero_shot

    return get_zero_shot()


def analyze(raw_text):
    if not raw_text.strip():
        return {"blocked": False, "score": 0.0, "main_cause": None, "matches": []}

    matches = []
    unknown_chunks = []
    offset = 0

    for line_num, line in enumerate(raw_text.splitlines(keepends=True), start=1):
        stripped = line.strip()
        if len(stripped) > 3:
            start_char = offset + line.find(stripped)
            end_char = start_char + len(stripped)
            chunk = {
                "line": line_num,
                "start_offset": start_char,
                "end_offset": end_char,
                "text": stripped,
            }

            if CREDENTIAL_PATTERNS.search(stripped):
                matches.append({**chunk, "cause": "credentials or banking data", "score": 0.96, "snippet": stripped})
            elif LEGAL_PATTERNS.search(stripped):
                matches.append({**chunk, "cause": "legal contract or NDA", "score": 0.92, "snippet": stripped})
            elif FINANCE_PATTERNS.search(stripped):
                matches.append({**chunk, "cause": "internal company financial data", "score": 0.92, "snippet": stripped})
            elif HR_CUSTOMER_PATTERNS.search(stripped):
                matches.append({**chunk, "cause": "confidential HR, payroll, or customer records", "score": 0.92, "snippet": stripped})
            elif CODE_SYNTAX.search(stripped):
                matches.append({**chunk, "cause": CODE_LABEL, "score": 0.90, "snippet": stripped})
            else:
                unknown_chunks.append(chunk)

        offset += len(line)

    for m in matches:
        m.pop("text", None)

    # Only load & run the heavy neural network on lines not already caught above
    default_score = 0.0
    if unknown_chunks:
        results = classify(
            [c["text"] for c in unknown_chunks],
            LABELS,
            hypothesis_template="This text is {}.",
        )
        if isinstance(results, dict):
            results = [results]
        default_score = round(float(results[0]["scores"][0]), 4)

        for chunk, res in zip(unknown_chunks, results):
            top_label = res["labels"][0]
            top_score = round(float(res["scores"][0]), 4)
            if top_label != SAFE_LABEL and top_score >= THRESHOLD:
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
    }

    if matches:
        blocking_matches = [m for m in matches if m["cause"] in BLOCKED_LABELS]
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

    if response["main_cause"] in BLOCKED_LABELS:
        response["blocked"] = True

    return response


def analyze_stdin():
    """CLI entry point: read the prompt from stdin and return the verdict."""
    return analyze(sys.stdin.read())


if __name__ == "__main__":
    print(json.dumps(analyze_stdin(), indent=2, ensure_ascii=False))
