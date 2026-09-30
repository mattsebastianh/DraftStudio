# DraftStudio Pipeline: n8n Workflow Design

`n8n/draftstudio_pipeline.workflow.json` runs the DraftStudio agent pipeline
(Intake → Research → Draft ⇄ Review → Dispatch) inside n8n. It uses only n8n built-in nodes
(`n8n-nodes-base.*` and `@n8n/n8n-nodes-langchain.*`): no Code or Function nodes, no community
nodes. It mirrors `harness/run_pipeline.py` in shape (quality threshold 80, at most 3 revision
cycles, then escalation) but its quality gate is stricter (section 6).

Check the file with `python3 scripts/validate_n8n_workflow.py n8n/draftstudio_pipeline.workflow.json`
and its tests with `python3 -m unittest tests.unit.test_n8n_quality_gate tests.unit.test_n8n_telegram_wiring tests.unit.test_validate_n8n_workflow`.

| | |
|---|---|
| **Status** | Imported into a local n8n 2.x and run live (executions 370-380: Telegram in and out, revision loop, Groq 429 fallback). Inactive. |
| **Not yet run live** | The stricter approval gate and constraint checks, the OpenRouter reviewer fallback, the failure branches (service error, research error), and multi-part Telegram replies. |
| **Verified against** | `n8n-nodes-base@2.41.2`, `@n8n/n8n-nodes-langchain@2.41.2`, `n8n-core@2.41.2` (2026-09-29); see [verify_notes.md](../n8n/verify_notes.md). |
| **Diagrams** | [02_pipeline_architecture_n8n.svg](02_pipeline_architecture_n8n.svg) (this workflow) · [01_pipeline_architecture_groq_harness.svg](01_pipeline_architecture_groq_harness.svg) (the Python harness, for comparison) |

## Contents

