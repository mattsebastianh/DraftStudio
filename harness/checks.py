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
# "500 words", "500-word post", "300-400 words", "1000+ words" (the plus is read as a floor)
_UNIT_SPAN_RE = re.compile(r"(\d+(?:[,.]\d+)*k?)\s*\+?\s*(?:(?:-|–|—|to)\s*(\d+(?:[,.]\d+)*k?)\s*)?[\s-]*(words?|characters?|chars?)\b", re.IGNORECASE)
_NUMBER = r"\d+(?:[,.]\d+)*k?"
_BETWEEN_RE = re.compile(rf"\bbetween\s+({_NUMBER})\s+and\s+({_NUMBER})\s*(words?|characters?|chars?)\b", re.IGNORECASE)
# Hints that bind anywhere in the count's sentence before it ("Max 2 paragraphs, 150 words"), or right after it.
_AT_MOST_RE = re.compile(
    r"≤|<=|<(?!=)|\bmax(?:imum)?\b|\bup to\b|\bno (?:more|longer) than\b|\bnot (?:more than|to exceed|exceed(?:ing)?|over|above)\b|(?:\b(?:never|do not|must not|cannot|can not)|n't|can’t) exceed\b|(?:\bnot|\bcannot|n't|’t) be (?:more than|over|above|greater than|longer than)\b|(?:\bnot(?: to)?|n't|’t) go (?:over|above|beyond)\b|\bwithout exceeding\b|\bnot longer than\b|\bat most\b|\bunder\b",
    re.IGNORECASE,
)
_AT_LEAST_RE = re.compile(r"≥|>=|>(?!=)|\bmin(?:imum)?\b|\bat least\b|\b(?:no|not) (?:less|fewer) than\b", re.IGNORECASE)
# Weaker words only count when they sit directly before the count ("less than 200 words") or after it ("or fewer").
_AT_MOST_BEFORE_RE = re.compile(r"(?<!no )(?<!not )\b(?:less than|fewer than|below|within)\s*(?:about\s+|around\s+|~\s*)?$", re.IGNORECASE)
_AT_LEAST_BEFORE_RE = re.compile(r"(?<!not )(?<!never )(?<!n't )(?<!no )\b(?:more than|over|above|exceeds?)\s*(?:about\s+|around\s+|~\s*)?$", re.IGNORECASE)
_AT_MOST_AFTER_RE = re.compile(r"^\s*or\s+(?:less|fewer)\b", re.IGNORECASE)
_AT_LEAST_AFTER_RE = re.compile(r"^\s*or\s+more\b", re.IGNORECASE)
# A count that applies to each part ("~150 words each", "per section", "2 paragraphs of 150 words") is no total.
_PER_ITEM_AFTER_RE = re.compile(r"^[\s)\],.;:]*(?:each|apiece|per\b|/)", re.IGNORECASE)
_PER_ITEM_BEFORE_RE = re.compile(
    r"(?:\b(?:each|every)\b[^,;.]{0,20}|\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+[a-z]+s\s+(?:of|at)\s+(?:[a-z~]+\s+){0,2})$",
    re.IGNORECASE,
)
# After the count: "500 words max", "1000 words (max 1200)"; "max 3 sections" belongs to another count.
_AFTER_CEILING_RE = re.compile(r"^[\s(,–-]*(?:max(?:imum)?|at most|tops|up to|no more than)\b(?!\s*\d)", re.IGNORECASE)
_AFTER_FLOOR_RE = re.compile(r"^[\s(,–-]*(?:min(?:imum)?|at least)\b(?!\s*\d)", re.IGNORECASE)
_UNITLESS_END = r"\s*(?:words?|characters?|chars?)?\s*(?:[).,;]|$)"
_AFTER_CEILING_NUM_RE = re.compile(
    rf"(?:^|[,;(])\s*(?:but\s+|and\s+)?(?:(?:max(?:imum)?|at most|up to|no more than)\s*(?:of\s*)?({_NUMBER}){_UNITLESS_END}|({_NUMBER})\s*max(?:imum)?\b)",
    re.IGNORECASE,
)
_AFTER_FLOOR_NUM_RE = re.compile(
    rf"(?:^|[,;(])\s*(?:but\s+|and\s+)?(?:(?:min(?:imum)?|at least)\s*(?:of\s*)?({_NUMBER}){_UNITLESS_END}|({_NUMBER})\s*min(?:imum)?\b)",
    re.IGNORECASE,
)
_NOUN_LIMIT_RE = re.compile(
    r"\b(?:max(?:imum)?|min(?:imum)?|at most|at least|up to|no more than|under|over)\s*\d[\d,.]*\s+(?!words?\b|characters?\b|chars?\b)[a-z]+\b",
    re.IGNORECASE,
)
_CLAUSE_END_RE = re.compile(r"[,;]\s*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n")
MAX_PLAUSIBLE_COUNT = 10**12


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
    num_str = num_str.lower()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", num_str):  # "1.000" / "2.500": the European thousands separator
        num_str = num_str.replace(".", "")
    num_str = num_str.replace(",", "")
    value = float(num_str.rstrip("k"))
    if num_str.endswith("k"):
        value *= 1000
    if value > MAX_PLAUSIBLE_COUNT:
        raise ValueError("count too large to be a length")
    return int(value)  # OverflowError for inf


