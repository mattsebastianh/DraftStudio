"""Last-resort JSON extraction for model replies that ignore structured-output mode."""

import json
import re

_CONTROL_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}


def _escape_raw_control_chars_in_strings(text):
    """Escape raw newlines/tabs/control chars that appear inside JSON string literals."""
    out = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            elif ch in _CONTROL_ESCAPES:
                out.append(_CONTROL_ESCAPES[ch])
                continue
            elif ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
                continue
        elif ch == '"':
            in_string = True
        out.append(ch)
    return "".join(out)


def _object_at(text, start):
    """The balanced {...} slice starting at `start` (braces inside strings do not count), or None."""
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json(text):
    """Pull the first JSON object out of a model reply (tolerates fences/prose, even prose with braces)."""
    text = text.strip()  # fences around the object are skipped by the scan; fences inside strings are content
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in model reply")
    error = None
    while start != -1:
        candidate = _object_at(text, start)
        if candidate is not None:
            try:
                return json.loads(_escape_raw_control_chars_in_strings(candidate))
            except ValueError as err:  # prose like "{draft}": try the next opening brace
                error = err
        start = text.find("{", start + 1)
    if error is not None:
        raise error
    raise ValueError("unbalanced JSON in model reply")
