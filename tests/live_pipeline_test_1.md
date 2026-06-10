# Live Pipeline Test 1: First Real Model Execution

**Date:** 2026-06-10
**Type:** LIVE — real Groq API inference per agent (first non-mock pipeline run)
**Harness:** `harness/run_pipeline.py`
**Model:** `openai/gpt-oss-120b` (service tier: on_demand / free)
**Run log (full tool I/O):** `tests/live_runs/run_20260610_212603.json`

---

## Request

Same practical scenario as Mock Test 2:

> "I need a guide on choosing a CRM for solo consultants — around 2,000 words, professional but friendly. My readers are independent consultants who hate bloated enterprise software. Compare a few real options with pricing."

---

## Run Summary

| Step | Agent | Wire | Tokens | Latency |
|------|-------|------|--------|---------|
| 1 | IntakeAgent | client → Intake | 954 | 1.6s |
| 2 | ResearchAgent | Intake → Research | 1,920 | 3.5s |
| 3 | DraftAgent | Intake → Draft (+ dossier) | 4,508 | 47.4s* |
| 4 | ReviewAgent | Draft → Review (round 0) | 3,971 | 41.6s* |
| 5 | DispatchAgent | Review → Dispatch | 861 | 1.7s |

\* includes free-tier rate-limit waits (see Issues)

**Outcome:**
- IntakeAgent classified `full_service`, produced a complete structured brief
- ResearchAgent dossier: 80% overall confidence (above the 60% escalation floor), per-claim confidence included
- Draft: **2,047 words** (brief asked 1,800–2,200) — comparison of HubSpot, Zoho, Pipedrive, Less Annoying CRM with pricing
- ReviewAgent: **score 92/100, approved on round 0** — all 6 requirements passed, no revision cycle needed
- DispatchAgent packaged with client-facing delivery note
- **Deliverable:** `deliverables/choosing_the_right_crm_for_solo_consultants_a_practical_guid.md`

**Total run cost:** ~12,200 tokens across 5 calls, ~96s wall clock (≈20s of actual inference; the rest was free-tier rate-limit backoff).

---

## Issues Found & Fixed (harness hardening)

| # | Issue | Fix |
|---|-------|-----|
| 1 | Groq edge returns **403 Forbidden** to Python's default `urllib` User-Agent (curl works) | Harness sends `User-Agent: DraftStudio-harness/1.0` |
| 2 | Free tier TPM limit (8,000 tokens/min for gpt-oss-120b) → **429** on consecutive calls | Retry loop honoring `Retry-After` header, 5 attempts |
| 3 | One transient **413** observed during an early run (request + max_tokens vs TPM window) | Resolved by the retry/pacing behavior; not reproduced |

---

## Observations (for v2)

1. **Quality gate passed but wasn't stressed:** approval on round 0 means the live revision loop (`ReviewAgent → DraftAgent`) is still unexercised with real models. A stricter rubric or a deliberately under-specified brief would force it.
2. **ReviewAgent requirements were shallow:** it echoed the brief's six fields as pass/fail rather than decomposing them (e.g., it didn't independently verify word count). The per-dimension scoring item on the v2 list would address this.
3. **ResearchAgent used model knowledge, not live web search** — the harness tells it so and it correctly tagged per-claim confidence (75–90%). Pricing claims in the deliverable should be treated as indicative until a real `web_search` tool is wired in.
4. **Free tier is the bottleneck:** 8k TPM means draft-sized calls queue behind each other. Fine for single runs; Dev Tier needed for anything concurrent.
5. **Wires not covered live:** mid-draft research, fact-check, client-revision routing, and all escalation paths. Candidates for Live Test 2.

---

## Verdict

**PASS** — first live execution of the full pipeline. All 5 agents produced valid, schema-conforming JSON over their wires with zero parse failures; quality gate enforced; deliverable met the brief (length, tone, audience, comparison + pricing) and scored 92/100.

The v2 roadmap item "Live execution test with real model invocations via the Groq API" is **done**.
