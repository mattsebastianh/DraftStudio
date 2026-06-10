# Plan: Build DraftStudio Digital Worker Agency

## Context
DraftStudio is an agentic AI agency building a 5-agent digital worker ecosystem. All 5 agents are fully built, reviewed, pipeline-tested, and active as of 2026-04-14. Remaining work is v2 enhancements (see Next Steps).

## Agent Lineup

### 1. ResearchAgent
- **Role:** Investigates topics and returns structured research dossiers with sourced findings
- **Tools:** `web_search`, `extract_facts`, `compile_dossier`, `send_to_DraftAgent`
- **Escalation:** Insufficient sources (confidence <60%) → human for domain guidance

### 2. DraftAgent
- **Role:** Creates written deliverables from structured briefs and optional research inputs
- **Tools:** `parse_brief`, `outline_content`, `draft_deliverable`, `format_output`, `receive_from_ResearchAgent`, `send_to_ReviewAgent`, `receive_from_ReviewAgent`, `receive_from_IntakeAgent`
- **Escalation:** Ambiguous/contradictory brief → human for clarification; needs domain expertise → human

### 3. ReviewAgent
- **Role:** Evaluates deliverables against brief requirements and quality standards before client delivery
- **Tools:** `check_requirements`, `assess_quality`, `flag_issues`, `receive_from_DraftAgent`, `send_to_DraftAgent`, `send_to_DispatchAgent`
- **Escalation:** Quality below threshold after 3 revision cycles → human; can't verify facts → ResearchAgent fact-check

### 4. IntakeAgent
- **Role:** Receives raw client requests, structures them into actionable briefs, classifies work type, routes to the right agent
- **Tools:** `parse_request`, `classify_work`, `route_task`, `send_to_ResearchAgent`, `send_to_DraftAgent`, `receive_from_DispatchAgent`
- **Escalation:** Too vague to classify → ask client; outside capabilities → human scope decision

### 5. DispatchAgent
- **Role:** Packages approved deliverables for client delivery, attaches context, confirms handoff
- **Tools:** `package_deliverable`, `attach_context`, `confirm_delivery`, `receive_from_ReviewAgent`, `send_to_IntakeAgent`
- **Escalation:** Delivery fails → alert human; client revision → route to IntakeAgent as new request

## Wire Map

### Active wires (9 total, all built and verified ✅):
| Wire | From → To | Trigger |
|------|-----------|---------|
| `ResearchAgent_to_DraftAgent` | Research → Draft | Dossier complete |
| `DraftAgent_to_ReviewAgent` | Draft → Review | Draft complete |
| `ReviewAgent_to_DraftAgent` | Review → Draft | Quality issues found |
| `IntakeAgent_to_ResearchAgent` | Intake → Research | Research needed |
| `IntakeAgent_to_DraftAgent` | Intake → Draft | Draft-ready brief |
| `ReviewAgent_to_DispatchAgent` | Review → Dispatch | Deliverable approved |
| `DispatchAgent_to_IntakeAgent` | Dispatch → Intake | Client revision request |
| `ReviewAgent_to_ResearchAgent` | Review → Research | Fact-check needed |
| `DraftAgent_to_ResearchAgent` | Draft → Research | Mid-draft research escalation |

## End-to-End Workflow
```
Client → IntakeAgent → ResearchAgent → DraftAgent → ReviewAgent → DispatchAgent → Client
                                   ↑         ↓ (revision)       ↓
                                   └─────────┘         (revision request → IntakeAgent)
```

Shorter paths: research-only, draft-only, or direct standalone usage of any agent.

## Progress

| Agent | Spec | Scaffold | Wires | Review |
|-------|------|----------|-------|--------|
| ResearchAgent | ✅ | ✅ | ✅ | ✅ |
| DraftAgent | ✅ | ✅ | ✅ | ✅ |
| ReviewAgent | ✅ | ✅ | ✅ | ✅ |
| IntakeAgent | ✅ | ✅ | ✅ | ✅ |
| DispatchAgent | ✅ | ✅ | ✅ | ✅ |

## Status: COMPLETE ✅

All 5 agents reviewed (`reviews/<AgentName>_review.md`), all Critical/High findings fixed, all 9 wires built and verified, full pipeline test passed (15 issues found and fixed — `tests/pipeline_test_results.md`), all agents activated (status: active) on 2026-04-14.

## Key Design Decisions
- **Revision requests go through ReviewAgent → DraftAgent** (not direct) — ReviewAgent owns the quality gate
- **Client revision requests route through IntakeAgent** (not back to DraftAgent) — preserves traceability and ensures full QA pipeline on revisions
- **No separate PlannerAgent** — planning is absorbed into IntakeAgent's classify/route tools; split out later if needed
- **5 agents** — each does substantive, distinct work; fewer would collapse responsibilities, more would add insufficient standalone value

## Verification Checklist (per agent)
- [x] `agents/registry.yaml` has entry with correct paths (all 5)
- [x] `agents/<AgentName>/` has all 3 files: agent.md, system_prompt.txt, tools.json (all 5)
- [x] system_prompt.txt is under 500 tokens (verified during review)
- [x] tools.json valid JSON (verified during review)
- [x] Both agents' tools.json reflect every wire (all 9 wires verified, 2026-04-14)
- [x] After all reviews pass: test request traces through full pipeline (passed 2026-04-14)

## Next Steps (v2)
- Add `priority` field to IntakeAgent intake flow (urgent request handling)
- Add per-dimension quality scores to ReviewAgent (not just composite)
- Add `client_id` propagation through all send tools
- Multi-channel delivery support in DispatchAgent
- Live execution test with real model invocations via the Groq API
