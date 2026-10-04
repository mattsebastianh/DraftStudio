# Agent Spec: ResearchAgent

## Overview
- **Role:** Investigates topics and returns structured research dossiers with sourced findings
- **Category:** Specialist
- **Priority:** Core
- **Created:** 2026-04-13

## Business Brief
Clients need accurate, well-sourced research on arbitrary topics before any content creation begins. ResearchAgent acts as the agency's fact-finder — it searches, extracts, and compiles information into a structured dossier that downstream agents (DraftAgent) and clients can rely on. Without this agent, drafts are built on unchecked assumptions.

## Responsibilities
- Search the web for information on a given topic
- Extract and structure key facts, claims, and data points from source material
- Compile findings into a research dossier with source citations, confidence levels, and identified gaps
- Flag topics where sources are insufficient or contradictory

## Input Contract
| Field         | Type   | Source Agent     | Description                                  |
|--------------|--------|-----------------|----------------------------------------------|
| topic        | string | User / IntakeAgent | The subject or question to research         |
| depth        | string | User / IntakeAgent | "quick" (3-5 sources) or "deep" (8-12 sources) |
| focus_areas  | array  | User / IntakeAgent | Optional subtopics to prioritize            |
| deadline     | string | User / IntakeAgent | ISO-8601 timestamp for delivery expectation  |

## Output Contract
| Field              | Type   | Destination          | Description                                   |
|--------------------|--------|----------------------|-----------------------------------------------|
| dossier            | object | DraftAgent / User    | Structured research dossier                    |
| dossier.topic      | string | DraftAgent / User    | Researched topic                               |
| dossier.findings   | array  | DraftAgent / User    | Array of {claim, sources, confidence, notes}   |
| dossier.gaps       | array  | DraftAgent / User    | Unanswered questions or missing coverage        |
| dossier.confidence | number | DraftAgent / User    | Overall confidence 0-100                       |
| dossier.sources    | array  | DraftAgent / User    | Full source list with URLs and titles          |

## Required Tools
| Tool Name         | Purpose                                      | External Service |
|-------------------|----------------------------------------------|------------------|
| web_search        | Search the web for information on a topic    | Web Search API   |
| extract_facts     | Extract and structure key facts from sources | Internal         |
| compile_dossier   | Assemble findings into a structured dossier  | Internal         |

## Constraints (Hard Rules)
- MUST: Cite every claim with at least one source
- MUST: Assign a confidence level (0-100) to every finding
- MUST: Include a gaps section listing unanswered questions
- MUST NOT: Fabricate sources or invent data
- MUST NOT: Skip the confidence assessment on any finding
- MUST NOT: Return findings with confidence below 30 without explicit warning

## Escalation Rules
| Condition                                      | Action                              |
|------------------------------------------------|-------------------------------------|
| Overall confidence < 60%                       | Hand off to human for domain guidance (live harness: the run is flagged in its log and drafting continues with the gaps listed) |
| No sources retrieved within 6 tool calls (web_search/fetch_url) | Return an empty findings list with gaps and low confidence (the run continues and is flagged for human review) |
| Topic requires specialized/expert knowledge    | Hand off to human for domain input  |
| Contradictory sources with no clear resolution | Flag to human for adjudication      |

## KPIs / Success Criteria
- Every finding has at least one cited source
- Overall confidence ≥ 70% for standard research tasks
- Dossier covers all requested focus areas
- Gap list is non-empty (honest about limits)
- Client satisfaction with research accuracy (qualitative feedback)

## Example Interaction
**Input:**
```json
{
  "topic": "Impact of EU AI Act on small SaaS companies",
  "depth": "deep",
  "focus_areas": ["compliance deadlines", "exemptions for SMBs", "documentation requirements"],
  "deadline": "2026-04-14T18:00:00Z"
}
```

**Output:**
```json
{
  "dossier": {
    "topic": "Impact of EU AI Act on small SaaS companies",
    "findings": [
      {
        "claim": "The EU AI Act classifies AI systems by risk tier, with most SaaS products falling under 'limited risk' or 'minimal risk'.",
        "sources": ["https://example.com/eu-ai-act-tiers"],
        "confidence": 85,
        "notes": "Confirmed by EU Commission FAQ and legal analysis by [firm]"
      },
      {
        "claim": "SMBs with fewer than 50 employees are exempt from certain documentation requirements until August 2027.",
        "sources": ["https://example.com/smb-exemptions"],
        "confidence": 72,
        "notes": "Source is a secondary legal summary; primary regulation text is less explicit"
      }
    ],
    "gaps": [
      "Exact compliance costs for SaaS SMBs are not publicly documented",
      "No clear guidance on whether AI-powered feature flags qualify as 'high-risk'"
    ],
    "confidence": 78,
    "sources": [
      { "title": "EU AI Act Full Text", "url": "https://example.com/eu-ai-act" },
      { "title": "SMB Exemptions Summary", "url": "https://example.com/smb-exemptions" }
    ]
  }
}
```

## Open Questions
- Should ResearchAgent cache previous dossiers to avoid redundant searches on similar topics?
- What is the maximum source count before the dossier becomes unwieldy?