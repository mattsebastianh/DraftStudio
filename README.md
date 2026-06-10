# DraftStudio

**An autonomous content studio run by AI agents.**

DraftStudio is a five-agent digital worker ecosystem that takes raw client requests and turns them into researched, quality-gated written deliverables. Each agent holds a specific, non-overlapping role — like a staffed editorial studio that runs itself.

All agents are built with [claude-code](https://claude.com/claude-code) and powered by open-weight models served on [Groq](https://groq.com)'s fast inference platform.

## The Agent Lineup

| Agent | Role |
|-------|------|
| **IntakeAgent** | Parses raw client requests into structured briefs, classifies the work, routes it. Entry point for everything. |
| **ResearchAgent** | Investigates topics and returns structured, sourced research dossiers. |
| **DraftAgent** | Creates written deliverables from briefs + research. Can request mid-draft research. |
| **ReviewAgent** | Quality gate before delivery — scores drafts, requests revisions, approves at ≥ 80/100. |
| **DispatchAgent** | Packages approved content, attaches context, delivers to the client. |

## How Work Flows

```
Client → IntakeAgent → ResearchAgent → DraftAgent → ReviewAgent → DispatchAgent → Client
                                   ↑         ↓ (revision, max 3 cycles)
                                   └─────────┘
                       (client revision request → back through IntakeAgent)
```

The agents communicate over 9 verified **wires** — explicit contracts in `wires/` that define the trigger event, message schema, and failure handling for every hop. Key guarantees:

- **Quality gate:** nothing ships below a review score of 80/100
- **Bounded revisions:** max 3 revision cycles, then human escalation
- **Every agent has an escalation path** — ambiguity, low confidence, or failure always routes to a human, never silently drops

## Getting Started

### Prerequisites

- [claude-code](https://claude.com/claude-code) CLI
- A [Groq API key](https://console.groq.com/keys) (free tier works)

### Setup

```bash
git clone https://github.com/mattsebastianh/DraftStudio.git
cd DraftStudio
cp .env.example .env
# edit .env and paste in your real GROQ_API_KEY
```

`.env` is gitignored — real keys never leave your machine. The models are configured there too:

| Variable | Default | Purpose |
|----------|---------|---------|
| `GROQ_PRIMARY_MODEL` | `openai/gpt-oss-120b` | Flagship agentic reasoning model |
| `GROQ_FALLBACK_MODEL` | `llama-3.3-70b-versatile` | Cheap orchestration tasks |

Swap models by editing `.env` — nothing else references model IDs. Note the primary is a reasoning model: give it a generous `max_tokens` budget, since reasoning tokens count against it.

### Verify your connection

```bash
set -a && source .env && set +a
curl -s "$GROQ_BASE_URL/models" -H "Authorization: Bearer $GROQ_API_KEY"
```

You should get a JSON list of available models.

## Using the Studio

Open claude-code in the repo root. The studio is operated through five slash commands (project skills in `.claude/skills/`):

| Command | What it does |
|---------|--------------|
| `/spec-agent` | Convert a business brief into a structured agent spec (always run this first) |
| `/new-agent` | Scaffold a complete agent from an existing spec |
| `/agent-wire` | Define a communication contract between two agents |
| `/agent-review` | Audit an agent for safety, completeness, and agentic risks |
| `/context-dump` | Export the session as a structured handoff doc |

**The workflow is spec-first:** `/spec-agent` → `/new-agent` → `/agent-wire` → `/agent-review`. Never scaffold without a spec, and address all Critical/High review findings before activating an agent.

## Repository Layout

```
agents/          ← One subdirectory per agent (agent.md, system_prompt.txt, tools.json)
agents/registry.yaml  ← Central registry: status, paths, and wires for every agent
wires/           ← Inter-agent communication contracts (YAML)
specs/           ← Agent specs, written before scaffolding
reviews/         ← Audit reports from /agent-review
tests/           ← Pipeline test results
handoffs/        ← Session export dumps from /context-dump
deliverables/    ← Sample outputs produced by the pipeline
```

Every agent defines: Role, Goal, Backstory, Tools, Constraints, and Escalation rules. Tool definitions are JSON; system prompts are plain text and kept under 500 tokens.

## Status

All 5 agents are built, reviewed, pipeline-tested, and **active**. The full wire map (9 wires) passed static integration testing — see `tests/pipeline_test_results.md`.

Planned v2 work: priority handling at intake, per-dimension quality scores, `client_id` propagation, multi-channel delivery, and a live end-to-end execution test against the Groq API.

## Design Principles

- **Spec-first** — no agent exists without a written, reviewed specification
- **Small, focused agents** — each does substantive, distinct work; no mega-agents
- **Explicit contracts** — every inter-agent message has a schema and a failure path
- **Humans stay in the loop** — every agent has defined escalation rules
- **Secrets stay in `.env`** — no keys, tokens, or model IDs hardcoded anywhere
