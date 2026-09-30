# DraftStudio n8n Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One importable n8n workflow JSON that runs the DraftStudio agent pipeline (Intake → Research → Draft ⇄ Review → Dispatch) using only n8n built-in nodes.

**Architecture:** A Webhook (and a Manual Trigger for testing) feeds a chain of built-in n8n AI nodes (Basic LLM Chain / AI Agent with the built-in Groq Chat Model and Structured Output Parser). Deterministic checks and the review verdict are computed with Edit Fields (Set) and IF nodes using expressions — no Code node, no community nodes. The revision loop is a native loop-back connection capped at 3 cycles; escalation returns a "needs human" response.

**Tech Stack:** n8n (built-in nodes: `n8n-nodes-base.*` and `@n8n/n8n-nodes-langchain.*`), Groq API through n8n's Groq credential, Python 3 stdlib for the validator.

**Spec:** none for this task; the design below is the binding source. The behavioral reference is `docs/superpowers/plans/2026-09-29-pipeline-modernization.md` / `harness/run_pipeline.py` (threshold 80, 3 revision cycles, escalation).

## Global Constraints
- **Native nodes only:** every node `type` must start with `n8n-nodes-base.` or `@n8n/n8n-nodes-langchain.` and exist in the real n8n packages. No community nodes. **No `n8n-nodes-base.code`, `function`, `functionItem` or `executeCommand` nodes.**
- **No secrets in the file:** credentials are referenced by type and name only (`groqApi` → `"DraftStudio Groq"`, and `httpHeaderAuth` → `"DraftStudio Tavily"` if used). Credential `id` values are the string `"REPLACE_ME"`.
- **Models:** Groq chat models use `openai/gpt-oss-120b` (primary). The fallback model `qwen/qwen3.8-27b` is documented in a sticky note, and wired as a fallback model only if the verified Agent/Chain node version supports a fallback-model input.
- **Threshold and cap:** approval requires `score >= 80` and no critical issue and no placeholder text; at most 3 revision cycles, then escalate (never silently deliver).
- **File names snake_case.** Outputs: `n8n/draftstudio_pipeline.workflow.json` and `docs/n8n_workflow_design.md`.
- The working tree has unrelated uncommitted changes; commit only the files named in each task (`git add <paths>`).

## Design

```
Webhook (POST /draftstudio) ─┐
Manual Trigger ──► Test Input ┴► Normalize Request
  → IntakeAgent (Basic LLM Chain + Groq + Structured Parser)
  → IF needs_research
       true  → ResearchAgent (AI Agent + Groq + Wikipedia tool + HTTP Request Tool[Tavily]) → Build Draft Input
       false → Build Draft Input
  → DraftAgent (Basic LLM Chain + Groq + Structured Parser)            ◄──────────────┐
  → Deterministic Checks (Edit Fields: word_count, has_placeholder, length_ok)         │
  → ReviewAgent (Basic LLM Chain + Groq + Structured Parser)                           │
  → Compute Verdict (Edit Fields: approved, critical_count)                            │
  → IF approved ─ true  → DispatchAgent (Chain) → Respond: delivered                   │
                └ false → IF round < 3 ─ true → Prepare Revision (round+1, issues) ────┘
                                        └ false → Respond: escalated (HTTP 200, status "escalated")
```
State (brief, dossier, draft, round, issues) is carried in Edit Fields nodes that re-attach data from earlier nodes with `$('Node Name').item.json...` expressions. Output parsers use the manual JSON-schema mode with the same schemas as `agents/*/output_schema.json`.

## Node inventory (exact names — connections must use these)

