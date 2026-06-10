# Mock Test 2: Practical Full-Service Request (All 9 Wires)

**Date:** 2026-06-10
**Type:** Full pipeline mock (practical scenario, simulated tool I/O — no live model execution)
**Purpose:** Exercise all 9 wires with a realistic client request, including the two paths not covered by Mock Test 1: `DraftAgent → ResearchAgent` (mid-draft research) and `DispatchAgent → IntakeAgent` (client revision request)

---

## Mock Request

**Client input:** "I need a guide on choosing a CRM for solo consultants — around 2,000 words, professional but friendly. My readers are independent consultants who hate bloated enterprise software. Compare a few real options with pricing."

---

## Step 1 — IntakeAgent

**Tool:** `parse_request`
**Input:** `{ raw_request: "I need a guide on choosing a CRM for solo consultants..." }`

**Output:**
```json
{
  "topic": "choosing a CRM for solo consultants",
  "intent": "buyer_guide",
  "needs_research": true,
  "needs_drafting": true,
  "constraints": {
    "length": "~2000 words",
    "tone": "professional but friendly",
    "audience": "independent consultants averse to enterprise software",
    "must_include": ["real product comparison", "pricing"]
  }
}
```

**Tool:** `classify_work`
**Output:** `{ work_type: "full_service", routing_plan: ["ResearchAgent", "DraftAgent", "ReviewAgent", "DispatchAgent"] }`

*Constraint check: topic confirmed, classification done before routing — no clarification needed (request is specific).*

**Tool:** `send_to_ResearchAgent` — wire `IntakeAgent_to_ResearchAgent`
**Input:** `{ topic: "CRM options for solo consultants", depth: "standard", focus_areas: ["lightweight CRMs", "pricing tiers", "solo-user workflows"] }`

**Tool:** `send_to_DraftAgent` — wire `IntakeAgent_to_DraftAgent`
**Input:**
```json
{
  "brief": {
    "topic": "How to choose a CRM as a solo consultant",
    "audience": "Independent consultants who dislike bloated enterprise software",
    "tone": "professional but friendly",
    "length": "1800-2200 words",
    "key_points": ["evaluation criteria", "comparison of real options", "pricing", "recommendation framework"],
    "format": "markdown"
  }
}
```

---

## Step 2 — ResearchAgent

**Tool:** `receive_from_IntakeAgent`

**Tool:** `web_search` ×3 (mock) → lightweight CRM landscape, pricing pages, user reviews
**Tool:** `extract_facts` → 11 claims extracted
**Tool:** `compile_dossier`

**Output:**
```json
{
  "dossier": {
    "topic": "CRM options for solo consultants",
    "findings": [
      { "claim": "HubSpot free tier covers contact management but pushes paid upgrades aggressively", "sources": ["hubspot.com/pricing", "review aggregate"], "confidence": 85 },
      { "claim": "Pipedrive Essential starts ~$14/seat/month, built around pipeline view", "sources": ["pipedrive.com/pricing"], "confidence": 90 },
      { "claim": "Notion/Airtable DIY CRMs are popular with solos but lack email sync", "sources": ["community forums"], "confidence": 72 },
      { "claim": "Less Annoying CRM is $15/user/month flat, targets exactly this segment", "sources": ["lessannoyingcrm.com"], "confidence": 88 }
    ],
    "gaps": ["Folk and Attio pricing not verified"],
    "confidence": 81,
    "sources": 9
  }
}
```

*Confidence 81 ≥ 60 escalation floor → no human escalation.*

**Tool:** `send_to_DraftAgent` — wire `ResearchAgent_to_DraftAgent`

---

## Step 3 — DraftAgent (initial draft + mid-draft research)

**Tool:** `receive_from_IntakeAgent` → brief
**Tool:** `receive_from_ResearchAgent` → dossier
**Tool:** `parse_brief` → requirements object
**Tool:** `outline_content`
**Output:** `{ outline: "Why solos need different CRMs → 5 evaluation criteria → Comparison (4 tools w/ pricing) → Decision framework → Conclusion" }`

**Mid-draft gap:** comparison section needs the unverified Folk/Attio pricing flagged in dossier `gaps`.

**Tool:** `send_to_ResearchAgent` — wire `DraftAgent_to_ResearchAgent` ⭐ *(not exercised in Mock Test 1)*
**Input:** `{ request_type: "mid_draft_gap", question: "Current entry pricing for Folk and Attio CRMs", context: "comparison table in progress" }`

**ResearchAgent →** `web_search` ×1 → `send_to_DraftAgent`:
```json
{ "findings": [
  { "claim": "Folk starts at $20/user/month (annual)", "confidence": 82 },
  { "claim": "Attio free tier for up to 3 seats, paid from $29/user/month", "confidence": 79 }
] }
```

**Tool:** `draft_deliverable`
**Output:** `{ draft: { title: "The Solo Consultant's Guide to Picking a CRM (Without the Bloat)", word_count: 2080, unsupported: [] } }`

**Tool:** `format_output` → markdown
**Tool:** `send_to_ReviewAgent` — wire `DraftAgent_to_ReviewAgent`
**Input:** `{ draft, brief, revision_round: 0 }`

---

