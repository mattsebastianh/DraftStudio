"""Deterministic review checks: cheap, explainable rules run in code before the LLM rubric."""

import math
import re
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from harness import config

# TODO/TBD/XXX only in capitals ("my todo list" is prose); bracket placeholders but not markdown links.
PLACEHOLDER_RE = re.compile(
    r"(?-i:\bTODO\b|\bTBD\b|\bXXX\b)|lorem ipsum|\[\s*(?:insert|your|link|url|company name|name|date)\b[^\]]*\](?!\()",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(r"(\d[\d,]*)\s*(?:-|–|—|to)\s*(\d[\d,]*)")
_NUMBER_RE = re.compile(r"\d[\d,]*")
_CHARACTERS_RE = re.compile(r"\b(?:characters?|chars?)\b", re.IGNORECASE)
_WORDS_RE = re.compile(r"\bwords?\b", re.IGNORECASE)
_AT_MOST_RE = re.compile(r"≤|<=|\bmax(?:imum)?\b|\bup to\b|\bno more than\b|\bat most\b|\bunder\b", re.IGNORECASE)
_AT_LEAST_RE = re.compile(r"≥|>=|\bmin(?:imum)?\b|\bat least\b|\bno (?:less|fewer) than\b", re.IGNORECASE)


@dataclass
class CheckResult:
    id: str
    passed: bool
    severity: str
    detail: str
    suggested_fix: str = ""

    def as_dict(self):
        return asdict(self)

    def as_issue(self):
        return {
            "severity": self.severity,
            "category": f"deterministic:{self.id}",
            "description": self.detail,
            "suggested_fix": self.suggested_fix,
        }


def _passed(check_id, detail="ok"):
    return CheckResult(check_id, True, "low", detail)


def _length_target(length):
    """(unit, low, high) with the tolerance applied; high is None for "at least N".

    None when the brief gives no word or character count ("1-2 pages", "short").
    """
    if isinstance(length, bool) or not isinstance(length, (int, str)):
        return None
    if isinstance(length, int):
        unit, text = "words", str(length)
    elif _CHARACTERS_RE.search(length):
        unit, text = "characters", length
    elif _WORDS_RE.search(length):
        unit, text = "words", length
    else:
        return None
    span = _RANGE_RE.search(text)
    if span:
        low, high = sorted(int(n.replace(",", "")) for n in span.groups())
    else:
        number = _NUMBER_RE.search(text)
        if not number:
            return None
        value = int(number.group(0).replace(",", ""))
        if _AT_MOST_RE.search(text):
            low, high = 0, value
        elif _AT_LEAST_RE.search(text):
            low, high = value, None
        else:
            low = high = value
    tol = config.LENGTH_TOLERANCE
    return unit, int(low * (1 - tol)), None if high is None else math.ceil(high * (1 + tol))


def check_length(brief, content):
    target = _length_target(brief.get("length"))
    if target is None:
        return _passed("length", "no word or character count requested")
    unit, low, high = target
    size = len(content.split()) if unit == "words" else len(content.strip())
    allowed = f"at least {low}" if high is None else (f"at most {high}" if low == 0 else f"{low}-{high}")
    if size >= low and (high is None or size <= high):
        return _passed("length", f"{size} {unit}, allowed {allowed}")
    return CheckResult(
        "length",
        False,
        "medium",
        f"Draft is {size} {unit}; the brief allows {allowed} {unit}.",
        f"Rewrite to {allowed} {unit}.",
    )


def _stems(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w[:5] for w in words if len(w) > 3 or w.isdigit()]


def check_key_points(brief, content):
    points = brief.get("key_points") or []
    if not points:
        return _passed("key_points_covered", "no key points in brief")
    haystack = set(_stems(content))
    missing = []
    for point in points:
        stems = _stems(str(point))
        if stems and sum(s in haystack for s in stems) / len(stems) < 0.5:
            missing.append(str(point))
    if not missing:
        return _passed("key_points_covered")
    return CheckResult(
        "key_points_covered",
        False,
        "medium",
        "Key points not covered: " + "; ".join(missing),
        "Add a passage addressing each missing key point.",
    )


def check_placeholders(content):
    match = PLACEHOLDER_RE.search(content)
    if not match:
        return _passed("no_placeholders")
    return CheckResult(
        "no_placeholders",
        False,
        "critical",
        f"Draft contains placeholder text: '{match.group(0)}'.",
        "Replace every placeholder with real content.",
    )


def check_citations(content, dossier):
    sources = (dossier or {}).get("sources") or []
    if not sources:
        return _passed("citations_present", "no research sources to cite")
    lowered = content.lower()
    for src in sources:
        url = src.get("url", "")
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        title = (src.get("title") or "").lower()
        if (url and url.lower() in lowered) or (host and host in lowered) or (title and title in lowered):
            return _passed("citations_present")
    return CheckResult(
        "citations_present",
        False,
        "medium",
        "Research was used but the draft cites none of its sources.",
        "Cite at least one source (title or URL) for the claims taken from research.",
    )


def check_format(brief, content):
    fmt = str(brief.get("format") or "").lower()
    if "markdown" not in fmt:
        return _passed("format", "markdown structure not required")
    if re.search(r"^#{1,6}\s+\S", content, re.MULTILINE):
        return _passed("format")
    return CheckResult("format", False, "low", "Markdown was requested but the draft has no headings.", "Add markdown headings.")


def run_checks(brief, content, dossier):
    return [
        check_length(brief, content),
        check_key_points(brief, content),
        check_placeholders(content),
        check_citations(content, dossier),
        check_format(brief, content),
    ]
