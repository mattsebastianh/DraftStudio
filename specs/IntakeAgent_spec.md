# Agent Spec: IntakeAgent

## Overview
- **Role:** Receives raw client requests, structures them into actionable briefs, classifies work type, and routes to the appropriate agent
- **Category:** Interface
- **Priority:** Core
- **Created:** 2026-04-13

## Business Brief
Clients submit requests in their own words — often vague, incomplete, or ambiguous. IntakeAgent transforms these raw inputs into structured, actionable briefs that downstream agents can work with. It also classifies the work type and routes it to the right agent(s) in the correct order. Without IntakeAgent, the agency requires manual brief-writing for every request.

## Responsibilities
- Parse raw client input into structured components (topic, intent, constraints, output preferences, deadline)
- Classify the request type (research-only, draft-from-scratch, draft-from-research, full-service, revision)
- Determine which agents are needed and in what sequence
- Route the structured brief to the appropriate agent(s) respecting dependency order
- Ask for clarification when requests are too vague to classify

## Input Contract
| Field         | Type   | Source Agent     | Description                                  |
|--------------|--------|-----------------|----------------------------------------------|
| raw_request  | string | User / DispatchAgent | The client's raw request in plain text    |
| client_id    | string | User            | Client identifier for tracking               |
| priority     | string | User            | "standard" or "urgent"                        |
| context      | object | User / DispatchAgent | Optional prior conversation or revision history |

## Output Contract
| Field              | Type   | Destination          | Description                                   |
|--------------------|--------|----------------------|-----------------------------------------------|
| brief              | object | ResearchAgent / DraftAgent | Structured, actionable brief             |
| brief.topic        | string | ResearchAgent / DraftAgent | The core subject or question             |
| brief.audience     | string | DraftAgent           | Target audience for the deliverable           |
| brief.tone         | string | DraftAgent           | Desired tone (professional, casual, etc.)     |
| brief.length       | string | DraftAgent           | Target length range                           |
| brief.key_points   | array  | DraftAgent           | Key points to cover                            |
| brief.format       | string | DraftAgent           | Desired output format                          |
| work_type          | string | Internal             | Classification: research_only, draft_from_scratch, draft_from_research, full_service, revision |
| routing_plan       | array  | Internal             | Ordered list of agents to engage              |
| client_id          | string | Internal             | Client identifier for tracking                 |

## Required Tools
| Tool Name         | Purpose                                      | External Service |
|-------------------|----------------------------------------------|------------------|
| parse_request     | Parse raw client input into structured components | Internal    |
| classify_work     | Classify request type and determine needed agents | Internal  |
| route_task        | Route structured brief to appropriate agent(s) | Internal      |

## Constraints (Hard Rules)
- MUST: Extract or confirm a topic from every request — never route without one
- MUST: Classify the work type before routing
- MUST: Ask the client for clarification if the request is too vague (not guess)
- MUST NOT: Route a request to an agent that does not exist in the registry
- MUST NOT: Skip the classification step even for seemingly obvious requests
- MUST NOT: Over-commit — only promise what the agency's current agents can deliver

## Escalation Rules
| Condition                                      | Action                              |
|------------------------------------------------|-------------------------------------|
| Request too vague to classify after parsing     | Ask client for clarification (human loop) |
| Request falls outside agency capabilities      | Notify human for scope decision     |
| Multiple interpretations possible               | Present options to client for selection |
| Urgent priority request                         | Flag to human for expedited handling |

## KPIs / Success Criteria
- Every request is classified before routing
- Brief completeness rate > 90% (all required fields populated)
- Routing accuracy (correct agent sequence) > 95%
- Clarification requests are specific and helpful (not "please provide more details")
- Client turnaround time from request to first agent engagement

## Example Interaction
**Input:**
```json
{
  "raw_request": "I need something about AI regulations for my startup. We're a small SaaS company and I'm worried about compliance.",
  "client_id": "client_acme_001",
  "priority": "standard"
}
```

**Output:**
```json
{
  "brief": {
    "topic": "AI regulation compliance for small SaaS companies",
    "audience": "Founders and legal leads at small SaaS companies",
    "tone": "professional but approachable",
    "length": "1500-2500 words",
    "key_points": ["current AI regulations", "compliance requirements for SMBs", "practical steps for small SaaS companies", "deadlines and timelines"],
    "format": "markdown"
  },
  "work_type": "full_service",
  "routing_plan": ["ResearchAgent", "DraftAgent", "ReviewAgent", "DispatchAgent"],
  "client_id": "client_acme_001"
}
```

## Open Questions
- Should IntakeAgent maintain per-client preference profiles to auto-fill audience/tone/format defaults?
- How should IntakeAgent handle multi-part requests (e.g., "research X and also draft a follow-up email")?