## Step 4 — ReviewAgent (Round 0, with fact-check)

**Tool:** `receive_from_DraftAgent`

**Tool:** `check_requirements`
**Output:**
```json
{ "results": [
  { "requirement": "1800-2200 words", "passed": true },
  { "requirement": "professional but friendly tone", "passed": true },
  { "requirement": "real product comparison with pricing", "passed": true },
  { "requirement": "recommendation framework", "passed": false, "note": "framework section is a flat list, no decision logic" }
] }
```

**Fact-check trigger:** pricing claims are client-facing and time-sensitive.

**Tool:** `send_to_ResearchAgent` — wire `ReviewAgent_to_ResearchAgent` ⭐ *(not exercised in Mock Test 1)*
**Input:** `{ claims_to_verify: ["Pipedrive ~$14/seat/month", "Less Annoying CRM $15 flat", "Attio free tier 3 seats"] }`

**ResearchAgent →** verification result: `{ verified: 3, corrected: 0, confidence: 89 }` → returned to ReviewAgent

**Tool:** `assess_quality` → `{ score: 76 }`
**Tool:** `flag_issues`
**Output:** `{ issues: ["recommendation framework lacks decision logic", "conclusion restates intro instead of advising next step"] }`

**Decision:** 76 < 80 → revision required

**Tool:** `send_to_DraftAgent` — wire `ReviewAgent_to_DraftAgent`
**Input:** `{ issues, revision_round: 1 }`

---

## Step 5 — DraftAgent (Revision 1)

**Tool:** `receive_from_ReviewAgent`
**Tool:** `draft_deliverable` — framework rebuilt as if/then decision tree; conclusion now ends with a concrete 3-step action plan
**Output:** `{ draft: { word_count: 2140 } }`
**Tool:** `send_to_ReviewAgent` — `{ draft, brief, revision_round: 1 }`

---

## Step 6 — ReviewAgent (Round 1)

**Tool:** `check_requirements` → all 4 pass
**Tool:** `assess_quality` → `{ score: 86 }`

**Decision:** 86 ≥ 80 → **approved** (1 revision cycle, within 3-max limit)

**Tool:** `send_to_DispatchAgent` — wire `ReviewAgent_to_DispatchAgent`
**Input:** `{ draft, review_summary: { score: 86, revision_rounds: 1, fact_check: "passed" } }`

---

## Step 7 — DispatchAgent

**Tool:** `receive_from_ReviewAgent`
**Tool:** `package_deliverable` → `{ packaged_draft, review_status: "approved" }`
**Tool:** `attach_context` → adds research sources, revision history, quality score
**Tool:** `confirm_delivery`
**Output:** `{ delivery_record: { status: "delivered", client_id: "mock_client_2", timestamp: "2026-06-10" } }`

---

## Step 8 — Client Revision Request (post-delivery)

**Client (mock):** "Great guide — can you add a short section on migrating data from spreadsheets?"

**Tool:** `send_to_IntakeAgent` — wire `DispatchAgent_to_IntakeAgent` ⭐ *(not exercised in Mock Test 1)*
**Input:** `{ revision_request: "add section on spreadsheet data migration", original_delivery_id: "mock_client_2/2026-06-10", routed_as: "new_intake_item" }`

**IntakeAgent →** `parse_request` → `classify_work` → `{ work_type: "revision", routing_plan: ["DraftAgent", "ReviewAgent", "DispatchAgent"] }`

*Design decision verified: client revisions re-enter through IntakeAgent (full QA pipeline), never directly to DraftAgent.*

*(Revision sub-run truncated — same path as Steps 3–7, approved at score 84, delivered.)*

---

## Wire Summary

| # | Wire | Status |
|---|------|--------|
| 1 | IntakeAgent → ResearchAgent | ✅ |
| 2 | IntakeAgent → DraftAgent | ✅ |
| 3 | ResearchAgent → DraftAgent | ✅ |
| 4 | DraftAgent → ResearchAgent (mid-draft) | ✅ ⭐ first coverage |
| 5 | DraftAgent → ReviewAgent | ✅ (rounds 0 + 1) |
| 6 | ReviewAgent → ResearchAgent (fact-check) | ✅ ⭐ first coverage |
| 7 | ReviewAgent → DraftAgent (revision) | ✅ |
| 8 | ReviewAgent → DispatchAgent | ✅ |
| 9 | DispatchAgent → IntakeAgent (client revision) | ✅ ⭐ first coverage |

**Total agents visited:** 5/5
**Total wires used:** 9/9 (full coverage — first test to do so)
**Revision cycles:** 1 initial + 1 post-delivery revision run (both within limits)
**Escalations to human:** 0 (correct — no escalation condition was met)
**Final quality scores:** 86 (initial), 84 (revision)

---

## Verdict

**PASS** — practical request completed the full pipeline with 9/9 wire coverage. Mid-draft research, fact-check loop, and post-delivery client revision routing all fired per their wire contracts. Quality gate enforced both runs; revision-via-IntakeAgent design decision confirmed in practice.

**Coverage note:** escalation paths (vague intake, research confidence < 60, 3-cycle exhaustion, delivery failure) remain untested — a good candidate for Mock Test 3 (failure-path test).
