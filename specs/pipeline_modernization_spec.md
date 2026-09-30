# Spec: Pipeline Modernization (Phase 1 in detail, Phases 2-4 outlined)

- **Status:** Draft — awaiting review
- **Created:** 2026-09-29
- **Touches:** `harness/run_pipeline.py`, `wires/*.yaml`, `agents/{Research,Review,Draft,Intake,Dispatch}Agent/tools.json`, `specs/ResearchAgent_spec.md`, `specs/ReviewAgent_spec.md`, `.env.example`

## 1. Problem
The five-agent pipeline (Intake → Research → Draft ⇄ Review → Dispatch) has the right shape but a dated implementation:

| # | Weakness | Evidence in repo |
|---|----------|------------------|
| P1 | Model replies are free text; JSON is dug out with `extract_json` and retried on failure | `tests/live_runs/bad_reply_DraftAgent_*.txt` (2 saved failures) |
| P2 | ResearchAgent cannot research: harness tells it "live web search unavailable", so findings are model recall with self-rated confidence | `run_pipeline.py` Step 2 prompt |
| P3 | ReviewAgent is the only gate, and it is a single LLM opinion. The "derive status mechanically" rule is enforced by asking the model to do it | Step 4 prompt |
| P4 | Ad hoc message shapes in the harness diverge from the contracts in `wires/*.yaml` | e.g. dossier/review fields vs. wire schemas |
| P5 | `max_tokens` values (2000-6000) were sized for Llama; a reasoning model (gpt-oss-120b) spends completion tokens on reasoning, so long drafts can truncate | primary model changed in `.env` |

## 2. Goals (Phase 1)
- **G1 Structured outputs:** every agent hop returns schema-valid JSON by construction, not by parsing luck.
- **G2 Real research:** ResearchAgent gets a search/fetch tool; every finding carries a source URL.
- **G3 Hybrid review:** deterministic checks run in code first; the LLM rubric judges what code can't; code, not the model, computes the final status.
- **G4 Single source of truth:** `wires/*.yaml` `message_schema` drives validation in the harness.
- **G5 Reasoning-model safe:** token budgets and reasoning effort set so no truncation on the primary model.

## 3. Non-goals (Phase 1)
- Replacing the agent split or merging agents.
- A durable workflow engine / framework migration.
- OpenRouter wiring (env vars exist; harness support is Phase 3).
- Changing the 80-point threshold or the 3-cycle escalation rule.

## 4. Requirements

### G1 — Structured outputs
- R1.1 Load each wire's `message_schema` from `wires/*.yaml`, convert to JSON Schema, and pass it to the API as `response_format` (json_schema) where the model supports it.
- R1.2 For models/paths without schema enforcement, fall back to JSON mode plus local validation.
- R1.3 On validation failure, retry with the validation error text appended (max 2 retries), then fail the run and save the raw reply as today.
- R1.4 `extract_json` is kept only as the last-resort path and logged when used.
- R1.5 Each step's log entry records `schema_enforced: true|false` and `validation_retries`.

### G2 — Research with tools
- R2.1 ResearchAgent's `tools.json` defines `web_search(query)` and `fetch_url(url)`; the harness runs a tool loop (max 6 tool calls per dossier).
- R2.2 Dossier findings become `{claim, source_url, quote, confidence}`; a finding with no `source_url` is dropped by the harness and listed under `gaps`.
- R2.3 The "live web search unavailable" text is removed from the harness prompt.
- R2.4 If search is unavailable at runtime, ResearchAgent returns `gaps` and `confidence <= 40`, and the run continues (fail soft, never fabricate sources).
- R2.5 `.env.example` documents any new key (see Open Question Q2).

### G3 — Hybrid review
- R3.1 New module `harness/checks.py` with deterministic checks, each returning `{id, passed, severity, detail}`:
  - `length`: word count within the brief's requested length (±15%).
  - `key_points_covered`: each brief key point appears (keyword/stem match) in the draft.
  - `no_placeholders`: no `TODO`, `[insert…]`, `lorem ipsum`, `XXX` (**critical** if found).
  - `citations_present`: if a dossier was used, the draft cites at least one dossier source.
  - `format`: markdown headings present when the brief format asks for structure.
