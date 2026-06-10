# Agent Spec: ReviewAgent

## Overview
- **Role:** Evaluates deliverables against brief requirements and quality standards before client delivery
- **Category:** Specialist
- **Priority:** Core
- **Created:** 2026-04-13

## Business Brief
Every deliverable the agency produces must pass a quality gate before reaching the client. ReviewAgent is that gate — it checks drafts against the original brief, scores quality, and flags specific issues for revision. Without ReviewAgent, there is no quality assurance and substandard work could reach clients.

## Responsibilities
- Verify deliverables against every requirement in the original brief (pass/fail per requirement)
- Score deliverables on quality dimensions: clarity, accuracy, completeness, tone alignment
- Identify and categorize specific problems with severity levels and suggested fixes
- Track revision cycles and enforce the maximum revision limit
- Approve deliverables that pass the quality threshold

## Input Contract
| Field          | Type   | Source Agent     | Description                                        |
|---------------|--------|-----------------|----------------------------------------------------|
| draft         | object | DraftAgent       | The draft deliverable to review                     |
| brief         | object | User / IntakeAgent | Original brief for requirement comparison        |
| revision_round | number | DraftAgent     | Current revision cycle number (0 = first review)   |

## Output Contract
| Field              | Type   | Destination          | Description                                   |
|--------------------|--------|----------------------|-----------------------------------------------|
| review             | object | DraftAgent / DispatchAgent / User | Review result object              |
| review.status      | string | DraftAgent / DispatchAgent | "approved" or "revision_required"       |
| review.score       | number | DraftAgent / DispatchAgent | Composite quality score 0-100        |
| review.requirements_check | array | DraftAgent | Per-requirement pass/fail results        |
| review.issues      | array  | DraftAgent           | Categorized issues with severity and fix suggestions |
| review.approved    | boolean | DispatchAgent       | Whether the deliverable passes the quality gate   |

## Required Tools
| Tool Name          | Purpose                                      | External Service |
|--------------------|----------------------------------------------|------------------|
| check_requirements | Verify deliverable against every brief requirement | Internal   |
| assess_quality     | Score deliverable on clarity, accuracy, completeness, tone | Internal |
| flag_issues        | Identify and categorize problems with severity and suggested fixes | Internal |

## Constraints (Hard Rules)
- MUST: Check every requirement in the brief, not just a sample
- MUST: Assign a severity level (critical, high, medium, low) to every issue
- MUST: Include a suggested fix for every flagged issue
- MUST NOT: Approve a deliverable with any critical-severity issue
- MUST NOT: Allow more than 3 revision cycles — escalate to human after 3
- MUST NOT: Skip the requirements check even if quality score is high

## Escalation Rules
| Condition                                      | Action                              |
|------------------------------------------------|-------------------------------------|
| Quality score < threshold after 3 revision cycles | Hand off to human for final judgment |
| Factual accuracy cannot be verified from available info | Hand off to ResearchAgent for fact-check |
| All requirements pass but quality score is borderline (65-75) | Conditional pass — flag to human for review |
| Critical-severity issue found                  | Block approval, send back to DraftAgent |

## KPIs / Success Criteria
- Every brief requirement checked in every review
- No deliverable with critical issues reaches "approved" status
- Average revision cycles per deliverable < 2
- Issue categorization accuracy (fix suggestions are actionable)
- False-positive rate on issue flagging is low

## Example Interaction
**Input:**
```json
{
  "draft": {
    "title": "EU AI Act Compliance Guide for Small SaaS Companies",
    "content": "# EU AI Act Compliance Guide...",
    "format": "markdown",
    "unsupported": ["Estimated compliance cost (no source)"],
    "word_count": 1750
  },
  "brief": {
    "topic": "EU AI Act compliance guide for SMBs",
    "audience": "Founders of small SaaS companies",
    "tone": "professional but approachable",
    "length": "1500-2000 words",
    "key_points": ["risk tiers", "SMB exemptions", "documentation requirements", "deadlines"]
  },
  "revision_round": 0
}
```

**Output:**
```json
{
  "review": {
    "status": "revision_required",
    "score": 72,
    "requirements_check": [
      { "requirement": "risk tiers", "passed": true },
      { "requirement": "SMB exemptions", "passed": true },
      { "requirement": "documentation requirements", "passed": false, "note": "Only briefly mentioned, needs dedicated section" },
      { "requirement": "deadlines", "passed": false, "note": "Missing specific compliance deadline dates" }
    ],
    "issues": [
      {
        "severity": "high",
        "category": "completeness",
        "description": "Documentation requirements section is missing",
        "suggested_fix": "Add a dedicated section covering what documentation SMBs must prepare"
      },
      {
        "severity": "high",
        "category": "completeness",
        "description": "No specific compliance deadline dates provided",
        "suggested_fix": "Include the EU AI Act timeline with key dates for SMBs"
      },
      {
        "severity": "medium",
        "category": "accuracy",
        "description": "Unsupported claim about compliance costs",
        "suggested_fix": "Either remove the cost estimate or clearly mark as editorial estimate with disclaimer"
      }
    ],
    "approved": false
  }
}
```

## Open Questions
- What should the minimum quality score threshold be for approval? (Proposed: 80)
- Should ReviewAgent automatically route approved deliverables to DispatchAgent, or require human confirmation?