1. [Setup and security](#1-setup-and-security)
2. [Triggers and responses](#2-triggers-and-responses)
3. [Pipeline](#3-pipeline)
4. [Models](#4-models)
5. [Failure handling](#5-failure-handling)
6. [Quality gate](#6-quality-gate)
7. [Telegram](#7-telegram)
8. [Reference and known limits](#8-reference-and-known-limits)
9. [Test history](#9-test-history)

---

## 1. Setup and security

### Import

1. In n8n: **Workflows → Add workflow → … menu → Import from File**, then choose
   `n8n/draftstudio_pipeline.workflow.json`.
2. Create the credentials below and select them on each node that shows a credential warning.
   The file refers to credentials by name only, with id `REPLACE_ME`.
3. Set the **Restrict to Chat IDs** value on the Telegram Trigger (see the checklist).
4. Test with **Test workflow** (Manual Trigger → Test Input, a sample vacation-policy memo
   request) or by messaging the bot.
5. Activate the workflow. The production webhook is `POST <n8n-base>/webhook/draftstudio`.

### Credentials

| Credential type | Name | Used by | Value |
|---|---|---|---|
| Groq API (`groqApi`) | `DraftStudio Groq` | Groq Intake / Research / Draft / Dispatch | Groq API key |
| OpenRouter (`openRouterApi`) | `DraftStudio OpenRouter` | OpenRouter Review and every OpenRouter Fallback node | OpenRouter API key |
| Telegram API (`telegramApi`), optional | `DraftStudio Telegram` | Telegram Trigger and all `Telegram Reply …` nodes | Bot token from BotFather |
| Header Auth (`httpHeaderAuth`), optional | `DraftStudio Tavily` | Tavily Search | Name `Authorization`, value `Bearer <Tavily key>` |

Keys live only in n8n's credential store, never in the JSON. Without a Tavily key, disable or
delete the **Tavily Search** node: ResearchAgent still works with Wikipedia.

### Before you activate

- [ ] **Webhook authentication.** The Webhook node ships with *Header Auth* and a placeholder
  credential, **DraftStudio Webhook**. Create it (header `X-API-Key`, a long random value) and
  send that header on every call; an unconfigured import cannot be called. Never set it to
  *None*: each run makes 5-13 LLM calls on your quota. Consider a hard-to-guess path too.
  The request text goes straight into the prompts, so prompt injection is possible; the only
  tools any agent can call are Wikipedia and Tavily search, both read-only.
- [ ] **Telegram chat ids.** The trigger's *Restrict to Chat IDs* holds the placeholder
  `REPLACE_WITH_YOUR_CHAT_ID`, so an unconfigured import rejects every message (fail closed).
  Replace it with your chat id (comma-separated for several). Without a real id the bot stays
  silent; with an empty value anyone who finds the bot could spend your quota.
- [ ] **One webhook per bot.** Activating the trigger points the bot's Telegram webhook at this
  workflow (`WEBHOOK_URL` must be public HTTPS). Use a bot no other workflow uses, or that
  workflow stops receiving messages.
- [ ] **OpenRouter credit.** The reviewer and every fallback except the reviewer's run on OpenRouter; an empty balance
  stops the review (section 5).

## 2. Triggers and responses

### Triggers

| Trigger | Path | Reply channel |
|---|---|---|
| Webhook (`POST /webhook/draftstudio`, body `{ "request": "..." }`) | → Normalize Request | HTTP response from a Respond node |
| Manual Trigger → Test Input | → Normalize Request | Inspect the last node's output in the editor |
| Telegram Trigger → Has Request Text? → Telegram Input | → Normalize Request | Telegram message(s) to the same chat |

The Webhook uses `responseMode: responseNode`, so the HTTP call stays open until a Respond node
answers. `run_id` in every answer is the n8n execution id (`$execution.id`).

### HTTP responses

| Outcome | Node | HTTP | `status` |
|---|---|---|---|
| Approved | Respond Delivered | 200 | `delivered` |
| 3 revision cycles exhausted | Respond Escalated | 200 | `escalated` |
| Intake could not parse the request | Respond Needs Clarification | 200 | `needs_clarification` |
| An agent failed (after retries and fallback) | Respond Service Error | 500 | `error` |

Delivered:

```json
{
  "status": "delivered", "run_id": "123", "score": 86, "rounds": 1,
  "title": "Updated Vacation Policy",
  "deliverable": "# Updated Vacation Policy\n...markdown...",
  "delivery_note": "Short client-facing note", "package_status": "delivered", "issues": []
}
```

Escalated (a failing draft is never delivered silently):

```json
{
  "status": "escalated", "run_id": "123",
  "reason": "Revision cap reached: 3 revision cycles exhausted ... Needs human review.",
  "last_score": 72, "rounds": 3,
  "issues": [{ "severity": "high", "description": "...", "suggested_fix": "..." }],
  "last_draft": { "title": "...", "content": "...", "word_count": 310 }
}
```

Needs clarification and service error carry `status`, `run_id` and a `message`.

## 3. Pipeline

```
Webhook ───────────────┐
Manual Trigger → Test Input ──► Normalize Request
Telegram Trigger → Has Request Text? → Telegram Input ─┘
  → IntakeAgent ──error──► Intake Reply Unparseable? ─yes→ Respond Needs Clarification
  │                                                    └no→ Respond Service Error
  → Needs Research?
       yes → ResearchAgent (Wikipedia, Tavily) → Build Draft Input      (research error → no dossier)
       no  → Build Draft Input
  → DraftAgent                                                        ◄─────────────┐
  → Deterministic Checks → ReviewAgent → Compute Verdict → Approved?                │
       yes → DispatchAgent → Respond Delivered → Telegram reply (1-3 messages)      │
       no  → Rounds Left? ─ yes → Prepare Revision ───────────────────────────────┘
                          └ no  → Respond Escalated → Telegram reply
  Draft / Review / Dispatch error output → Respond Service Error → Telegram reply
```

### State carrying

LLM nodes output only `{ output: ... }`, so the Edit Fields (Set) nodes rebuild the pipeline state
by referencing earlier nodes by name:

| Node | Adds / carries |
|---|---|
| Normalize Request | `raw_request`, `round = 0`, `run_id`, `issues = []`, `chat_id` (from top-level `telegram_chat_id`, else empty) |
| Build Draft Input | `raw_request`, `run_id`, `brief`, `work_type`, `dossier`, `research_failed`, `round`, `issues`, `previous_draft = {}`. Reads `$('Normalize Request').first()`, `$('IntakeAgent').first()` and, if it ran, `$('ResearchAgent').first()`, so it works whichever branch fed it |
| Deterministic Checks | constant state from `$('Build Draft Input').first()`, the current `round`, `draft`, plus `word_count`, `has_placeholder`, `length_ok`, `constraint_failures` |
| Compute Verdict | everything from `$('Deterministic Checks').last()`, plus `review`, `score`, `critical_count`, `constraint_failures`, merged `issues`, `approved` |
| Prepare Revision | same shape as Build Draft Input with `round + 1`, `issues`, `previous_draft`, `research_failed`, `last_score` |

Build Draft Input and Prepare Revision output the same shape, so DraftAgent's prompt uses `$json`
whichever fed it. `.first()` is only used on nodes that run once per execution. Inside the loop,
`.last()` (a node's latest run) gives the current cycle: paired-item lookups back through a loop
are fragile, and with one item per run the latest run is the current cycle.

### Revision loop

`round` counts revision cycles; the first draft is round 0. **Approved?** false → **Rounds Left?**
(`round < 3`): true → **Prepare Revision** (`round + 1`, merged issues, previous draft) → back into
DraftAgent, which gets the revision prompt with a bulleted issue list; false → **Respond
Escalated**. That allows the first draft plus up to 3 revisions, like the harness's
`MAX_REVISION_CYCLES = 3`.

## 4. Models

| Agent | Primary (node) | Fallback (node) | Max output tokens |
|---|---|---|---|
| Intake | Groq `openai/gpt-oss-120b` (`Groq Intake`) | OpenRouter `openai/gpt-oss-20b` | 4000 |
| Research | Groq `openai/gpt-oss-120b` | OpenRouter `openai/gpt-oss-20b` | 12000 |
| Draft | Groq `openai/gpt-oss-120b` | OpenRouter `openai/gpt-oss-20b` | 12000 |
| **Review** | **OpenRouter `qwen/qwen3-235b-a22b-2507`** (`OpenRouter Review`, temperature 0.1) | **Groq `llama-3.3-70b-versatile`** (`Groq Fallback Review`, temperature 0.1) | 4000 |
| Dispatch | Groq `openai/gpt-oss-120b` | OpenRouter `openai/gpt-oss-20b` | 3000 |

Temperature is 0.3 except on the review nodes. Groq and fallback nodes size max tokens for
reasoning models, which spend part of the budget on hidden reasoning; the OpenRouter option is
`maxTokens`, the Groq one `maxTokensToSample`.

**Why the reviewer is different.** A different model family from the drafter avoids a judge that
favours its own style; a non-reasoning model spends no budget on hidden reasoning (the
gpt-oss-20b fallback once returned an empty response, execution 378); and moving the review off
Groq removes about 4000 tokens per round from Groq's per-minute budget (execution 377 hit the
8000 TPM limit inside ReviewAgent). The fallback is a third family on a different provider. Cost is about $0.001-0.002 per
review at list prices. **Two providers everywhere:** every agent has a primary and a fallback on
different providers (Groq with an OpenRouter fallback, and the OpenRouter reviewer with a Groq
fallback), so a regional Groq block (Groq can be unreachable from some regions) or an OpenRouter
outage or empty balance cannot take out an agent by itself.

**How fallback works.** Each chain/agent has *Enable Fallback Model* on (`needsFallback: true`) and
its fallback node wired to the second model input (*Fallback Model*, `ai_languageModel` index 1).
If a call to the primary throws (for example a Groq 429), LangChain's `withFallbacks` re-runs the
same prompt on the fallback. This needs Basic LLM Chain 1.2 or 1.4+ (1.5 is used) and AI Agent
2.1+ (ResearchAgent uses 2.2).

**Retries.** Every agent has Retry On Fail: **5 tries, 5 s apart** (n8n's maximum), about 20 s of
waiting, which covers a typical Groq "try again in ~8 s" 429.

**`.env` is reference only.** n8n does not read it. `.env.example` lists `OPENROUTER_PRIMARY_MODEL`,
`OPENROUTER_FALLBACK_MODEL` and `OPENROUTER_REVIEW_MODEL`
for the Python harness and as a record; the workflow hard-codes the IDs on its nodes, so
changing a variable changes nothing here. To change a model, edit the Model field on the node.

## 5. Failure handling

Every agent (Intake, Research, Draft, Review, Dispatch) has **On Error: Continue (using error
output)**, taken after its 5 retries and its fallback model:

| Failure | Result |
|---|---|
| Intake reply cannot be parsed (`doesn't fit required format`, empty response, invalid JSON) | **Intake Reply Unparseable?** is true → `needs_clarification` reply asking for topic, audience, tone and length. Typical cause: a chat message that is not a writing request ("where is my cake", execution 371) |
| Any other Intake failure (429, expired key, network) | `error` reply (HTTP 500 for the webhook, a generic Telegram message with the run id). The internal error text is never sent to the user |
| Research fails or hits `Agent stopped due to max iterations.` | Continues without a dossier; `research_failed` is set (section 6) |
| Draft, Review or Dispatch fails | `error` reply, as above |

Reasons a run can still end without a reply: n8n itself is down, or the Telegram send fails. Look in
the Executions list.

## 6. Quality gate

### Deterministic checks (no LLM)

**Deterministic Checks** (Edit Fields) computes facts with expressions and passes them to
ReviewAgent as facts:

- `word_count`: the draft content split on whitespace. The model's self-reported count is never
  trusted.
- `has_placeholder`: true when a bracketed placeholder (`[Insert ...]`, `[Add ...]`, `[Name]`,
  `[Date]`, `[Company Name]`, `[TODO]`, `[TBD]`, `[Placeholder]`, `[Your ...]`, case-insensitive)
  or `lorem ipsum` is found, or the exact upper-case words `TODO`, `TBD`, `XXX`. The bracket forms
  skip markdown link text with a `(?!\()` lookahead. Ordinary words such as "todo app" do not match.
- `length_ok`, from `brief.length` when it mentions "word":

  | Wording | Rule |
  |---|---|
  | one number, "under / below / max / no more than / at most / up to / less than / fewer than N words" | draft ≤ N |
  | one number, "at least / minimum / no fewer than / no less than / more than / over N words" | draft ≥ N |
  | a target ("400 words") or a range ("300-400 words") | between min × 0.85 and max × 1.15 |
  | no word target ("one page", "short") | always true |

- `constraint_failures` (array of messages), read from the original request text:

  | Constraint | Check |
  |---|---|
  | *end with the sentence "X"* (straight, curly or single quotes; apostrophes inside are fine) | the draft ends with X; trailing markdown emphasis and quotes are ignored, text after it fails |
  | *exactly N words* (ignored when preceded by "each / every / per") | the whole draft is within N ± 5% |
  | *bulleted list of at least N* / *at least N bullets* (N as digits or one to ten) | at least N lines starting with `-`, `*`, `•` or `1.` |

  Other phrasings are not detected. Extend the regexes when a real request needs it.

### Verdict

**Compute Verdict** (Edit Fields) sets:

- `critical_count`: ReviewAgent issues with severity `critical` (case ignored).
- `issues`: ReviewAgent's issues, plus a `critical` issue for a placeholder, a `high` issue when
  `length_ok` is false, and one `critical` issue per constraint failure. The next revision sees all
  of them.
- `approved` = score ≥ 80 **and** no placeholder **and** `length_ok` **and** no
  `constraint_failures` **and** no ReviewAgent issue with severity `critical` or `high`.

The workflow computes this itself instead of trusting the model's `status`: it disagreed with the
outcome in both directions (execution 378: `approved` while listing placeholders; execution 380:
`revision_required` for a draft the old rule shipped). `medium` and `low` issues are reported but
do not block. The gate causes more revision rounds and more escalations than the harness; the loop
is still capped at 3.

### Research and invented details

- If ResearchAgent ends with `Agent stopped due to max iterations.` (execution 380) or returns no
  output, Build Draft Input clears the dossier and sets `research_failed`; DraftAgent is then told
  no verified sources exist. Research is capped at 10 iterations.
- DraftAgent is told not to invent contact details, statistics, studies, quotes, names or dates,
  and to cite only dossier sources. ReviewAgent is told to flag any such unsupported claim as
  `high`, which blocks approval.
- ReviewAgent also receives `constraint_failures` and the original client request, not only the
  brief.

## 7. Telegram

```
Telegram Trigger → Has Request Text? ─yes→ Telegram Input → Normalize Request → …
Respond Delivered  → Reply on Telegram? (delivered) → Telegram Reply Delivered [→ part 2 → part 3]
Respond Escalated  → Reply on Telegram? (escalated) → Telegram Reply Escalated
Respond Needs Clarification → Reply on Telegram? (clarify) → Telegram Reply Clarify
Respond Service Error       → Reply on Telegram? (error)   → Telegram Reply Error
```

- **Filter:** updates without message text (stickers, photos) are dropped silently.
- **`chat_id`:** `Telegram Input` writes the chat id to a top-level `telegram_chat_id` field and
  `Normalize Request` copies it to `chat_id` (empty for Webhook and Manual runs). The Webhook payload
  lives under `body`, so a webhook caller can never set it or make the workflow message an
  arbitrary chat. Each reply gate tests that `chat_id` is not empty, so Webhook and Manual runs never
  call Telegram.
- **Replies are plain text** (no parse mode: Groq Markdown often breaks Telegram's parser), so
  `**bold**` shows as literal asterisks.
  - *Delivered:* a header line (`Approved · score N · N revision(s)`) then the deliverable only;
    DispatchAgent's delivery note is not sent. Long deliverables go out in up to three messages of
    3900 characters (Telegram's limit is 4096); beyond 11,700 characters the last message ends with a
    notice pointing at the n8n execution.
  - *Escalated:* the last score and the top five issues, with a needs-human-review notice, cut at
    4000 characters.
  - *Clarification and error:* the fixed messages from section 5.

## 8. Reference and known limits

### Prompts and structured output

- **Prompts are copies.** Each chain/agent's system message is a copy of
  `agents/<Agent>/system_prompt.txt`, pasted in when the workflow was built; editing the file does
  not update the workflow. **ReviewAgent's copy deliberately differs:** its decision rule says
  `critical` **or** `high` blocks approval and it lists only the fields the parser schema has,
  matching section 6. The user prompt of each node repeats the harness's wire name and format
  instructions and tells the model that the tools named in the prompt files
  (`parse_request`, `outline_content`, …) do not exist in n8n.
- **Structured output.** Intake, Draft, Review and Dispatch each have a Structured Output Parser in
  manual JSON-schema mode, with the harness's contracts: Intake
  `{brief{topic,audience,tone,length,key_points[],format}, work_type, needs_research, routing_plan[]}`,
  Draft `{draft{title,content,word_count}}`, Review `{dimension_scores{clarity,accuracy,completeness,tone_alignment}, score, requirements[{requirement,passed}], issues[{severity,description,suggested_fix}], status}`,
  Dispatch `{package{title,delivery_note,status}}`. A chain's result is at `$json.output`. Severity
  and status are plain strings rather than enums, so a capitalised value does not fail parsing.
- **Research.** ResearchAgent is an AI Agent v2.2 (always a Tools Agent) with no output parser;
  its final text (a JSON dossier) is stored as the string `dossier`.

### Known n8n limits

- **Respond nodes on the manual path:** started from the Manual Trigger, there is no HTTP request to
  answer; inspect the final node's output in the editor.
- **Webhook timeouts:** a full run with 3 revisions can take several minutes (a review alone took
  32 s on OpenRouter in execution 380). Reverse proxies or clients in front of n8n may time out first.
- **Loop references:** the loop depends on `$('Prepare Revision').isExecuted` and on `.last()`
  returning the latest run of a node that runs once per cycle. Keep exactly one item flowing
  through the workflow; the design assumes a single request per execution.
- **Groq rate limits:** the `on_demand` tier caps `openai/gpt-oss-120b` at 8000 tokens per minute.
  A run with revisions can exceed it; retries and the fallback absorb most cases (section 4).
- **Model/tool support:** ResearchAgent needs tool-calling models. OpenRouter's model list shows
  `tools` supported for `openai/gpt-oss-20b` (max output 32768, so the 12000 setting is valid); that
  is catalog metadata only, and no tool call has been run against the fallback yet.
- **Curly braces:** braces in prompts are safe in the verified versions. The Basic LLM Chain doubles
  every `{`/`}` in its Chat Messages before building the LangChain template and passes the user
  prompt as `{query}`; the AI Agent passes its system message as `{system_message}` and the prompt as
  `{input}`. Do not escape braces by hand (`{{` would reach the model literally), and remember that
  n8n treats `{{ ... }}` as an expression in any field that starts with `=`. An expression must not
  contain `}}` inside its body.
- **Tavily tool:** `toolHttpRequest` v1.1 still loads and runs in n8n 2.41 but is marked `hidden`
  (n8n recommends `n8n-nodes-base.httpRequestTool`). The body uses *Specify Body: Using Fields
  Below* with one model-supplied `query` field, so quotes in a query cannot break the request
  body. Tavily's defaults (`max_results` 5, `search_depth` "basic") apply. To move to
  `httpRequestTool`, keep the URL and header credential and fill `query` with `$fromAI('query')`.
- **Settings and the API:** n8n adds `binaryMode` to the workflow settings when saved from the editor,
  and the public API rejects that key on update. Use n8n-mcp's partial update, or send settings
  without it.
- **Editor tabs:** a tab opened before an API or MCP update holds the old version, and saving it
  overwrites the update. Reload before editing.

## 9. Test history

| Execution | Request | Outcome | Change it led to |
|---|---|---|---|
| 370 | Vacation memo, ~300 words | Delivered round 0, score 89 | 244-word draft shipped against a 255-345 range (length did not block); invented policy details |
| 371 | "where is my cake" | Crashed at Intake Parser | Intake error output → clarification reply |
| 377 | Office-closure memo | Groq 429 in ReviewAgent, fallback also limited | 5 × 5 s retries; reviewer moved to OpenRouter |
| 378 | Same, "end with … flexibility" | Delivered round 1, score 88, wrong closing sentence | Constraint checks; `high` issues block |
| 379 | Same | Round 0 rejected (placeholders, 590 words), delivered round 1 | Invented contact details flagged; Telegram reply = deliverable only |
| 380 | Pomodoro blog post | Delivered round 0, score 86 despite a `high` accuracy issue; research hit max iterations | Failed research scrubbed; DraftAgent no-invention rule |

The PR review then added: chat-id fail-closed default, apostrophe and
bound-aware checks, error outputs on every agent, ReviewAgent system-message alignment, and
multi-part Telegram replies. None of these has run live yet.
