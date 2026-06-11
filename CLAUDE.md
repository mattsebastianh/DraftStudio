# DraftStudio — Agentic AI Agency

## Project Goal
Build a holistic ecosystem of AI Agents that act as skilled digital workers.
Each agent holds a specific, non-overlapping role within the agency.
All agents are built with claude-code, powered by open-weight models served on Groq's fast inference platform.

## Primary Model
- **Llama 3.3 70B Versatile** (`llama-3.3-70b-versatile`, Groq API) — default for all agent calls
- Fallback: `openai/gpt-oss-120b` — used automatically when the primary model's daily token quota is exhausted
- Model IDs are set in `.env` (`GROQ_PRIMARY_MODEL`, `GROQ_FALLBACK_MODEL`) — change them there, not in configs

## Project Stack
- Runtime: claude-code + Groq-served models (OpenAI-compatible endpoint at `GROQ_BASE_URL`)
- Secrets: `.env` file (gitignored) — see `.env.example` for the template
- Agent format: Markdown spec + JSON tool definitions + plain-text system prompt
- Orchestration: Agent registry in `agents/registry.yaml`
- Inter-agent contracts: `wires/` directory
- Specifications: `specs/` directory
- Audit reports: `reviews/` directory
- Session handoffs: `handoffs/` directory

## Directory Layout
```
agents/          ← One subdirectory per agent role
wires/           ← Inter-agent communication contracts
specs/           ← Agent specs written before scaffolding
reviews/         ← Audit reports from /agent-review
handoffs/        ← Session export dumps from /context-dump
```

## Conventions
- **Spec-first:** Always run `/spec-agent` BEFORE `/new-agent`. Never scaffold without a spec.
- Agent names use PascalCase (e.g., ResearchAgent, OnboardingAgent)
- All file names use snake_case
- Every agent must define: Role, Goal, Backstory, Tools, Constraints, Escalation rules
- Every wire must define: trigger event, message schema, failure handling

## Live Pipeline Harness — When to Run It Automatically
Run `harness/run_pipeline.py` (no need to ask first) whenever a user asks something like:
- "run/test the pipeline", "live-test this request", "try this through the agents"
- "re-run the [cap-vs-structure / revision-loop / etc.] trap"
- to verify a change to an agent, wire, or the harness itself with real model output

### How to invoke
Always redirect to a file outside the session tmp dir and run in the background — direct output capture has been unreliable for long runs:
```
python3 harness/run_pipeline.py "<client request text>" > /tmp/pipeline_run.log 2>&1
```
Then use Monitor (or tail) on `/tmp/pipeline_run.log`, watching for `Step`, `done`, `approved`, `ESCALATION`, `HTTP`, `Run log`. TPM `HTTP 429` lines with an automatic retry are normal, not failures.

### After a run completes
- Run log: `tests/live_runs/run_<id>.json` — check each step's `model` (did fallback trigger?), the final `review.score`, and `escalated`/`round_num` for revision-loop activity
- Deliverable: `deliverables/<slug>.md`
- Bad JSON replies are saved to `tests/live_runs/bad_reply_<Agent>_<ts>.txt` for diagnosis
- Log every run to Notion under "Pipeline Tests" (see `.claude/memory/keep-notion-updated.md`)

### Model behavior
- `GROQ_PRIMARY_MODEL` (default `llama-3.3-70b-versatile`) is used first; on a daily-quota (TPD) 429 the harness auto-falls-back to `GROQ_FALLBACK_MODEL` and records `fallback_model_used` in the run log

## Available Skills (Slash Commands)
| Command          | Purpose                                        |
|------------------|------------------------------------------------|
| `/spec-agent`    | Convert a business brief into a structured agent spec |
| `/new-agent`     | Scaffold agent files from an existing spec     |
| `/agent-wire`    | Define inter-agent communication contract      |
| `/agent-review`  | Audit an agent for safety and completeness     |
| `/context-dump`  | Export session as a structured handoff doc     |

## Persistent Memory
- Project memory lives in `.claude/memory/` (project-local, committed) — NOT in the user-level `~/.claude/projects/<slug>/memory/` store
- At session start, read `.claude/memory/MEMORY.md` for the index, then recall individual memory files as needed
- Write all new memories to `.claude/memory/` and add an index line to its MEMORY.md; never write project memories to the user-level store

# Key Rules for Claude
- Never hardcode API keys, tokens, or secrets in any file — always reference environment variables loaded from `.env`
- Never commit `.env`; keep `.env.example` updated whenever a new variable is added
- Never scaffold an agent without a spec in `specs/`
- Never skip the escalation/fallback path in any agent
- When modifying a wire, update BOTH agent's tool definitions
- After any agent review, address all Critical and High severity findings before proceeding
- Prefer small, focused agents over large multi-role agents
