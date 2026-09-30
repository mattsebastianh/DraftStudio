# DraftStudio Handbook — Running the Agents

A practical guide to operating the DraftStudio pipeline, from setup to reading the results, with a real worked example. For architecture and design principles, see [README.md](../README.md); this document is about *running* the studio day to day.

> **Two ways to run the pipeline.** This handbook covers the Python harness (sections 1-8). The same pipeline as an n8n workflow (webhook, Telegram, stricter quality gate) is documented in [n8n_workflow_design.md](n8n_workflow_design.md).

**Contents:** [1. One-time setup](#1-one-time-setup) · [2. Two ways to run](#2-two-ways-to-run-the-pipeline) · [3. Worked example](#3-worked-example--vacation-policy-memo) · [4. Reading the outputs](#4-reading-the-outputs) · [5. Rate limits and failures](#5-rate-limits-fallback-and-failure-handling) · [6. Crafting requests](#6-crafting-good-requests) · [7. Modifying the studio](#7-modifying-the-studio-itself) · [8. Troubleshooting](#8-troubleshooting)

---

## 1. One-Time Setup

```bash
cd ~/Documents/Projects/DraftStudio
cp .env.example .env        # then paste your real GROQ_API_KEY into .env
```

Verify the connection before anything else:

```bash
set -a && source .env && set +a
curl -s -o /dev/null -w "%{http_code}\n" "$GROQ_BASE_URL/models" -H "Authorization: Bearer $GROQ_API_KEY"
# expect: 200
```

Models for the harness are configured in `.env` only (the n8n workflow hard-codes its own, see the n8n design doc). Values below are the defaults in `.env.example`; your `.env` may override them:

| Variable | Default | Role |
|----------|--------------|------|
| `GROQ_PRIMARY_MODEL` | `llama-3.3-70b-versatile` | Every agent call, by default |
| `GROQ_FALLBACK_MODEL` | `openai/gpt-oss-120b` | Taken over automatically if the primary hits its daily token quota |
| `OPENROUTER_API_KEY` | (none) | Optional second provider; used for the rest of the run if Groq is unreachable or refuses the request |
| `OPENROUTER_PRIMARY_MODEL` | none; e.g. `openai/gpt-oss-120b` (required for the fallback) | Model used on OpenRouter after that switch |

## 2. Two Ways to Run the Pipeline

### A. Through claude-code (recommended)

Just ask for the deliverable in a claude-code session at the repo root:

> *"Write an internal memo announcing a new vacation policy"*

Per the convention in `CLAUDE.md`, Claude routes any request for a new draft, revision, or review through the live pipeline automatically — it invokes the harness, monitors the run, and reports the score, run log, and deliverable back to you. You never call the harness yourself.

### B. Directly via the harness

```bash
python3 harness/run_pipeline.py "<raw client request>" > /tmp/pipeline_run.log 2>&1 &
tail -f /tmp/pipeline_run.log
```

Two operational rules, learned the hard way:

- **Redirect output to a file outside any session tmp dir** (e.g. `/tmp/pipeline_run.log`). Session-managed tmp capture has dropped output before.
- **Run it in the background and tail the log.** A run normally takes 30 s – 3 min; free-tier rate limiting (see §5) can stretch it further.

### What flows where

```
"raw client request" ──► IntakeAgent ──► [ResearchAgent] ──► DraftAgent ──► ReviewAgent ──► DispatchAgent
                                                                  ▲              │
                                                                  └── revision ──┘  (max 3 cycles, then human escalation)
```

Full diagram of this pipeline: [01_pipeline_architecture_groq_harness.svg](01_pipeline_architecture_groq_harness.svg). The same pipeline as an importable n8n workflow is drawn in [02_pipeline_architecture_n8n.svg](02_pipeline_architecture_n8n.svg) and documented in [n8n_workflow_design.md](n8n_workflow_design.md).

Diagram files in `docs/` are named `NN_<subject>_<diagram-type>_<variant>.svg`: `NN` is the reading order, and the variant says which implementation is drawn (not which came later).

The single command-line argument is the entire client request. Put **everything** in it — constraints, tone, audience, format, hard limits — because IntakeAgent parses that one string into the structured brief every downstream agent works from. ResearchAgent only runs if IntakeAgent sets `needs_research: true`.

## 3. Worked Example — Vacation Policy Memo

This is a real run from 2026-06-11 (`tests/live_runs/run_20260611_024443.json`).

**The request** (note how audience, tone, constraints, and format are all spelled out):

```bash
python3 harness/run_pipeline.py "Write an internal memo announcing a new company vacation policy. The new policy moves from a fixed 15-days-per-year accrual system to an unlimited PTO model, effective at the start of next quarter. Audience: all employees. Tone: positive and reassuring, but clear about expectations (manager approval still required, minimum 10 days/year encouraged, no unused-PTO payout under the new policy). Format: internal memo with a subject line, brief explanation of the change and why, what stays the same vs. what changes, and a short FAQ." > /tmp/pipeline_run.log 2>&1 &
```

**What the log showed:**

```
DraftStudio live run 20260611_024443 — model llama-3.3-70b-versatile
Step 1: IntakeAgent
  IntakeAgent done (1.0s, 713 tokens, llama-3.3-70b-versatile)
Step 3: DraftAgent
  DraftAgent done (2.0s, 1024 tokens, llama-3.3-70b-versatile)
Step 4: ReviewAgent (round 0)
    HTTP 429, retrying in 13s... (tokens per minute (TPM): Limit 12000 ...)
  ReviewAgent done (14.5s, 1703 tokens, llama-3.3-70b-versatile)
  dimensions: clarity 90, accuracy 95, completeness 95, tone_alignment 90
  approved: score 92 >= 80
Step 6: DispatchAgent
  DispatchAgent done (13.2s, 450 tokens, llama-3.3-70b-versatile)

Run log: tests/live_runs/run_20260611_024443.json
Deliverable: deliverables/introduction_of_new_company_vacation_policy.md (final score 92)
```

Reading it:

- **Step 2 (ResearchAgent) is absent** — IntakeAgent decided the brief needed no research. That's routing working, not a bug.
- **The `HTTP 429, retrying in 13s` line is normal** free-tier throttling, handled automatically (§5).
- **`approved: score 92 >= 80` on round 0** — no revision cycle was needed. ReviewAgent verified all 10 requirements it extracted from the brief (unlimited PTO, manager approval retained, no-payout rule, FAQ, tone, …) and flagged one low-severity style issue.
- **Outcome:** the finished memo landed in `deliverables/introduction_of_new_company_vacation_policy.md`, ~396 words, with the old-vs-new comparison table and 3-question FAQ the brief demanded. Total cost: ~3,900 tokens across 4 calls, ~45 s wall clock.

## 4. Reading the Outputs

| Artifact | Where | What's in it |
|----------|-------|--------------|
| Run log | `tests/live_runs/run_<timestamp>.json` | Every step: agent, wire, full input/output JSON, model used, token counts, timing. Top level: `request`, `deliverable`, `escalated`, `fallback_model_used` |
| Deliverable | `deliverables/<slug>.md` | The approved content, written only if ReviewAgent approved |
| Bad replies | `tests/live_runs/bad_reply_<Agent>_<ts>.txt` | Raw model reply when an agent returned unparseable JSON 3× (run aborts) |

Quick checks on a run log:

```bash
# Did the revision loop fire? (more than one ReviewAgent step / any revision rounds)
python3 -c "import json; d=json.load(open('tests/live_runs/run_20260611_024443.json')); print([s['agent'] for s in d['steps']], 'escalated:', d.get('escalated', False), 'fallback:', d.get('fallback_model_used'))"
```

**Log every run to Notion** under *DraftStudio Agent Workflow → Pipeline Tests* — this is a standing project convention.

## 5. Rate Limits, Fallback, and Failure Handling

The harness handles all of these on its own; this is what the log lines mean when you see them.

| Log line | Meaning | Action needed |
|----------|---------|---------------|
| `HTTP 429, retrying in Ns... (... (TPM) ...)` | Per-minute token throttle (free tier: 12k TPM on llama). Harness waits and retries, up to 5 attempts | None — normal |
| `<model> hit its daily token quota, falling back to <fallback>` | Daily (TPD) quota exhausted. Harness switches to the fallback model for the **rest of the run** and records `fallback_model_used` in the log | None — but quota resets take up to ~24h; consider Dev Tier if frequent |
| `bad JSON from <Agent> (attempt N/3)` | Model returned malformed JSON; harness re-asks | None unless it hits 3/3, which aborts the run and saves the raw reply |
| `ESCALATION: 3 revision cycles exhausted, score <N>` | Draft never reached 80/100. **No deliverable is written** — a human (you) must take over | Review the run log's final draft + issues, decide manually |
| `connection error, retrying in Ns...` | Network blip | None — normal |
| `Groq unavailable, switching to OpenRouter for the rest of the run` | Groq failed permanently (403 region/VPN block, 401, outage, retries exhausted). Every later call goes to OpenRouter and the log records `fallback_provider_used` | None if `OPENROUTER_API_KEY` is set; otherwise the run stops with the Groq error |

One real-world note: a run that mixes both models (e.g. starts on the primary, falls back mid-run) is fine and has happened in practice — `run_20260611_022533.json` started IntakeAgent on `gpt-oss-120b`, hit the daily quota, and finished the remaining three steps on llama with a final score of 94.

## 6. Crafting Good Requests

From the live-test history (`tests/live_runs/`, Notion "Pipeline Tests"):

- **Be exhaustive in the one argument.** Anything not in the request string doesn't exist for the agents.
- **State format structurally** ("a 5-row table with columns X, Y, Z", "exactly 3 FAQ entries") — DraftAgent follows structure well.
- **Avoid "exactly N words".** Reasoning models can burn their whole token budget counting words and return nothing. Ranges or caps ("must not exceed 380 words") work fine. (The n8n workflow does check "exactly N words", allowing ±5%, and a required closing sentence; the harness does not.)
- **Don't expect word-count violations to force a revision** — ReviewAgent treats length misses as low/medium severity, not critical. Every live run so far has been approved on round 0 (scores 85–94).

## 7. Modifying the Studio Itself

Running the agents is the harness's job; *changing* them goes through the project slash commands in claude-code, in this order:

1. `/spec-agent` — write the spec first, always
2. `/new-agent` — scaffold from the spec
3. `/agent-wire` — wire it to its neighbors (updates **both** agents' tools.json)
4. `/agent-review` — audit; fix all Critical/High findings before activating

The agent registry (`agents/registry.yaml`) tracks status and wiring for all five agents; each agent's behavior lives in `agents/<Name>/system_prompt.txt` (kept under 500 tokens) and its tool surface in `agents/<Name>/tools.json`. If you change a prompt or wire, re-run a live pipeline test and log it to Notion.

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `curl $GROQ_BASE_URL/models` non-200 | Bad/missing `GROQ_API_KEY`, or Groq incident | Check `.env`, then [groqstatus.com](https://groqstatus.com) |
| Run exits fast with empty log | Crash before the first API call | Run the same command in the foreground to see the traceback |
| Run seems hung for minutes | TPM backoff loop, or a long retry chain | `tail` the log; check `ps -o pid,etime,stat -p <pid>` — state `S` is healthy waiting |
| Every reply unparseable from one agent | System prompt drift / model change | Inspect the `bad_reply_*.txt`, then revisit that agent's `system_prompt.txt` |
| `rate_limit_exceeded ... (TPD)` even on fallback | Both Groq models out of daily quota | With `OPENROUTER_API_KEY` set the harness moves to OpenRouter on its own; otherwise wait for reset or upgrade tier |
| `HTTP 403` from Groq | Regional block, often a VPN exit IP | Switch off the VPN or rely on the OpenRouter fallback |
