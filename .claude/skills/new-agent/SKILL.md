---
description: Scaffold a complete AI agent from an existing spec. Creates all required files for a new agent role in the JournilabAgents ecosystem.
user-invocable: true
---

# Skill: /new-agent

## Purpose
Scaffold a fully structured AI agent from a spec file in `specs/`.
Never run this skill without a corresponding spec — always run `/spec-agent` first.

## Steps

1. **Verify spec exists**
   - Check `specs/<AgentName>_spec.md` exists
   - If not, stop and tell the user to run `/spec-agent` first

2. **Create agent directory structure**
   ```
   agents/<AgentName>/
   ├── agent.md          ← Role definition & metadata
   ├── system_prompt.txt ← Deployable system prompt (≤500 tokens)
   └── tools.json        ← Tool definitions in JSON format
   ```

3. **Write `agent.md`** with:
   - `Role:` — One-sentence job title
   - `Goal:` — The primary objective this agent optimizes for
   - `Backstory:` — Context that gives the agent its "personality" and expertise framing
   - `Tools:` — Bulleted list of tools it can use (must match `tools.json`)
   - `Constraints:` — Hard rules the agent must never break
   - `Escalation:` — When and how to hand off to another agent or human
   - `Upstream:` — Which agents send tasks to this agent
   - `Downstream:` — Which agents receive output from this agent

4. **Write `system_prompt.txt`** — A production-ready system prompt:
   - Concise, under 500 tokens
   - Written in second person ("You are...")
   - Includes role, goal, key constraints, and output format
   - Does NOT include internal metadata (backstory, wiring) — that's for `agent.md`

5. **Write `tools.json`** — JSON array of tool definitions:
   ```json
   [
     {
       "name": "tool_name",
       "description": "What this tool does",
       "parameters": {
         "type": "object",
         "properties": {
           "param1": { "type": "string", "description": "..." }
         },
         "required": ["param1"]
       }
     }
   ]
   ```

6. **Register in `agents/registry.yaml`**
   Append a new entry:
   ```yaml
   - name: <AgentName>
     role: <one-line role>
     spec: specs/<AgentName>_spec.md
     system_prompt: agents/<AgentName>/system_prompt.txt
     tools: agents/<AgentName>/tools.json
     status: draft
     created: <YYYY-MM-DD>
   ```

7. **Confirm completion**
   Report all created files and the agent's registered status.
