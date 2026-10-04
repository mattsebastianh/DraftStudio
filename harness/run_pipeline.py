#!/usr/bin/env python3
"""Live execution harness for the DraftStudio pipeline.

  IntakeAgent -> [ResearchAgent] -> DraftAgent -> ReviewAgent (deterministic checks + LLM rubric,
  revision loop, max 3 cycles, approval computed in code at score >= 80) -> DispatchAgent

Model calls go to Groq (GROQ_FALLBACK_MODEL takes over after a daily-quota 429) and move to OpenRouter
for the rest of the run when Groq is unreachable or refuses the request. Every hop message is validated
against wires/*.yaml and every reply against agents/<Agent>/output_schema.json. Writes a JSON run log to
tests/live_runs/ (also when a step fails) and the approved deliverable to deliverables/.

Usage: .venv/bin/python harness/run_pipeline.py "<raw client request>"
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import checks, config, messages, schemas, wires  # noqa: E402
from harness.llm import LLMClient, ReplyError, build_messages  # noqa: E402
from harness.research import run_research  # noqa: E402

UNWIRED = {"client_to_IntakeAgent"}  # the one hop without a wire file: every other hop is validated and must have one
RESEARCH_CONFIDENCE_FLOOR = 60  # ResearchAgent's escalation rule: below this, flag the run for a human

INTAKE_FORMAT = (
    'Parse and classify this request. Return JSON: {"brief": {"topic", "audience", "tone", '
    '"length" (string), "key_points" (array), "format"}, "work_type", "needs_research" (boolean), '
    '"routing_plan" (array of agent names)}'
)
DRAFT_FORMAT = (
    'Write the full deliverable per the brief. Return JSON: {"draft": {"title", "content" '
    "(the complete deliverable in markdown, meeting the brief's length), "
    '"format", "unsupported" (array of claims without research backing), "word_count"}}'
)
REVIEW_FORMAT = (
    'Evaluate the draft against the brief. Return JSON: {"dimension_scores" ({"clarity", '
    '"accuracy", "completeness", "tone_alignment"}, each 0-100), "score" (composite 0-100, '
    'consistent with the dimensions), "requirements" (array of {"requirement", "passed"}), '
    '"issues" (array of {"severity" (critical/high/medium/low), "category", "description", '
    '"suggested_fix"}; empty if nothing to flag), "status" (advisory)}'
)
REVISE_FORMAT = (
    'Revise the draft to resolve every issue. Return JSON: {"draft": {"title", "content" '
    '(complete revised deliverable in markdown), "format", "unsupported", "word_count"}}. '
    "If sources are provided, keep citing the sources provided, and do not add sources that are not listed."
)
DISPATCH_FORMAT = (
    'Package this approved deliverable. Return JSON: {"package": {"title", "delivery_note" '
    '(short client-facing note), "status", "format", "sources" (array of URLs), "revision_history" '
    '(array), "metadata" (object)}}. Do not repeat the content.'
)


def run(raw_request, client, env, repo=config.REPO, toolbox=None):
    """Run one client request through the pipeline.

    Returns the run log, which is also written to tests/live_runs/run_<id>.json, also when a step fails
    (with the error recorded before the exception propagates).
    """
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log = {"run_id": run_id, "request": raw_request, "model": env["GROQ_PRIMARY_MODEL"], "steps": []}
    print(f"DraftStudio live run {run_id} — model {env['GROQ_PRIMARY_MODEL']}")
    progress = {"step": None}
    failed = False
    try:
        _run_steps(raw_request, client, env, repo, toolbox, log, progress)
    except Exception as err:
        failed = True
        log["error"] = f"{type(err).__name__}: {err}"
        log.setdefault("failed_step", progress["step"])
        print(f"  RUN FAILED: {log['error']}")
        raise
    finally:
        for key in ("fallback_model_used", "fallback_provider_used"):
            if getattr(client, key, None):
                log[key] = getattr(client, key)
        try:
            log_path = _live_runs_dir(repo) / f"run_{run_id}.json"
            log_path.write_text(json.dumps(log, indent=2) + "\n")
            print(f"\nRun log: {log_path.relative_to(repo)}")
        except OSError as err:
            print(f"could not write run log: {err}")
            if not failed:
                raise
    if log.get("deliverable"):
        print(f"Deliverable: {log['deliverable']} (final score {log['final_score']})")
    return log


def _live_runs_dir(repo):
    path = repo / "tests" / "live_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate(wire, message):
    errors = wires.validate_message(wire, message)
    if errors:
        raise wires.WireContractError(wire, errors)


def _save_bad_reply(repo, agent, err, log):
    """Keep the raw text of a reply that failed validation or was truncated, and record it in the run log."""
    bad = _live_runs_dir(repo) / f"bad_reply_{agent}_{int(time.time())}.txt"
    bad.write_text(err.raw or "")
    log["failed_step"] = agent
    log["bad_reply"] = str(bad.relative_to(repo))
    print(f"    raw reply saved to {log['bad_reply']}")


def _deliverable_path(repo, title, run_id):
    """deliverables/<slug>.md, or <slug>_<run_id>.md when that file exists: never overwrite a deliverable."""
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:60] or "deliverable"
    folder = repo / "deliverables"
    folder.mkdir(exist_ok=True)
    path = folder / f"{slug}.md"
    return folder / f"{slug}_{run_id}.md" if path.exists() else path


def _run_steps(raw_request, client, env, repo, toolbox, log, progress):
    def system_prompt(agent):
        return (repo / "agents" / agent / "system_prompt.txt").read_text()

    def run_agent(agent, wire, message, format_instructions):
        progress["step"] = agent
        if wire not in UNWIRED:
            _validate(wire, message)
        user_message = (
            f"Incoming message on wire `{wire}`:\n\n"
            + json.dumps(message, indent=2)
            + "\n\n"
            + format_instructions
            + "\nRespond with ONLY a valid JSON object, no other text."
        )
        max_tokens, effort = config.AGENT_BUDGETS[agent]
        try:
            parsed, meta = client.chat_structured(
                build_messages(system_prompt(agent), user_message), schemas.output_schema(agent), agent, max_tokens, effort
            )
        except ReplyError as err:
            _save_bad_reply(repo, agent, err, log)
            raise
        log["steps"].append({"agent": agent, "wire": wire, "input": message, "output": parsed, **meta})
        print(f"  {agent} done ({meta['seconds']}s, {meta['usage']['total_tokens']} tokens, {meta['provider']}:{meta['model']})")
        return parsed

    print("Step 1: IntakeAgent")
    progress["step"] = "IntakeAgent"
    intake = run_agent("IntakeAgent", "client_to_IntakeAgent", {"raw_request": raw_request}, INTAKE_FORMAT)
    brief = intake["brief"]

    dossier = None
    if intake["needs_research"]:
        print("Step 2: ResearchAgent")
        progress["step"] = "ResearchAgent"
        message = messages.intake_to_research(brief)
        _validate("IntakeAgent_to_ResearchAgent", message)
        try:
            dossier, meta = run_research(client, env, system_prompt("ResearchAgent"), message, toolbox=toolbox)
        except ReplyError as err:
            _save_bad_reply(repo, "ResearchAgent", err, log)
            raise
        _validate("ResearchAgent_to_DraftAgent", dossier)
        log["steps"].append({"agent": "ResearchAgent", "wire": "IntakeAgent_to_ResearchAgent", "input": message, "output": dossier, **meta})
        print(
            f"  ResearchAgent done ({len(dossier['findings'])} sourced findings, "
            f"{meta['dropped_findings']} dropped, confidence {dossier['confidence']})"
        )
        if dossier["confidence"] < RESEARCH_CONFIDENCE_FLOOR:
            note = f"research confidence {dossier['confidence']} < {RESEARCH_CONFIDENCE_FLOOR}: a human should check the dossier gaps"
            log.setdefault("flags", []).append(note)
            print(f"  note: {note}")

    print("Step 3: DraftAgent")
    progress["step"] = "DraftAgent"
    draft = run_agent("DraftAgent", "IntakeAgent_to_DraftAgent", messages.intake_to_draft(brief, dossier), DRAFT_FORMAT)

    for round_num in range(config.MAX_REVISION_CYCLES + 1):
        print(f"Step 4: ReviewAgent (round {round_num})")
        progress["step"] = "ReviewAgent"
        results = checks.run_checks(brief, draft["draft"]["content"], dossier)
        llm_review = run_agent(
            "ReviewAgent",
            "DraftAgent_to_ReviewAgent",
            messages.draft_to_review(brief, draft["draft"], round_num, [r.as_dict() for r in results]),
            REVIEW_FORMAT,
        )
        review = checks.finalize_review(llm_review, results, config.QUALITY_THRESHOLD)
        log["steps"][-1]["output"] = review
        log["final_score"] = review["score"]
        dims = review.get("dimension_scores")
        if dims:
            print("  dimensions: " + ", ".join(f"{k} {v}" for k, v in dims.items()))
        if review["status_disagreed"]:
            print(f"  note: model said '{review['llm_status']}', code decided '{review['status']}'")
        if review["status"] == "approved":
            print(f"  approved: score {review['score']} >= {config.QUALITY_THRESHOLD}, no critical issue")
            break
        if round_num == config.MAX_REVISION_CYCLES:
            print(f"  ESCALATION: {config.MAX_REVISION_CYCLES} revision cycles exhausted, score {review['score']}")
            log["escalated"] = True
            return
        critical = sum(1 for i in review["issues"] if i.get("severity") == "critical")
        print(f"  revision needed: score {review['score']}, {critical} critical issue(s)")
        print(f"Step 5: DraftAgent (revision {round_num + 1})")
        progress["step"] = "DraftAgent"
        draft = run_agent(
            "DraftAgent",
            "ReviewAgent_to_DraftAgent",
            messages.review_to_draft(brief, draft["draft"], review["issues"], round_num + 1, dossier),
            REVISE_FORMAT,
        )

    print("Step 6: DispatchAgent")
    progress["step"] = "DispatchAgent"
    dispatch = run_agent(
        "DispatchAgent",
        "ReviewAgent_to_DispatchAgent",
        messages.review_to_dispatch(draft["draft"], review, round_num, dossier),
        DISPATCH_FORMAT,
    )
    path = _deliverable_path(repo, draft["draft"]["title"], log["run_id"])
    path.write_text(draft["draft"]["content"] + "\n")
    log["deliverable"] = str(path.relative_to(repo))
    log["delivery"] = dispatch


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: run_pipeline.py '<client request>'")
    env = config.load_env()
    run(sys.argv[1], LLMClient(env), env)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