| Name | Type | Notes |
|------|------|-------|
| Webhook | `n8n-nodes-base.webhook` | POST, path `draftstudio`, responseMode `responseNode`; body `{ "request": "..." }` |
| Manual Trigger | `n8n-nodes-base.manualTrigger` | testing |
| Test Input | `n8n-nodes-base.set` | sets `body.request` to a sample vacation-policy memo request |
| Normalize Request | `n8n-nodes-base.set` | `raw_request` = `{{ $json.body.request }}`, `round` = 0 (number), `run_id` = `{{ $execution.id }}`, `issues` = `[]` |
| IntakeAgent | `@n8n/n8n-nodes-langchain.chainLlm` | system prompt from `agents/IntakeAgent/system_prompt.txt`; output parser attached |
| Groq Intake | `@n8n/n8n-nodes-langchain.lmChatGroq` | ai_languageModel → IntakeAgent |
| Intake Parser | `@n8n/n8n-nodes-langchain.outputParserStructured` | ai_outputParser → IntakeAgent; schema = IntakeAgent output_schema |
| Needs Research? | `n8n-nodes-base.if` | `{{ $json.output.needs_research }}` is true |
| ResearchAgent | `@n8n/n8n-nodes-langchain.agent` | system prompt from `agents/ResearchAgent/system_prompt.txt`; max iterations 6 |
| Groq Research | `lmChatGroq` | ai_languageModel → ResearchAgent |
| Wikipedia | `@n8n/n8n-nodes-langchain.toolWikipedia` | ai_tool → ResearchAgent |
| Tavily Search | `@n8n/n8n-nodes-langchain.toolHttpRequest` | ai_tool → ResearchAgent; POST `https://api.tavily.com/search`, Header Auth credential, `query` as a model-supplied placeholder |
| Build Draft Input | `n8n-nodes-base.set` | brief, dossier (or empty), round, issues, raw_request; reached from both branches |
| DraftAgent | `chainLlm` | system prompt from `agents/DraftAgent/system_prompt.txt`; prompt includes `issues` and previous draft when `round > 0` |
| Groq Draft / Draft Parser | `lmChatGroq` / `outputParserStructured` | |
| Deterministic Checks | `n8n-nodes-base.set` | `word_count`, `has_placeholder` (regex expression), `length_ok` (±15% against a number parsed from `brief.length`, true when no number), keeps state |
| ReviewAgent | `chainLlm` | system prompt from `agents/ReviewAgent/system_prompt.txt`; receives the deterministic results |
| Groq Review / Review Parser | `lmChatGroq` / `outputParserStructured` | |
| Compute Verdict | `n8n-nodes-base.set` | `approved` = `score >= 80 && !has_placeholder && critical_count == 0`; `issues` merged (LLM issues + deterministic issue objects) |
| Approved? | `n8n-nodes-base.if` | |
| DispatchAgent | `chainLlm` | + `Groq Dispatch`, `Dispatch Parser` |
| Respond Delivered | `n8n-nodes-base.respondToWebhook` | JSON: status `delivered`, score, title, `deliverable` (markdown), `delivery_note`, `run_id` |
| Rounds Left? | `n8n-nodes-base.if` | `{{ $json.round < 3 }}` |
| Prepare Revision | `n8n-nodes-base.set` | `round` = round + 1, carries issues and previous draft; connects back to DraftAgent |
| Respond Escalated | `n8n-nodes-base.respondToWebhook` | JSON: status `escalated`, reason, last score, issues, last draft |
| Notes | `n8n-nodes-base.stickyNote` ×3 | overview, credentials setup (Groq API key, optional Tavily header auth), fallback model |

Node names ending in "Agent" and the sub-nodes are those listed; additional sticky notes may be added.

## Preflight scan (controller records this in the ledger)
Tasks share `scripts/validate_n8n_workflow.py` (Task 1 produces, Tasks 2-3 consume) and `n8n/draftstudio_pipeline.workflow.json` (Task 2 produces, Task 3 modifies). Interfaces: the validator takes a single path argument and exits non-zero on any error; the workflow file is one JSON object with `name`, `nodes`, `connections`, `settings`.

---

### Task 1: Workflow validator

**Files:**
- Create: `scripts/validate_n8n_workflow.py`, `tests/unit/test_validate_n8n_workflow.py`

**Interfaces:**
- Produces: `validate(workflow: dict) -> list[str]` (error strings; empty = valid) and a CLI `python3 scripts/validate_n8n_workflow.py <file>` that prints each error and exits 1 if any, else prints `OK: <n> nodes` and exits 0.
- Rules (each an error): top-level keys `name`, `nodes`, `connections` present; every node has unique `name`, unique `id`, a `type`, `typeVersion` (number), `position` (two numbers), `parameters` (object); every `type` starts with `n8n-nodes-base.` or `@n8n/n8n-nodes-langchain.`; type is not one of `n8n-nodes-base.code`, `.function`, `.functionItem`, `.executeCommand`; every connection source key and every target `node` names an existing node; connection types are one of `main`, `ai_languageModel`, `ai_outputParser`, `ai_tool`, `ai_memory`; every non-sticky node is reachable from a trigger (types containing `webhook` or `Trigger`) following connections in either direction (AI sub-nodes count as reachable through their root); `credentials` entries have an `id` and `name` and no value looks like a secret (regex `gsk_[A-Za-z0-9]{10,}|tvly-[A-Za-z0-9]{10,}|sk-[A-Za-z0-9]{20,}` anywhere in the JSON text); every `{{ ... }}` expression is brace-balanced (count of `{{` equals count of `}}` in each string).

- [ ] **Step 1: Write failing tests** covering: a minimal valid workflow passes; each rule above has one test that fails with a message naming the problem (duplicate names, unknown connection target, forbidden Code node, non-native type, unreachable node, secret pattern, unbalanced `{{`). Use `sys.path` insertion of `scripts/` or `importlib` to import the module (scripts/ is not a package).
- [ ] **Step 2: Run** `python3 -m pytest tests/unit/test_validate_n8n_workflow.py -v` (if `pytest` is missing use `python3 -m unittest`-style tests instead; system Python has no pytest — write the tests with `unittest` so they run under plain `python3 -m unittest tests.unit.test_validate_n8n_workflow -v`) and confirm they fail (module missing).
- [ ] **Step 3: Implement** the validator, stdlib only.
- [ ] **Step 4: Run tests** and confirm all pass.
- [ ] **Step 5: Commit** `git add scripts/validate_n8n_workflow.py tests/unit/test_validate_n8n_workflow.py && git commit -m "feat: add n8n workflow validator"`

