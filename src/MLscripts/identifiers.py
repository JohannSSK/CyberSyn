"""Shared deterministic recognizers for the PII and confidential-context checks."""

import re
from datetime import date

API_KEY = (
    r"(?<![\w-])(?:sk-(?:proj-|svcacct-|admin-|ant-|or-v1-)?[A-Za-z0-9_-]{16,}|"
    r"AIza(?:Sy[0-9A-Za-z_-]{16,}|[0-9A-Za-z_-]{30,})|(?:AKIA|ASIA)[0-9A-Z]{16}|"
    r"(?:gh[pousr]|gsk|hf)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{16,}|xai-[A-Za-z0-9_-]{20,}|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})(?!\w)"
)
# The same credential rules apply in a config file, a code comment or prose.
# Keep raw Match objects so both scanners can report original offsets.
_CREDENTIAL = re.compile(
    API_KEY + r"|(?i:(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s'\"<>]+|"
    r"-----BEGIN (?:(?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----|"
    r"\bBearer\s+(?P<bearer>[A-Za-z0-9._~+/=-]{12,})|"
    r"\b(?:password|passwd|pwd|api[_-]?key|secret(?:[_-]?key)?|client[_-]?secret|access[_-]?token|"
    r"auth[_-]?token|refresh[_-]?token|private[_-]?key|aws_secret_access_key|db_pass(?:word)?|token)"
    r"['\"]?\s*[:=]\s*['\"]?(?P<assigned>[^\s'\",;]{6,}))"
)
_PLACEHOLDER = re.compile(
    r"YOUR[_-][\w-]+|<[^>]+>|changeme|example|None|null|true|false|"
    r"os\.(?:environ|getenv).*|process\.env.*|\$\{[\w.]+\}", re.I
)


def credential_matches(text):
    for match in _CREDENTIAL.finditer(text):
        value = match["assigned"] or match["bearer"]
        if not value or not _PLACEHOLDER.fullmatch(value):
            yield match


_LATIN, _GREEK = "ABEZHIKMNOPTYX", "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ"
GREEK_ID = rf"\b(?:(?:[{_LATIN}]{{1,2}}|[{_GREEK}]{{1,2}})[ -]?\d{{6}}|(?:[{_LATIN}]{{2}}|[{_GREEK}]{{2}})[ -]?\d{{7}})\b"
_ID_CONTEXT = re.compile(r"\b(?:α\.?δ\.?τ|ταυτότητ\w*|ταυτοτητ\w*|δελτίο|id|identity|passport|διαβατήριο|κάτοχος|αριθμός)\b", re.I)


def id_score(text, match):
    window = text[max(0, match.start() - 80):match.end() + 80]
    return 0.95 if match[0][0] in _GREEK or _ID_CONTEXT.search(window) else 0.55


def valid_amka(raw):
    try:
        date(2000 + int(raw[4:6]), int(raw[2:4]), int(raw[:2]))
    except ValueError:
        return False
    return len(raw) == 11 and raw[6:] != "00000"


# Registered IBAN formats. Using their exact length also prevents trailing
# words or a following identifier being swallowed into a spaced IBAN.
_FORMATS = """AD24 AE23 AL28 AT20 AZ28 BA20 BE16 BG22 BH22 BI27 BR29 BY28 CH21 CR22 CY28 CZ24 DE22
DJ27 DK18 DO28 EE20 EG29 ES24 FI18 FK18 FO18 FR27 GB22 GE22 GI23 GL18 GR27 GT28 HR21 HU28 IE22 IL23
IQ23 IS26 IT27 JO30 KW30 KZ20 LB28 LC32 LI21 LT20 LU20 LV21 LY25 MC27 MD24 ME22 MK19 MN20 MR27 MT31
MU30 NI28 NL18 NO15 OM23 PK24 PL28 PS29 PT25 QA29 RO24 RS22 RU33 SA24 SC31 SD18 SE24 SI19 SK24 SM27
SO23 ST25 SV28 TL23 TN24 TR26 UA29 VA22 VG24 XK20 YE30"""
_LENGTHS = {f[:2]: int(f[2:]) for f in _FORMATS.split()}
IBAN = r"\b(?:" + "|".join(
    rf"(?:{'|'.join(c for c, size in _LENGTHS.items() if size == n)})[0-9]{{2}}(?:[ -]?[A-Z0-9]){{{n-4}}}"
    for n in sorted(set(_LENGTHS.values()))
) + r")\b"


def is_valid_iban(raw):
    value = raw.replace(" ", "").replace("-", "")
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[0-9A-Z]{11,30}", value) or _LENGTHS.get(value[:2]) != len(value):
        return False
    rotated = value[4:] + value[:4]
    return int("".join(str(ord(c)-55) if c.isalpha() else c for c in rotated)) % 97 == 1


def iban_score(text, match):
    if is_valid_iban(match[0]):
        return 0.98
    if (re.search(r"\bIBAN\s*[:=]?\s*$", text[:match.start()], re.I) and
            re.fullmatch(r"GR(?:[ -]?[0-9]){25}", match[0])):
        return 0.90
    return 0


CARD = re.compile(r"(?<!\w)(?<!\d[ -])\d(?:[ -]?\d){12,18}\b(?![ -]?\d)")


def is_valid_luhn(raw):
    digits = raw.replace(" ", "").replace("-", "")
    if not re.fullmatch(r"[0-9]{13,19}", digits) or len(set(digits)) == 1:
        return False
    total = 0
    for i, char in enumerate(reversed(digits)):
        n = int(char) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0
