# Agent Spec: DispatchAgent

## Overview
- **Role:** Packages approved deliverables for client delivery, attaches context, and confirms successful handoff
- **Category:** Interface
- **Priority:** Core
- **Created:** 2026-04-13

## Business Brief
After a deliverable passes the quality gate, it needs to be packaged, formatted per client preferences, and delivered with appropriate context (sources, revision notes, metadata). DispatchAgent handles this last mile and creates the feedback loop — routing client revision requests back to IntakeAgent as new intake items.

## Responsibilities
- Format the deliverable per client preferences (markdown, plain text, sectioned document)
- Attach supporting context: research sources consulted, revision history, agency metadata
- Record the delivery event and track client confirmation or feedback
- Route client revision requests back to IntakeAgent as new intake items (not directly to DraftAgent)

## Input Contract
| Field              | Type   | Source Agent     | Description                                   |
|--------------------|--------|-----------------|-----------------------------------------------|
| draft              | object | ReviewAgent     | The approved draft deliverable                 |
| review_summary     | object | ReviewAgent     | Review result summary (score, revision rounds)|
| client_preferences | object | User / IntakeAgent | Formatting and delivery preferences         |
| client_id          | string | User            | Client identifier for tracking                |

## Output Contract
| Field              | Type   | Destination          | Description                                   |
|--------------------|--------|----------------------|-----------------------------------------------|
| package            | object | User                 | The packaged deliverable ready for delivery   |
| package.content    | string | User                 | Final formatted content                        |
| package.format     | string | User                 | Format applied                                 |
| package.sources    | array  | User                 | Research sources consulted                     |
| package.revision_history | array | User             | Revision notes from ReviewAgent cycles         |
| package.metadata   | object | User                 | Agency metadata (date, agent pipeline, etc.)  |
| delivery_status    | string | Internal             | "delivered", "confirmed", "revision_requested" |

## Required Tools
| Tool Name           | Purpose                                      | External Service |
|---------------------|----------------------------------------------|------------------|
| package_deliverable | Format deliverable per client preferences and apply final formatting | Internal |
| attach_context      | Append research sources, revision history, and metadata to the package | Internal |
| confirm_delivery    | Record delivery event, track client confirmation, close work item | Internal |

## Constraints (Hard Rules)
- MUST: Include all research sources consulted in the package
- MUST: Include revision history showing what changed across review cycles
- MUST: Respect client formatting preferences
- MUST NOT: Deliver a package without an approved review status
- MUST NOT: Route revision requests directly to DraftAgent — always go through IntakeAgent
- MUST NOT: Alter the approved content during packaging (formatting only)

## Escalation Rules
| Condition                                      | Action                              |
|------------------------------------------------|-------------------------------------|
| Delivery fails or client unreachable           | Alert human account manager         |
| Client requests revision after delivery        | Route to IntakeAgent as new intake  |
| Package format mismatch with client preference | Retry with correct format           |

## KPIs / Success Criteria
- Every delivered package includes sources and revision history
- Client delivery confirmation rate > 95%
- Revision requests are correctly routed to IntakeAgent (not DraftAgent)
- No content alteration during packaging
- Delivery tracking is complete and accurate

## Example Interaction
**Input:**
```json
{
  "draft": {
    "title": "EU AI Act Compliance Guide for Small SaaS Companies",
    "content": "# EU AI Act Compliance Guide...",
    "format": "markdown"
  },
  "review_summary": {
    "score": 87,
    "revision_rounds": 1
  },
  "client_preferences": {
    "format": "markdown",
    "include_sources": true,
    "include_revision_history": true
  },
  "client_id": "client_acme_001"
}
```

**Output:**
```json
{
  "package": {
    "content": "# EU AI Act Compliance Guide for Small SaaS Companies\n\n...(full content)...",
    "format": "markdown",
    "sources": [
      { "title": "EU AI Act Full Text", "url": "https://example.com/eu-ai-act" }
    ],
    "revision_history": [
      { "round": 1, "issues_addressed": 2, "changes": "Added documentation section and compliance deadlines" }
    ],
    "metadata": {
      "agency": "DraftStudio",
      "pipeline": ["IntakeAgent", "ResearchAgent", "DraftAgent", "ReviewAgent", "DispatchAgent"],
      "delivered": "2026-04-13T15:30:00Z"
    }
  },
  "delivery_status": "delivered"
}
```

## Open Questions
- Should DispatchAgent support multiple delivery channels (email, API, file export)?
- How long should delivery tracking data be retained?