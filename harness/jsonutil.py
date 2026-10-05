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


def extract_json(text):
    """Pull the first JSON object out of a model reply (tolerates fences/prose)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in model reply")
    depth, in_string, escaped = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_string:  # braces inside a JSON string do not count
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
                return json.loads(_escape_raw_control_chars_in_strings(text[start : i + 1]))
    raise ValueError("unbalanced JSON in model reply")
