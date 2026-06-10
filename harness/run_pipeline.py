#!/usr/bin/env python3
"""Minimal live execution harness for the DraftStudio pipeline.

Loads .env, sends each agent's system prompt + incoming wire message to the
Groq API, and routes real model outputs through the wire sequence:

  IntakeAgent -> ResearchAgent -> DraftAgent -> ReviewAgent (revision loop,
  max 3 cycles, approval at score >= 80) -> DispatchAgent

Stdlib only. Usage:
  python3 harness/run_pipeline.py "<raw client request>"

Writes a JSON run log to tests/live_runs/ and the approved deliverable to
deliverables/.
"""

import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QUALITY_THRESHOLD = 80
MAX_REVISION_CYCLES = 3


def load_env():
    env = {}
    for line in (REPO / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


ENV = load_env()


def chat(system_prompt, user_message, max_tokens, model=None):
    payload = {
        "model": model or ENV["GROQ_PRIMARY_MODEL"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.6,
    }
    req = urllib.request.Request(
        ENV["GROQ_BASE_URL"] + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + ENV["GROQ_API_KEY"],
            "Content-Type": "application/json",
            "User-Agent": "DraftStudio-harness/1.0",
        },
    )
    started = time.time()
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = json.load(resp)
            break
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:300]
            if err.code not in (429, 500, 502, 503) or attempt == 4:
                print(f"    HTTP {err.code}: {detail}")
                raise
            wait = float(err.headers.get("Retry-After") or 2 ** (attempt + 1))
            print(f"    HTTP {err.code}, retrying in {wait:.0f}s... ({detail})")
            time.sleep(wait)
    return {
        "content": body["choices"][0]["message"]["content"],
        "usage": body.get("usage", {}),
        "seconds": round(time.time() - started, 1),
    }


def extract_json(text):
    """Pull the first JSON object out of a model reply (tolerates fences/prose)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in model reply")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("unbalanced JSON in model reply")


def system_prompt(agent):
    return (REPO / "agents" / agent / "system_prompt.txt").read_text()


LOG = {"steps": []}


def run_agent(agent, wire, message, format_instructions, max_tokens):
    """One wire hop: send `message` to `agent`, expect JSON back."""
    user_message = (
        f"Incoming message on wire `{wire}`:\n\n"
        + json.dumps(message, indent=2)
        + "\n\n"
        + format_instructions
        + "\nRespond with ONLY a valid JSON object, no other text."
    )
    result = chat(system_prompt(agent), user_message, max_tokens)
    parsed = extract_json(result["content"])
    LOG["steps"].append(
        {
            "agent": agent,
            "wire": wire,
            "input": message,
            "output": parsed,
            "tokens": result["usage"].get("total_tokens"),
            "prompt_tokens": result["usage"].get("prompt_tokens"),
            "completion_tokens": result["usage"].get("completion_tokens"),
            "seconds": result["seconds"],
        }
    )
    print(f"  {agent} done ({result['seconds']}s, {result['usage'].get('total_tokens')} tokens)")
    return parsed


def main():
    raw_request = sys.argv[1] if len(sys.argv) > 1 else sys.exit("usage: run_pipeline.py '<client request>'")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    LOG.update(run_id=run_id, request=raw_request, model=ENV["GROQ_PRIMARY_MODEL"])
    print(f"DraftStudio live run {run_id} — model {ENV['GROQ_PRIMARY_MODEL']}")

    print("Step 1: IntakeAgent")
    intake = run_agent(
        "IntakeAgent",
        "client_to_IntakeAgent",
        {"raw_request": raw_request},
        'Parse and classify this request. Return JSON: {"brief": {"topic", "audience", "tone", '
        '"length", "key_points" (array), "format"}, "work_type", "needs_research" (boolean), '
        '"routing_plan" (array of agent names)}',
        3000,
    )

    dossier = None
    if intake.get("needs_research", True):
        print("Step 2: ResearchAgent")
        dossier = run_agent(
            "ResearchAgent",
            "IntakeAgent_to_ResearchAgent",
            {"topic": intake["brief"]["topic"], "focus_areas": intake["brief"].get("key_points", [])},
            'Compile a research dossier from your knowledge (live web search unavailable in this '
            'harness; mark each finding\'s confidence accordingly). Return JSON: {"dossier": '
            '{"topic", "findings" (array of {"claim", "confidence" (0-100)}), "gaps" (array), '
            '"confidence" (0-100 overall)}}',
            6000,
        )

    print("Step 3: DraftAgent")
    draft = run_agent(
        "DraftAgent",
        "IntakeAgent_to_DraftAgent",
        {"brief": intake["brief"], "dossier": (dossier or {}).get("dossier")},
        'Write the full deliverable per the brief. Return JSON: {"draft": {"title", "content" '
        '(the complete deliverable in markdown, meeting the brief\'s length), "word_count"}}',
        16000,
    )

    review = None
    for round_num in range(MAX_REVISION_CYCLES + 1):
        print(f"Step 4: ReviewAgent (round {round_num})")
        review = run_agent(
            "ReviewAgent",
            "DraftAgent_to_ReviewAgent",
            {"brief": intake["brief"], "draft": draft["draft"], "revision_round": round_num},
            'Evaluate the draft against the brief. Return JSON: {"score" (0-100), "requirements" '
            '(array of {"requirement", "passed" (boolean)}), "issues" (array of specific, '
            'actionable revision notes; empty if approved)}',
            6000,
        )
        if review["score"] >= QUALITY_THRESHOLD:
            print(f"  approved: score {review['score']} >= {QUALITY_THRESHOLD}")
            break
        if round_num == MAX_REVISION_CYCLES:
            print(f"  ESCALATION: {MAX_REVISION_CYCLES} revision cycles exhausted, score {review['score']}")
            LOG["escalated"] = True
            break
        print(f"  revision needed: score {review['score']} < {QUALITY_THRESHOLD}")
        print(f"Step 5: DraftAgent (revision {round_num + 1})")
        draft = run_agent(
            "DraftAgent",
            "ReviewAgent_to_DraftAgent",
            {"brief": intake["brief"], "previous_draft": draft["draft"], "issues": review["issues"],
             "revision_round": round_num + 1},
            'Revise the draft to resolve every issue. Return JSON: {"draft": {"title", "content" '
            '(complete revised deliverable in markdown), "word_count"}}',
            16000,
        )

    if not LOG.get("escalated"):
        print("Step 6: DispatchAgent")
        dispatch = run_agent(
            "DispatchAgent",
            "ReviewAgent_to_DispatchAgent",
            {"draft_title": draft["draft"]["title"],
             "review_summary": {"score": review["score"], "review_status": "approved"}},
            'Package this approved deliverable. Return JSON: {"package": {"title", '
            '"delivery_note" (short client-facing note), "status"}}',
            2000,
        )
        slug = re.sub(r"[^a-z0-9]+", "_", draft["draft"]["title"].lower()).strip("_")[:60]
        deliverable_path = REPO / "deliverables" / f"{slug}.md"
        deliverable_path.write_text(draft["draft"]["content"] + "\n")
        LOG["deliverable"] = str(deliverable_path.relative_to(REPO))
        LOG["delivery"] = dispatch

    log_dir = REPO / "tests" / "live_runs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"run_{run_id}.json"
    log_path.write_text(json.dumps(LOG, indent=2) + "\n")
    print(f"\nRun log: {log_path.relative_to(REPO)}")
    if LOG.get("deliverable"):
        print(f"Deliverable: {LOG['deliverable']} (final score {review['score']})")


if __name__ == "__main__":
    main()
