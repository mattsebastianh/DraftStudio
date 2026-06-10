---
description: Export the current session as a structured handoff document. Use before ending a long session or switching models/agents.
user-invocable: true
disable-model-invocation: false
---

# Skill: /context-dump

## Purpose
Compress and export the current session's work into a portable handoff document.
Use this to:
- Hand off to a different model or claude-code session
- Create a checkpoint before a risky operation
- End a session cleanly with full context preserved

## Steps

1. **Collect session metadata**
   - Current date and time
   - Models used in this session
   - Working directory and project name

2. **Summarize what was accomplished**
   - What was the original goal?
   - What was built, written, or changed?
   - What decisions were made, and why?

3. **List all files created or modified**
   For each file:
   - Path (relative to project root)
   - One-line description of what it contains or what changed
   - Status: [COMPLETE | IN PROGRESS | BLOCKED]

4. **List open items**
   - What is unfinished?
   - What was explicitly deferred?
   - What is blocked and why?

5. **List next recommended actions**
   Ordered list of what should happen next, with enough context that a fresh session can pick up without re-reading prior conversation.

6. **Write the handoff document**
   Create `handoffs/<YYYY-MM-DD_HHMMSS>_handoff.md`:

   ```markdown
   # Session Handoff
   **Date:** <YYYY-MM-DD HH:MM:SS>
   **Project:** JournilabAgents
   **Model Used:** <model name>
   **Session Duration:** <estimated>

   ## Session Goal
   <What this session set out to accomplish>

   ## What Was Accomplished
   <Summary of completed work>

   ## Files Created / Modified
   | File Path                              | Status      | Notes                        |
   |---------------------------------------|-------------|------------------------------|
   | path/to/file.md                       | COMPLETE    | One-line description         |

   ## Key Decisions Made
   - **Decision:** <what was decided> — **Reason:** <why>

   ## Open Items
   | Item                          | Status   | Blocker (if any)             |
   |------------------------------|----------|------------------------------|
   | <task>                       | DEFERRED | <reason>                     |

   ## Recommended Next Actions
   1. <First action with full context>
   2. <Second action>
   3. ...

   ## Re-Hydration Prompt
   > Paste this into a new claude-code session to resume:
   >
   > "I'm continuing work on JournilabAgents. Please read CLAUDE.md and the
   > handoff document at handoffs/<filename>. Then proceed with: [NEXT ACTION 1]"
   ```

7. **Confirm**
   Report the handoff file path and the re-hydration prompt to paste in the next session.
