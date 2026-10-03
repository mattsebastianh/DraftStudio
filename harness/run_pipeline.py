#!/usr/bin/env python3
"""Minimal live execution harness for the DraftStudio pipeline.

Loads .env, sends each agent's system prompt + incoming wire message to the
Groq API (falling back to OpenRouter if Groq is unavailable), and routes real model outputs through the wire sequence:

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
import urllib.parse
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
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            env[key.strip()] = value
    return env


ENV = load_env()

# Model used for the rest of the run once the primary model becomes
# unavailable (e.g. daily token quota exhausted). Sticky across calls so we
# don't re-trigger the same rate limit on every subsequent step.
ACTIVE_MODEL = ENV["GROQ_PRIMARY_MODEL"]

# Cross-provider fallback: when Groq is unreachable or refuses us (regional
# block 403, outage, both Groq models exhausted), the rest of the run goes to
# OpenRouter. Sticky for the same reason as ACTIVE_MODEL.
FALLBACK_PROVIDER = None


def openrouter_configured():
    key = ENV.get("OPENROUTER_API_KEY", "")
    return bool(key) and not key.startswith("your-") and bool(ENV.get("OPENROUTER_PRIMARY_MODEL"))


def _require_safe_base_url(base_url):
    """The API key is sent to base_url, so refuse plain http except for a local server."""
    parts = urllib.parse.urlsplit(base_url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError(f"refusing to send an API key to {base_url!r}: base URL must be https (or http on localhost)")


def _chat_request(base_url, api_key, use_model, system_prompt, user_message, max_tokens, groq_quota_fallback):
    """One provider call with retries. Returns (body, model_used); raises when the provider is exhausted."""
    global ACTIVE_MODEL
    _require_safe_base_url(base_url)
    for attempt in range(5):
        payload = {
            "model": use_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.6,
        }
        req = urllib.request.Request(
            base_url + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
                "User-Agent": "DraftStudio-harness/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.load(resp), use_model
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:300]
            quota_exhausted = err.code == 429 and "tokens per day" in detail.lower()
            if quota_exhausted and groq_quota_fallback and use_model != ENV["GROQ_FALLBACK_MODEL"]:
                print(f"    {use_model} hit its daily token quota, falling back to {ENV['GROQ_FALLBACK_MODEL']}")
                use_model = ENV["GROQ_FALLBACK_MODEL"]
                ACTIVE_MODEL = use_model
                continue
            retryable = err.code in (429, 500, 502, 503) or (
                err.code == 400 and "tool_use_failed" in detail
            )
            if not retryable or attempt == 4:
                print(f"    HTTP {err.code}: {detail}")
                raise
            wait = float(err.headers.get("Retry-After") or 2 ** (attempt + 1))
            print(f"    HTTP {err.code}, retrying in {wait:.0f}s... ({detail})")
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            if attempt == 4:
                print(f"    connection error: {err}")
                raise
            wait = 2 ** (attempt + 1)
            print(f"    connection error, retrying in {wait:.0f}s... ({err})")
            time.sleep(wait)


def chat(system_prompt, user_message, max_tokens, model=None):
    global FALLBACK_PROVIDER
    started = time.time()
    body = None
    if FALLBACK_PROVIDER is None:
        try:
            body, use_model = _chat_request(
                ENV["GROQ_BASE_URL"], ENV["GROQ_API_KEY"], model or ACTIVE_MODEL,
                system_prompt, user_message, max_tokens, groq_quota_fallback=model is None,
            )
        except (urllib.error.URLError, TimeoutError, OSError):
            # HTTPError is a URLError subclass: covers 403 region blocks, exhausted retries, outages
            if not openrouter_configured():
                raise
            print("    Groq unavailable, switching to OpenRouter for the rest of the run")
            FALLBACK_PROVIDER = "openrouter"
    if body is None:
        body, use_model = _chat_request(
            ENV.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"), ENV["OPENROUTER_API_KEY"],
            ENV["OPENROUTER_PRIMARY_MODEL"], system_prompt, user_message, max_tokens, groq_quota_fallback=False,
        )
    return {
        "content": body["choices"][0]["message"]["content"],
        "usage": body.get("usage", {}),
        "seconds": round(time.time() - started, 1),
        "model": use_model,
    }


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
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(_escape_raw_control_chars_in_strings(text[start : i + 1]))
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
    for attempt in range(3):
        result = chat(system_prompt(agent), user_message, max_tokens)
        try:
            parsed = extract_json(result["content"])
            break
        except (ValueError, json.JSONDecodeError) as err:
            print(f"    bad JSON from {agent} (attempt {attempt + 1}/3): {err}")
            if attempt == 2:
                (REPO / "tests" / "live_runs").mkdir(exist_ok=True)
                bad = REPO / "tests" / "live_runs" / f"bad_reply_{agent}_{int(time.time())}.txt"
                bad.write_text(result["content"])
                print(f"    raw reply saved to {bad.relative_to(REPO)}")
                raise
    LOG["steps"].append(
        {
            "agent": agent,
            "wire": wire,
            "input": message,
            "output": parsed,
            "model": result["model"],
            "tokens": result["usage"].get("total_tokens"),
            "prompt_tokens": result["usage"].get("prompt_tokens"),
            "completion_tokens": result["usage"].get("completion_tokens"),
            "seconds": result["seconds"],
        }
    )
    print(f"  {agent} done ({result['seconds']}s, {result['usage'].get('total_tokens')} tokens, {result['model']})")
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
        4500,
    )

    review = None
    for round_num in range(MAX_REVISION_CYCLES + 1):
        print(f"Step 4: ReviewAgent (round {round_num})")
        review = run_agent(
            "ReviewAgent",
            "DraftAgent_to_ReviewAgent",
            {"brief": intake["brief"], "draft": draft["draft"], "revision_round": round_num},
            'Evaluate the draft against the brief. Return JSON with keys in this order: '
            '{"dimension_scores" ({"clarity", "accuracy", "completeness", "tone_alignment"}, '
            'each 0-100), "score" (composite 0-100, consistent with the dimensions), '
            '"requirements" (array of {"requirement", "passed" (boolean)}), '
            '"issues" (array of {"severity" (critical/high/medium/low), "description", '
            '"suggested_fix"}; empty if nothing to flag), "status" (derive it mechanically from '
            f'the fields above: "approved" when score >= {QUALITY_THRESHOLD} and no issue is '
            'critical, else "revision_required" — non-critical issues do not block approval)}',
            4500,
        )
        has_critical = any(
            isinstance(i, dict) and i.get("severity") == "critical" for i in review.get("issues", [])
        )
        dims = review.get("dimension_scores")
        if dims:
            print("  dimensions: " + ", ".join(f"{k} {v}" for k, v in dims.items()))
        if review["score"] >= QUALITY_THRESHOLD and not has_critical:
            print(f"  approved: score {review['score']} >= {QUALITY_THRESHOLD}")
            break
        if round_num == MAX_REVISION_CYCLES:
            print(f"  ESCALATION: {MAX_REVISION_CYCLES} revision cycles exhausted, score {review['score']}")
            LOG["escalated"] = True
            break
        reason = "critical issue flagged" if has_critical else f"score {review['score']} < {QUALITY_THRESHOLD}"
        print(f"  revision needed: {reason}")
        print(f"Step 5: DraftAgent (revision {round_num + 1})")
        draft = run_agent(
            "DraftAgent",
            "ReviewAgent_to_DraftAgent",
            {"brief": intake["brief"], "previous_draft": draft["draft"], "issues": review["issues"],
             "revision_round": round_num + 1},
            'Revise the draft to resolve every issue. Return JSON: {"draft": {"title", "content" '
            '(complete revised deliverable in markdown), "word_count"}}',
            4500,
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
    if ACTIVE_MODEL != ENV["GROQ_PRIMARY_MODEL"]:
        LOG["fallback_model_used"] = ACTIVE_MODEL
    if FALLBACK_PROVIDER:
        LOG["fallback_provider_used"] = FALLBACK_PROVIDER
    log_path.write_text(json.dumps(LOG, indent=2) + "\n")
    print(f"\nRun log: {log_path.relative_to(REPO)}")
    if LOG.get("deliverable"):
        print(f"Deliverable: {LOG['deliverable']} (final score {review['score']})")


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
