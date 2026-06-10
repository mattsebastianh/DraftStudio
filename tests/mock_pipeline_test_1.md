# Mock Test 1: Full Pipeline Integration Test

**Date:** 2026-04-16
**Type:** Full pipeline mock (simple stub)
**Purpose:** Verify agent integration without live model execution

---

## Stub Request

**Client input:** "Write a short blog post about productivity."

---

## Step 1 — IntakeAgent

**Tool:** `parse_request`
**Input:** `{ raw_request: "Write a short blog post about productivity." }`

**Output:**
```json
{
  "topic": "productivity",
  "intent": "blog_post",
  "needs_research": true,
  "needs_drafting": true,
  "constraints": {}
}
```

**Tool:** `classify_work`
**Input:** `{ parsed_request }`
**Output:** `{ work_type: "full_service", routing_plan: ["ResearchAgent", "DraftAgent", "ReviewAgent", "DispatchAgent"] }`

**Tool:** `send_to_ResearchAgent`
**Input:** `{ topic: "productivity", depth: "quick", focus_areas: [] }`
**Output:** → ResearchAgent queued

**Tool:** `send_to_DraftAgent`
**Input:** `{ brief: { topic: "productivity", audience: "general", tone: "conversational", length: "short", key_points: [], format: "plain_text" } }`
**Output:** → DraftAgent queued

---

## Step 2 — ResearchAgent

**Tool:** `receive_from_IntakeAgent`
**Input:** `{ topic: "productivity", depth: "quick", focus_areas: [] }`

**Mock output:** Simple placeholder dossier (no live web search)

```json
{
  "dossier": {
    "topic": "productivity",
    "findings": [
      { "claim": "Time blocking increases focus", "sources": [], "confidence": 70 },
      { "claim": "Short breaks improve output", "sources": [], "confidence": 65 }
    ],
    "gaps": [],
    "confidence": 67,
    "sources": []
  }
}
```

**Tool:** `send_to_DraftAgent`
**Input:** `{ dossier }`
**Output:** → DraftAgent

---

## Step 3 — DraftAgent

**Tool:** `receive_from_IntakeAgent`
**Input:** `{ brief: { topic: "productivity", audience: "general", tone: "conversational", length: "short", format: "plain_text" } }`

**Tool:** `receive_from_ResearchAgent`
**Input:** `{ dossier }`

**Tool:** `parse_brief` → requirements object

**Tool:** `outline_content`
**Input:** `{ requirements }`
**Output:** `{ outline: "Intro → 3 tips → Conclusion" }`

**Tool:** `draft_deliverable`
**Input:** `{ outline, revision_notes: [] }`
**Output:**
```json
{
  "draft": {
    "title": "5 Tips to Boost Your Productivity",
    "content": "Draft content here...",
    "unsupported": [],
    "word_count": 320
  }
}
```

**Tool:** `format_output`
**Input:** `{ draft_content, format: "plain_text" }`
**Output:** `{ formatted_draft }`

**Tool:** `send_to_ReviewAgent`
**Input:** `{ draft, brief, revision_round: 0 }`
**Output:** → ReviewAgent

---

## Step 4 — ReviewAgent (Round 0)

**Tool:** `receive_from_DraftAgent`
**Input:** `{ draft, brief, revision_round: 0 }`

**Tool:** `check_requirements`
**Output:** `{ results: [{ requirement: "short length", passed: true }] }`

**Tool:** `assess_quality`
**Output:** `{ score: 75 }`

**Tool:** `flag_issues`
**Input:** `{ quality_score: 75 }`
**Output:** `{ issues: [] }` — below 80 threshold but no critical issues to flag

**Decision:** score 75 < 80 → revision required

**Tool:** `send_to_DraftAgent`
**Input:** `{ draft_title, issues: [], revision_round: 1 }`
**Output:** → DraftAgent (revision loop)

---

## Step 5 — DraftAgent (Revision 1)

**Tool:** `receive_from_ReviewAgent`
**Input:** `{ draft_title, issues: [], revision_round: 1 }`

**Tool:** `draft_deliverable`
**Input:** `{ outline, revision_notes: [] }`
**Output:** `{ draft: { title: "...", content: "...", word_count: 350 } }`

**Tool:** `send_to_ReviewAgent`
**Input:** `{ draft, brief, revision_round: 1 }`
**Output:** → ReviewAgent

---

## Step 6 — ReviewAgent (Round 1)

**Tool:** `receive_from_DraftAgent`
**Input:** `{ draft, brief, revision_round: 1 }`

**Tool:** `check_requirements` → all pass
**Tool:** `assess_quality` → score: 82

**Decision:** score 82 ≥ 80 → approved

**Tool:** `send_to_DispatchAgent`
**Input:** `{ draft, review_summary: { score: 82, revision_rounds: 1 } }`
**Output:** → DispatchAgent

---

## Step 7 — DispatchAgent

**Tool:** `receive_from_ReviewAgent`
**Input:** `{ draft, review_summary, client_id: "stub_client" }`

**Tool:** `package_deliverable`
**Input:** `{ draft, review_status: "approved" }`
**Output:** `{ packaged_draft }`

**Tool:** `attach_context`
**Output:** `{ enriched_package }`

**Tool:** `confirm_delivery`
**Input:** `{ package, client_id: "stub_client" }`
**Output:** `{ delivery_record: { status: "delivered", timestamp: "2026-04-16" } }`

---

## Wire Summary

| Wire | Status |
|------|--------|
| IntakeAgent → ResearchAgent | ✅ sent, ✅ received |
| IntakeAgent → DraftAgent | ✅ sent, ✅ received |
| ResearchAgent → DraftAgent | ✅ dossier delivered |
| DraftAgent → ReviewAgent | ✅ draft submitted |
| ReviewAgent → DraftAgent | ✅ revision triggered |
| DraftAgent → ReviewAgent (r2) | ✅ revised draft |
| ReviewAgent → DispatchAgent | ✅ approved draft |
| DispatchAgent | ✅ packaged + delivered |

**Total agents visited:** 5/5
**Total wires used:** 8/9 (ReviewAgent→ResearchAgent fact-check not triggered)
**Revision cycles:** 1 (within 3-max limit)
**Final quality score:** 82 ≥ 80 threshold ✅

---

## Verdict

**PASS** — stub request completed full pipeline. All receive/send tools fired in correct sequence. Quality gate enforced at threshold 80. Revision loop triggered and resolved in 1 cycle.