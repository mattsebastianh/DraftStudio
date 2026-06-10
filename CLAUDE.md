# JournilabAgents — Agentic AI Agency

## Project Goal
Build a holistic ecosystem of AI Agents that act as skilled digital workers.
Each agent holds a specific, non-overlapping role within the agency.
All agents are built with claude-code, powered by ollama cloud-executed open-weight models.

## Primary Model
- **GLM-5.1** (ollama cloud) — flagship agentic engineering model, SWE-Bench Pro SOTA
- Fallback: minimax-m2.7 (1M context, orchestration tasks)

## Project Stack
- Runtime: claude-code + ollama cloud models
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

## Key Rules for Claude
- Never scaffold an agent without a spec in `specs/`
- Never skip the escalation/fallback path in any agent
- When modifying a wire, update BOTH agent's tool definitions
- After any agent review, address all Critical and High severity findings before proceeding
- Prefer small, focused agents over large multi-role agents
