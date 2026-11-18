"""Natural-language spans embedded in code, with offsets into the original paste."""

import re

_EMBEDDED = re.compile(
    r'''(?P<block>/\*[\s\S]*?(?:\*/|\Z)|<!--[\s\S]*?(?:-->|\Z))'''
    r'''|(?P<doc>"""[\s\S]*?(?:"""|\Z)|\'{3}[\s\S]*?(?:\'{3}|\Z))'''
    r'''|(?P<string>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')'''
    r'''|(?P<comment>(?:\#|//|--)[^\n]*(?:\n[ \t]*(?:\#|//|--)[^\n]*)*)'''
)
_MARKERS = re.compile(r"(?m)^[ \t]*(?:\#|//|--|\*(?!/))|^/\*|\*/$|^<!--|-->$")


def chunk(text, start, end, clean=None):
    raw = text[start:end]
    return {"line": text.count("\n", 0, start) + 1, "start_offset": start, "end_offset": end,
            "text": raw, "clean": raw if clean is None else clean}


def embedded(text):
    for match in _EMBEDDED.finditer(text):
        value = match[0]
        if match.lastgroup == "string" and len(value) < 27:
            continue
        # Replace delimiters with equal-length spaces. Regex positions in
        # clean still point to the exact original characters in a block.
        clean = _MARKERS.sub(lambda m: " " * len(m[0]), value) if match.lastgroup in ("block", "comment") else value
        yield chunk(text, match.start(), match.end(), clean)


def lines(text):
    for match in re.finditer(r"(?m)^[^\S\n]*(\S[^\n]*?)\s*(?=\n|$)", text):
        yield chunk(text, match.start(1), match.end(1))
