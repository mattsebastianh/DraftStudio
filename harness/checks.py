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
_UNIT_SPAN_RE = re.compile(r"(\d+(?:[,.]\d+)*k?)\s*(?:(?:-|–|—|to)\s*(\d+(?:[,.]\d+)*k?)\s*)?(words?|characters?|chars?)\b", re.IGNORECASE)
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


def _parse_number(num_str):
    """Parse a number string, handling commas and 'k' suffix (e.g. '1.5k' -> 1500)."""
    num_str = num_str.replace(",", "").lower()
    value = float(num_str.rstrip("k"))
    if num_str.endswith("k"):
        value *= 1000
    return int(value)


def _length_target(length):
    """(unit, low, high) with the tolerance applied; high is None for "at least N".

    None when the brief gives no word or character count ("1-2 pages", "short").
    Binds numbers directly to unit words (words/characters/chars).
    """
    if isinstance(length, bool) or not isinstance(length, (int, str)):
        return None

    # Handle integer lengths: must be > 0, treated as words.
    if isinstance(length, int):
        if length <= 0:
            return None
        return "words", int(length * (1 - config.LENGTH_TOLERANCE)), math.ceil(length * (1 + config.LENGTH_TOLERANCE))

    # Find a unit-bound number: (number) [number] (unit).
    text = str(length)
    match = _UNIT_SPAN_RE.search(text)
    if not match:
        return None

    # Determine unit (characters or words).
    unit_str = match.group(3).lower()
    unit = "characters" if unit_str[0] == "c" else "words"

    # Parse numbers: handle 'k' suffix and commas. Return None if parsing fails.
    try:
        num1 = _parse_number(match.group(1))
    except ValueError:
        return None
    num2 = match.group(2)

    if num2:
        # Range: two numbers.
        try:
            num2 = _parse_number(num2)
        except ValueError:
            return None
        low, high = sorted([num1, num2])
    else:
        # Single number: apply at-most/at-least to text before and up to 12 chars after the match.
        text_before = text[:match.start()]
        text_after = text[match.end():match.end() + 12]
        search_text = text_before + " " + text_after
        if _AT_MOST_RE.search(search_text):
            low, high = 0, num1
        elif _AT_LEAST_RE.search(search_text):
            low, high = num1, None
        else:
            # Exact target.
            low = high = num1

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
        # Guard: skip non-dict entries; treat None url/title as empty.
        if not isinstance(src, dict):
            continue
        url = (src.get("url") or "") if src.get("url") is not None else ""
        host = (urlparse(url).hostname or "").lower().removeprefix("www.") if url else ""
        title = (src.get("title") or "") if src.get("title") is not None else ""
        if (url and url.lower() in lowered) or (host and host in lowered) or (title and title.lower() in lowered):
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


def _is_critical(issue):
    """A non-dict issue counts as critical so malformed reviews fail closed."""
    if not isinstance(issue, dict):
        return True
    return str(issue.get("severity", "")).strip().lower() == "critical"


def finalize_review(llm_review, results, threshold):
    """Merge deterministic results into the LLM review and compute the verdict in code.

    Never raises on a malformed review: an invalid score or issue list fails closed.
    """
    llm_issues = llm_review.get("issues")
    issues = list(llm_issues) if isinstance(llm_issues, list) else []
    issues += [r.as_issue() for r in results if not r.passed]
    score = llm_review.get("score")
    score_valid = isinstance(score, (int, float)) and not isinstance(score, bool) and not math.isnan(score)
    if not score_valid:
        score = 0
        issues.append(
            {
                "severity": "critical",
                "category": "malformed_review",
                "description": "ReviewAgent returned a missing or non-numeric score.",
                "suggested_fix": "Re-run the review and return a numeric 0-100 score.",
            }
        )
    status = "approved" if score >= threshold and not any(_is_critical(i) for i in issues) else "revision_required"
    llm_status = llm_review.get("status")
    return {
        **llm_review,
        "score": score,
        "issues": issues,
        "status": status,
        "checks": [r.as_dict() for r in results],
        "llm_status": llm_status,
        "status_disagreed": llm_status is not None and llm_status != status,
    }