def _after_limits(text_after):
    """(floor, ceiling) numbers stated after a count without a unit; None where absent."""
    found = []
    for pattern in (_AFTER_FLOOR_NUM_RE, _AFTER_CEILING_NUM_RE):
        match = pattern.search(text_after)
        try:
            found.append(_parse_number(match.group(1) or match.group(2)) if match else None)
        except (ValueError, OverflowError):
            found.append(None)
    return tuple(found)


def _length_target(length):
    """(unit, low, high) with the tolerance applied; high is None for "at least N".

    An explicit ceiling ("at most N", "less than N", "N or fewer") gets no tolerance above it. Counts that
    apply per part ("150 words each", "2 paragraphs of 150 words") give no total and are skipped.

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

    # Find unit-bound counts: "between X and Y <unit>", or (number) [number] (unit).
    text = re.sub(r"\b(max|min)\.", r"\1", str(length), flags=re.IGNORECASE)
    between = _BETWEEN_RE.search(text)
    matches = [between] if between else list(_UNIT_SPAN_RE.finditer(text))
    if not matches:
        return None
    unit = "characters" if matches[0].group(3)[0].lower() == "c" else "words"
    tol = config.LENGTH_TOLERANCE
    low, high, found, plain = 0, None, False, 0
    for index, match in enumerate(matches):
        if ("characters" if match.group(3)[0].lower() == "c" else "words") != unit:
            continue
        # Each count reads only the text between its neighbouring counts, cut to its own sentence.
        before_start = matches[index - 1].end() if index else 0
        after_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        between = text[before_start : match.start()]
        if index:  # the previous count's trailing hint ("500 words max,") is not this count's
            between = _CLAUSE_END_RE.split(between, maxsplit=1)[-1]
        text_before = _NOUN_LIMIT_RE.sub("", _SENTENCE_SPLIT_RE.split(between)[-1])  # "max 3 sections" is not about words
        text_after = _SENTENCE_SPLIT_RE.split(text[match.end() : after_end])[0]
        hint_after = _SENTENCE_SPLIT_RE.split(text[match.end() :])[0]  # sees the digit of a following "at most 500"
        if _PER_ITEM_AFTER_RE.search(text_after[:16]) or _PER_ITEM_BEFORE_RE.search(text_before):
            continue
        try:
            num1 = _parse_number(match.group(1))
            num2 = _parse_number(match.group(2)) if match.group(2) else None
        except (ValueError, OverflowError):
            continue
        if num2 is not None:
            lo, hi = sorted([num1, num2])
            lo, hi = int(lo * (1 - tol)), math.ceil(hi * (1 + tol))
        elif _AT_MOST_RE.search(text_before) or _AT_MOST_BEFORE_RE.search(text_before) or _AFTER_CEILING_RE.search(hint_after) or _AT_MOST_AFTER_RE.search(text_after):
            lo, hi = 0, num1  # an explicit ceiling gets no tolerance above it
        elif "+" in match.group(0) or _AT_LEAST_RE.search(text_before) or _AT_LEAST_BEFORE_RE.search(text_before) or _AFTER_FLOOR_RE.search(hint_after) or _AT_LEAST_AFTER_RE.search(text_after):
            lo, hi = int(num1 * (1 - tol)), None
        else:
            lo, hi = int(num1 * (1 - tol)), math.ceil(num1 * (1 + tol))  # exact target
            plain += 1
        # A limit stated after the count without a unit: "1000 words (max 1200)", "1000 words max, 800 min".
        floor, ceiling = _after_limits(text_after)
        if ceiling is not None:
            hi = ceiling
            if lo > hi:
                lo = int(hi * (1 - tol))
        if floor is not None and (hi is None or int(floor * (1 - tol)) <= hi):
            lo = max(lo, int(floor * (1 - tol)))
        new_low = max(low, lo)
        new_high = hi if high is None else (high if hi is None else min(high, hi))
        if new_high is not None and new_low > new_high:
            continue  # contradicts an earlier count: the earlier one stands
        found, low, high = True, new_low, new_high
    if not found or plain > 1:  # several unqualified counts ("intro 100 words, body 400 words") are no total
        return None
    return unit, low, high


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
        "critical",  # a stated length is a hard constraint, so it blocks approval
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
        if stems:
            covered = sum(s in haystack for s in stems) / len(stems) >= 0.5
        else:  # only short words ("AI", "ROI", "SEO"): the phrase itself must appear
            phrase = str(point).strip()
            covered = not phrase or re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", content, re.IGNORECASE) is not None
        if not covered:
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


_SECOND_LEVEL_LABELS = {"co", "com", "org", "gov", "ac"}


def _host_label(host):
    """Registrable-domain label of a host: finance.yahoo.com -> yahoo, bbc.co.uk -> bbc."""
    parts = [p for p in host.removeprefix("www.").split(".") if p]
    if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL_LABELS:
        parts = parts[:-2]
    elif len(parts) > 1:
        parts = parts[:-1]
    return parts[-1] if parts else ""


def _normalized(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _label_cited(label, content):
    """Whether the domain label appears as a name: starting and ending on word edges, spanning words
    ("GM Insights" -> gminsights), and a lone word only as a capitalized name ("Yahoo", not "the latest news")."""
    tokens = [(m.start(), m.group()) for m in re.finditer(r"[A-Za-z0-9]+", content)]
    starts, ends, pos = {}, {}, 0
    for index, (_, word) in enumerate(tokens):
        starts[pos] = index
        pos += len(word)
        ends[pos] = index
    squashed = "".join(word for _, word in tokens).lower()
    at = squashed.find(label)
    while at != -1:
        first, last = starts.get(at), ends.get(at + len(label))
        if first is not None and last is not None and (first != last or tokens[first][1][0].isupper()):
            return True
        at = squashed.find(label, at + 1)
    return False


def check_citations(content, dossier):
    sources = (dossier or {}).get("sources") or []
    if not sources:
        return _passed("citations_present", "no research sources to cite")
    lowered = content.lower()
    for src in sources:
        if not isinstance(src, dict):
            continue
        url = src.get("url") or ""
        host = (urlparse(url).hostname or "").lower().removeprefix("www.") if url else ""
        title = src.get("title") or ""
        if (url and url.lower() in lowered) or (host and re.search(rf"(?<![a-z0-9-]){re.escape(host)}(?![a-z0-9-])", lowered)):
            return _passed("citations_present")
        # A multi-word title counts when quoted as written; any title counts as a name on word edges.
        if " " in title.strip() and re.search(rf"(?<!\w){re.escape(title.strip().lower())}(?!\w)", lowered):
            return _passed("citations_present")
        label = _normalized(_host_label(host))
        name = _normalized(title)
        # A lone-word title ("Home") is too common to prove a citation: it needs six letters.
        name_ok = len(name) >= (4 if " " in title.strip() else 6)
        if (len(label) >= 4 and _label_cited(label, content)) or (name_ok and _label_cited(name, content)):
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
    score_valid = isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 100
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
    if score < threshold and not issues:
        issues.append(
            {
                "severity": "high",
                "category": "score_below_threshold",
                "description": f"ReviewAgent scored the draft {score}, below the {threshold} threshold, but listed no issues.",
                "suggested_fix": "Strengthen the draft against the brief: accuracy, completeness, tone and structure.",
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