---

### Task 2: Build the workflow JSON and design doc

**Files:**
- Create: `n8n/draftstudio_pipeline.workflow.json`, `docs/n8n_workflow_design.md`

**Interfaces:**
- Consumes: the validator from Task 1; agent system prompts in `agents/<Agent>/system_prompt.txt`; output schemas in `agents/<Agent>/output_schema.json` (if the files are absent on this branch, derive the schemas from `harness/run_pipeline.py` prompts: Intake `{brief{topic,audience,tone,length,key_points[],format}, work_type, needs_research, routing_plan[]}`, Draft `{draft{title,content,word_count}}`, Review `{dimension_scores{clarity,accuracy,completeness,tone_alignment}, score, requirements[], issues[{severity,description,suggested_fix}], status}`, Dispatch `{package{title,delivery_note,status}}`).
- Produces: a workflow importable via n8n "Import from file" containing every node in the Node inventory with the exact names, wired as in the Design diagram.

Requirements:
- Full valid n8n export shape: `{ "name": "DraftStudio Pipeline", "nodes": [...], "connections": {...}, "pinData": {}, "settings": { "executionOrder": "v1" }, "active": false, "tags": [] }`. Node `id` values are UUID-format strings; `position` laid out left-to-right with no overlaps (step ≈ 220 px; AI sub-nodes below their root).
- AI sub-node connections are declared on the sub-node as `connections["<sub-node name>"]["ai_languageModel" | "ai_outputParser" | "ai_tool"] = [[{ "node": "<root>", "type": "<same type>", "index": 0 }]]`.
- System prompts are pasted from the agent prompt files into each chain's system message (single source: copy at build time; note this in the design doc).
- Expressions use n8n syntax (`={{ ... }}` in parameter values; parameter strings that are expressions start with `=`).
- Each `lmChatGroq` node: model `openai/gpt-oss-120b`, credential `groqApi` named `DraftStudio Groq`, credential id `REPLACE_ME`.
- `docs/n8n_workflow_design.md`: how to import, credentials to create, the request/response shapes (webhook body `{ "request": "..." }`; responses `delivered` / `escalated`), how the loop and the 3-cycle cap work, how deterministic checks work, known n8n limits.

- [ ] **Step 1:** Write the workflow JSON.
- [ ] **Step 2:** Run `python3 scripts/validate_n8n_workflow.py n8n/draftstudio_pipeline.workflow.json`; fix until `OK`.
- [ ] **Step 3:** Write `docs/n8n_workflow_design.md`.
- [ ] **Step 4: Commit** `git add n8n/draftstudio_pipeline.workflow.json docs/n8n_workflow_design.md && git commit -m "feat: add n8n DraftStudio pipeline workflow (built-in nodes only)"`

---

### Task 3: Verify node types and versions against the real n8n packages

**Files:**
- Modify: `n8n/draftstudio_pipeline.workflow.json` (only to fix findings), `docs/n8n_workflow_design.md` (add a "Verified against" line)
- Create: `n8n/verify_notes.md`

Goal: confirm every `type` and `typeVersion` exists in the current published n8n packages and that parameter names used are the ones each node's description defines.

- [ ] **Step 1:** In the session scratchpad directory (never in the repo), fetch the packages for inspection only: `npm pack n8n-nodes-base @n8n/n8n-nodes-langchain` then unpack the tarballs (`tar -xzf`). Do not `npm install` anything into the repo and do not execute package code. If the download is refused by the environment, stop this step, write `n8n/verify_notes.md` saying verification against packages was not possible, and go to Step 4 (structural validation only).
- [ ] **Step 2:** For each distinct node type in the workflow, locate its `*.node.js` (or `.node.json`) in the unpacked package and check: the type name, that the workflow's `typeVersion` is among the node's supported versions (`version:` array/number), and that each top-level `parameters` key used is a property `name` in the node's description (for versioned nodes check the matching `V*/` description). Record a table (node, type, version used, supported versions, parameter check) in `n8n/verify_notes.md`.
- [ ] **Step 3:** Fix any mismatch in the workflow JSON (bump `typeVersion`, rename parameters). Check whether the verified Agent/Chain version has a fallback-model input; if yes, add `Groq Fallback <X>` nodes (model `qwen/qwen3.8-27b`) wired as the second `ai_languageModel` input (`index: 1`) and set the node's fallback parameter as its description defines; if not, leave the sticky note.
- [ ] **Step 4:** Re-run the validator and the validator's unit tests; both must pass.
- [ ] **Step 5: Commit** `git add n8n/ docs/n8n_workflow_design.md && git commit -m "chore: verify n8n node types/versions against published packages"`
