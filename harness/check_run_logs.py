#!/usr/bin/env python3
"""Acceptance checker for Phase 1 run logs (spec §6: A1, A2, A5).

Usage: .venv/bin/python harness/check_run_logs.py tests/live_runs/run_<id>.json [...]
Prints PASS/FAIL per log and exits non-zero if any log fails.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.urls import normalize_url  # noqa: E402

STEP_META = ("schema_enforced", "validation_retries", "finish_reasons")


def _research_problems(step, output):
    findings = output.get("findings", [])
    if any(not finding.get("sources") for finding in findings):
        return ["A2: a research finding without a source reached DraftAgent"]
    if "retrieved_urls" not in step:  # logs from before the harness recorded retrieved URLs
        return []
    retrieved = {normalize_url(str(url)) for url in step["retrieved_urls"]}
    cited = {str(url) for finding in findings for url in finding["sources"]}
    if any(normalize_url(url) not in retrieved for url in cited):
        return ["A2: a research finding cites a URL the tools never retrieved"]
    return []


def check(log):
    """Return the acceptance problems in one run log (an empty list means it passes)."""
    problems = []
    if "error" in log:
        problems.append(f"run failed: {log['error']}")
    if log.get("escalated"):
        problems.append("A4: run escalated to a human (revision cycles exhausted); there is no deliverable")
    elif "error" not in log and not log.get("deliverable"):
        problems.append("A4: run produced no deliverable (interrupted or incomplete)")
    for flag in log.get("flags", []):
        problems.append(f"A4: flagged for a human: {flag}")
    for step in log.get("steps", []):
        agent = step.get("agent", "?")
        if step.get("skipped"):  # research that made no dossier call (no search key, nothing retrieved)
            continue
        missing = [key for key in STEP_META if key not in step]
        if missing:
            problems.append(f"A5: {agent} step is missing {missing}")
        if (step.get("finish_reasons") or [None])[-1] == "length":
            problems.append(f"A1: {agent} final reply was truncated")
        if step.get("used_extract_json"):
            problems.append(f"A1: {agent} reply needed the extract_json fallback")
        output = step.get("output") or {}
        if agent == "ResearchAgent":
            problems.extend(_research_problems(step, output))
        if agent == "ReviewAgent" and "checks" not in output:
            problems.append("A5: review step has no deterministic check results")
    return problems


def main(paths):
    failed = False
    for path in paths:
        try:
            with open(path) as handle:
                problems = check(json.load(handle))
        except (OSError, ValueError, AttributeError, TypeError) as err:  # unreadable, invalid JSON or not a run log
            problems = [f"could not read run log: {type(err).__name__}"]
        print(("FAIL " if problems else "PASS ") + path)
        for problem in problems:
            print("   - " + problem)
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
