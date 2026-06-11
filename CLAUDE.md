# DraftStudio — Agentic AI Agency

## Project Goal
Build a holistic ecosystem of AI Agents that act as skilled digital workers.
Each agent holds a specific, non-overlapping role within the agency.
All agents are built with claude-code, powered by open-weight models served on Groq's fast inference platform.

## Primary Model
- **Llama 3.3 70B Versatile** (`llama-3.3-70b-versatile`, Groq API) — default for all agent calls
- Fallback: `openai/gpt-oss-120b` — used automatically when the primary model's daily token quota is exhausted
- Model IDs are set in `.env` (`GROQ_PRIMARY_MODEL`, `GROQ_FALLBACK_MODEL`) — change them there, not in configs

## Drafts: Always Use the Live Pipeline
- When the user asks for a new written deliverable (memo, email, article, proposal, brief, guide, etc.), or asks to revise/review/redo an existing one, do NOT draft the content yourself — run the agent pipeline instead of calling individual agents manually.
- Invoke: `python3 harness/run_pipeline.py "<raw client request>"`, redirecting output to a file outside the session tmp dir (e.g. `/tmp/pipeline_run.log`) and running it in the background.
- Pass the user's request (including any hard requirements/constraints) verbatim as the single argument — IntakeAgent classifies it and routes it through Research/Draft/Review/Dispatch automatically, including the revision loop and 3-cycle escalation.
- For a revision/review request on prior output, phrase the argument as a request describing the desired changes plus enough context (title/topic) for IntakeAgent to route it correctly.
- After the run completes, report: the run log (`tests/live_runs/run_*.json`), the review score/status, and the deliverable path (`deliverables/*.md`) — and surface the deliverable content to the user.
- If escalation triggers (3 revision cycles exhausted, score still <80), report this to the user instead of silently delivering a sub-threshold draft.

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
