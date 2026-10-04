#!/usr/bin/env python3
"""Acceptance checker for Phase 1 run logs (spec §6: A1, A2, A5).

Usage: .venv/bin/python harness/check_run_logs.py tests/live_runs/run_<id>.json [...]
Prints PASS/FAIL per log and exits non-zero if any log fails.
"""

import json
import sys

STEP_META = ("schema_enforced", "validation_retries", "finish_reasons")


def check(log):
    """Return the acceptance problems in one run log (an empty list means it passes)."""
    problems = []
    if "error" in log:
        problems.append(f"run failed: {log['error']}")
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
        if agent == "ResearchAgent" and any(not finding.get("sources") for finding in output.get("findings", [])):
            problems.append("A2: a research finding without a source reached DraftAgent")
        if agent == "ReviewAgent" and "checks" not in output:
            problems.append("A5: review step has no deterministic check results")
    return problems


def main(paths):
    failed = False
    for path in paths:
        with open(path) as handle:
            problems = check(json.load(handle))
        print(("FAIL " if problems else "PASS ") + path)
        for problem in problems:
            print("   - " + problem)
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
