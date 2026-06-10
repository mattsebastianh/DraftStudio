---
description: Audit an agent's design for safety, completeness, clarity, and agentic risks. Produces a structured review report.
user-invocable: true
context: fork
---

# Skill: /agent-review

## Purpose
Perform a structured design audit on an agent before it is promoted from `draft` to `active`.
Identifies risks, gaps, and improvements across safety, clarity, and capability dimensions.

## Steps

1. **Identify the agent**
   If not provided, ask: "Which agent should I review?"

2. **Read all agent files**
   - `specs/<AgentName>_spec.md`
   - `agents/<AgentName>/agent.md`
   - `agents/<AgentName>/system_prompt.txt`
   - `agents/<AgentName>/tools.json`
   - Any wires in `wires/` referencing this agent

3. **Run the audit across 5 dimensions**

   ### Dimension 1: Role Clarity (score /10)
   - Is the role unambiguous?
   - Could the role be confused with another agent's responsibility?
   - Is the goal statement measurable or observable?

   ### Dimension 2: System Prompt Quality (score /10)
   - Is it under 500 tokens?
   - Written in second person?
   - Does it include: role, goal, output format, at least one constraint?
   - Is there anything that could cause hallucination or goal drift?
   - Are there prompt injection risks (e.g., unchecked user input reflected back)?

   ### Dimension 3: Tool Safety (score /10)
   - Are all listed tools actually implemented/available?
   - Do any tools have destructive side-effects without a confirmation gate?
   - Are tool parameters validated (types, required fields)?
   - Is there a tool that could be misused if the agent misinterprets instructions?

   ### Dimension 4: Escalation & Failure Handling (score /10)
   - Is there at least one escalation rule?
   - Is the escalation target defined (agent name or "human")?
   - What happens if ALL escalation targets are unavailable?
   - Is there a maximum loop/retry limit to prevent infinite loops?

   ### Dimension 5: Inter-Agent Compatibility (score /10)
   - Does the output contract match the input contract of its downstream agent(s)?
   - Are all wires properly defined?
   - Could this agent deadlock with another agent?

4. **Write the review report**
   Create `reviews/<AgentName>_review.md`:

   ```markdown
   # Agent Review: <AgentName>
   **Date:** <YYYY-MM-DD>
   **Reviewer:** claude-code (/agent-review skill)
   **Status:** [PASS | CONDITIONAL PASS | FAIL]

   ## Scores
   | Dimension               | Score | Notes                  |
   |------------------------|-------|------------------------|
   | Role Clarity            | X/10  | ...                    |
   | System Prompt Quality   | X/10  | ...                    |
   | Tool Safety             | X/10  | ...                    |
   | Escalation Handling     | X/10  | ...                    |
   | Inter-Agent Compat.     | X/10  | ...                    |
   | **Overall**             | X/50  |                        |

   ## Findings
   ### 🔴 Critical (must fix before deployment)
   - Finding description

   ### 🟠 High (fix before marking active)
   - Finding description

   ### 🟡 Medium (fix in next iteration)
   - Finding description

   ### 🟢 Low / Suggestions
   - Finding description

   ## Recommendation
   <PASS | FIX REQUIRED | DO NOT DEPLOY>
   <Reasoning>
   ```

5. **If PASS or CONDITIONAL PASS**
   Update `agents/registry.yaml` status recommendation accordingly.

6. **Confirm**
   Report the review file path and overall status.