- R3.2 Deterministic results are passed to ReviewAgent as input so it does not re-derive them, and are merged into `review.issues` with their severity and a suggested fix.
- R3.3 Final `status` is computed in code: `approved` iff `score >= 80` and no critical issue (LLM or deterministic). The model's own `status` field is ignored (kept for logging, flagged if it disagrees).
- R3.4 Composite score stays the LLM's; deterministic failures can only block or cap, never raise it.
- R3.5 ReviewAgent's system prompt and `specs/ReviewAgent_spec.md` are updated to describe the split responsibility.

### G4 / G5 — Contracts and budgets
- R4.1 Reconcile harness message shapes with `wires/*.yaml`; where the wire is wrong, change the wire (and both agents' `tools.json`, per project rule); where the harness is wrong, change the harness. Each changed wire gets a version bump.
- R5.1 Set `reasoning_effort` per agent (low for Intake/Dispatch, medium for Research/Review, medium for Draft) and raise `max_tokens` so completion budget = expected output + reasoning headroom.
- R5.2 Log `finish_reason`; a `length` finish is treated as a failure and retried once with a higher budget.

## 5. Design sketch
```
harness/
  run_pipeline.py     # orchestration only (slimmer)
  llm.py              # chat(), fallback, structured-output + retry, tool loop
  wires.py            # load wires/*.yaml -> JSON Schema, validate
  tools.py            # web_search, fetch_url
  checks.py           # deterministic review checks
```
The orchestration order and the revision loop are unchanged. Each `run_agent` call becomes: build message → validate against wire schema → call model with schema → validate reply → log.

## 6. Acceptance criteria
- A1 Across 5 replayed past requests (taken from `tests/live_runs/run_*.json`), **0** JSON-parse failures and **0** `finish_reason=length` truncations.
- A2 100% of dossier findings in the replayed runs that reach Draft have a `source_url`.
- A3 A draft deliberately seeded with a `TODO` is blocked by code even when the LLM scores it >= 80.
- A4 Every wire used in the pipeline validates its sample message against its own schema in a test.
- A5 Run logs include `schema_enforced`, `validation_retries`, `finish_reason`, and deterministic-check results.
- A6 Existing behavior preserved: 80 threshold, 3-cycle cap, escalation path, deliverable + run-log output.

## 7. Risks
| Risk | Mitigation |
|------|------------|
| Qwen fallback may not support strict json_schema | Phase 0 spike; R1.2 fallback path |
| Search adds latency/cost | Cap tool calls (R2.1); skip Research when Intake says `needs_research: false` |
| Keyword coverage check gives false failures | Non-critical severity; only the placeholder check is critical |
| Wire changes ripple to agent prompts | Update `tools.json` in the same change; run all replays |

## 8. Delivery phases
- **Phase 0 — Spikes (small, throwaway):** confirm json_schema support on `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`; confirm the chosen search option works from the harness.
- **Phase 1 — this spec:** G1-G5.
- **Phase 2 — Evals and tracing:** golden brief set, rubric scoring per run, regression report.
- **Phase 3 — Model routing:** cheap model for Intake/Dispatch; OpenRouter provider support with cross-provider fallback.
- **Phase 4 — Dynamic routing and durability:** Intake chooses stages per request; checkpoint/resume of runs.

## 9. Open questions
- **Q1 Dependencies:** the harness is stdlib-only. Add `jsonschema` (recommended, small and standard) or hand-write a minimal validator?
- **Q2 Search provider:** use Groq's built-in browser search on gpt-oss (no new key, to be confirmed in the spike) or an external API such as Tavily/Brave (new key in `.env`)?
- **Q3 Deterministic length tolerance:** ±15% acceptable?
