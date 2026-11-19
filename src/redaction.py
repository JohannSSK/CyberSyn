"""Request-local, offset-based redaction. Only safe metadata may leave this module."""

import re
from collections import Counter
from dataclasses import dataclass, field

TAGS = frozenset(("GREEK_AFM", "GREEK_AMKA", "GREEK_ID", "PASSPORT", "IBAN", "EMAIL", "GREEK_PHONE",
                  "INTL_PHONE", "CARD", "API_KEY", "IPV4", "PERSON", "COMPANY", "CONFIDENTIAL", "CODE"))
TAG_ALIASES = {"GREEK_ID_CARD": "GREEK_ID", "ID_CARD": "GREEK_ID", "GREEK_IBAN": "IBAN",
               "computer source code": "CODE", "credentials or banking data": "API_KEY"}
# Prefer a specific identifier to a whole confidential sentence or code line
# when they overlap; ties keep the first verdict in configured scanner order.
SEVERITY = {"API_KEY": 4, "CARD": 4, "IBAN": 4, "GREEK_AFM": 4, "GREEK_AMKA": 4,
            "GREEK_ID": 4, "PASSPORT": 4, "EMAIL": 3, "GREEK_PHONE": 3, "INTL_PHONE": 3,
            "IPV4": 3, "PERSON": 3, "COMPANY": 3, "CONFIDENTIAL": 2, "CODE": 1}
TOKEN = re.compile(r"\[[A-Z_]+_[0-9]+\]")


class RedactionError(ValueError):
    pass


def offsets(prompt, match):
    start, end = match.get("start_offset"), match.get("end_offset")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(prompt):
        raise RedactionError("The scanner returned invalid redaction offsets.")
    return start, end


def _tag(match):
    tag = match.get("redaction_tag") or match.get("cause")
    if not isinstance(tag, str):
        raise RedactionError("The scanner returned an invalid redaction category.")
    return tag if tag in TAGS else TAG_ALIASES.get(tag, "CONFIDENTIAL")


def _substitute(text, values):
    if not values:
        return text
    # Escape literals; longest first in case one value prefixes another.
    pattern = re.compile("|".join(re.escape(key) for key in sorted(values, key=lambda s: (-len(s), s))))
    return pattern.sub(lambda found: values[found[0]], text)


def restore(reply_text, mapping):
    """One pass over the original reply. Inserted text is never rescanned."""
    return _substitute(reply_text, mapping)


@dataclass
class Redaction:
    prompt: str
    info: dict
    mapping: dict = field(repr=False)  # token -> original union of overlapping spans
    private_values: dict = field(repr=False)  # original spans -> token (reply storage guard)

    def un_restored_reply(self, reply):
        """Usually unchanged. Also mask any coincident literal echo in the model reply."""
        return _substitute(reply, self.private_values)


def _merge(spans):
    merged = []
    for start, end, rank, tag in sorted(spans):
        if not merged or start >= merged[-1][1]:
            merged.append((start, end, rank, tag))
        else:
            previous, stop, highest, label = merged[-1]
            merged[-1] = (previous, max(stop, end), max(highest, rank), tag if rank > highest else label)
    return merged


def redact(prompt, matches):
    spans, values, categories = set(), {}, set()

    def add(start, end, rank, tag):
        spans.add((start, end, rank, tag))
        if len(spans) > 4 * len(prompt):
            raise RedactionError("Too many overlapping redactions to send this message safely.")

    def remember(start, end, rank, tag):
        raw = prompt[start:end]
        if raw not in values or rank > values[raw][0]:
            values[raw] = (rank, tag)

    for index, match in enumerate(matches):
        start, end = offsets(prompt, match)
        tag = _tag(match)
        rank = (SEVERITY[tag], -index)
        categories.add(tag)
        add(start, end, rank, tag)
        remember(start, end, rank, tag)
    for start, end, rank, tag in _merge(spans):
        remember(start, end, rank, tag)

    # A detector can require context (e.g. a label beside an AFM). Once a
    # value is recognized, mask its other exact occurrences too, not just
    # the first labeled one. Include overlapping occurrences, then merge.
    for raw, (rank, tag) in values.items():
        start = prompt.find(raw)
        while start != -1:
            add(start, start + len(raw), rank, tag)
            start = prompt.find(raw, start + 1)

    used, serials, tokens = set(TOKEN.findall(prompt)), Counter(), {}
    mapping, parts, end_of_last = {}, [], 0
    for start, end, _, tag in _merge(spans):
        raw = prompt[start:end]
        token = tokens.get((tag, raw))
        if token is None:
            while True:
                serials[tag] += 1
                token = f"[{tag}_{serials[tag]}]"
                if token not in used:
                    break
            used.add(token)
            tokens[tag, raw] = token
            mapping[token] = raw
        parts.extend((prompt[end_of_last:start], token))
        end_of_last = end
    parts.append(prompt[end_of_last:])
    safe = "".join(parts)
    if any(raw in safe for raw in values.keys() | set(mapping.values())):
        # A literal may even collide with the spelling of a generated token.
        # Refuse rather than sending a known value through that ambiguity.
        raise RedactionError("A redacted value could not be removed safely.")
    # For a coincident echo, keep the same placeholder where possible; when
    # there was a larger overlapping span, protect the smaller original too.
    private_values = {raw: token for token, raw in mapping.items()}
    for raw in values.keys() - private_values.keys():
        private_values[raw] = next(token for token, value in mapping.items() if raw in value)
    info = {"count": (len(parts) - 1) // 2, "categories": sorted(categories),
            "placeholders": list(mapping), "restored": False}
    return Redaction(safe, info, mapping, private_values)


def retained_redactions(text, entry):
    """Retain a saved receipt only for tokens still present in this exchange."""
    previous = entry.get("redaction_info") or {}
    found = Counter(TOKEN.findall(text))
    tokens = [token for token in previous.get("placeholders", []) if found[token]]
    if not tokens:
        return None
    categories = previous["categories"] if tokens == previous["placeholders"] else sorted({
        token[1:-1].rsplit("_", 1)[0] for token in tokens
    })
    return {"count": sum(found[token] for token in tokens), "categories": categories,
            "placeholders": tokens, "restored": False}
