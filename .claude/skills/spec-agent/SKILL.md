---
description: Convert a plain-English business brief into a structured agent specification document. Always run this before /new-agent.
user-invocable: true
context: fork
---

# Skill: /spec-agent

## Purpose
Transform a business need or role description into a rigorous, structured agent spec.
This is the mandatory first step before any agent is scaffolded.

## Steps

1. **Elicit the brief**
   If no brief was provided, ask the user:
   - "What does this agent need to DO?" (primary responsibility)
   - "What does it receive as INPUT?"
   - "What does it produce as OUTPUT?"
   - "What should it NEVER do?" (constraints)

2. **Derive the spec** — Write `specs/<AgentName>_spec.md` with these sections:

   ```markdown
   # Agent Spec: <AgentName>

   ## Overview
   - **Role:** <one-line job title>
   - **Category:** [Orchestrator | Specialist | Interface | Monitor | Utility]
   - **Priority:** [Core | Secondary | Optional]
   - **Created:** <YYYY-MM-DD>

   ## Business Brief
   <Plain-English description of the business need this agent addresses.>

   ## Responsibilities
   - <Primary responsibility 1>
   - <Primary responsibility 2>
   - ...

   ## Input Contract
   | Field        | Type   | Source Agent     | Description          |
   |-------------|--------|-----------------|----------------------|
   | field_name  | string | AgentName / User | What this field is   |

   ## Output Contract
   | Field        | Type   | Destination      | Description          |
   |-------------|--------|-----------------|----------------------|
   | field_name  | string | AgentName / User | What this field is   |

   ## Required Tools
   | Tool Name        | Purpose                        | External Service |
   |-----------------|-------------------------------|-----------------|
   | tool_name        | What it does                  | API/service name |

   ## Constraints (Hard Rules)
   - MUST: <non-negotiable requirement>
   - MUST NOT: <forbidden behavior>

   ## Escalation Rules
   | Condition                    | Action                          |
   |-----------------------------|--------------------------------|
   | <trigger>                   | Hand off to <AgentName/Human>  |
   | Confidence < threshold      | Request human approval         |

   ## KPIs / Success Criteria
   - <How will we know this agent is working well?>

   ## Example Interaction
   **Input:**
   ```json
   { "example": "input payload" }
   ```
   **Output:**
   ```json
   { "example": "output payload" }
   ```

   ## Open Questions
   - <Anything unclear that needs resolution before scaffolding>
   ```

3. **Validate the spec**
   Check for:
   - [ ] Input and Output contracts are complete
   - [ ] At least one escalation rule exists
   - [ ] No overlapping responsibilities with already-existing agents in `agents/registry.yaml`
   - [ ] All required tools are realistic and implementable

4. **Confirm**
   Report the spec file path and list any open questions the user should resolve.
