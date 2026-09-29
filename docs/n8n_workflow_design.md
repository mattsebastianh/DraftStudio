# DraftStudio Pipeline: n8n Workflow Design

`n8n/draftstudio_pipeline.workflow.json` runs the DraftStudio agent pipeline
(Intake -> Research -> Draft <-> Review -> Dispatch) inside n8n. It uses only n8n
built-in nodes (`n8n-nodes-base.*` and `@n8n/n8n-nodes-langchain.*`): no Code or
Function nodes, no community nodes. Its behaviour mirrors `harness/run_pipeline.py`:
quality threshold 80, at most 3 revision cycles, then escalation.

Check it with `python3 scripts/validate_n8n_workflow.py n8n/draftstudio_pipeline.workflow.json`.

This workflow has been validated structurally and against the published n8n package source, but has not been executed in a live n8n instance.

Verified against: `n8n-nodes-base@2.41.2`, `@n8n/n8n-nodes-langchain@2.41.2` and `n8n-core@2.41.2`
(the versions pinned by `n8n@2.41.3`, the current npm `latest`/`stable`), 2026-09-29. Every node type,
typeVersion and top-level parameter name was checked against the published node descriptions; see
`n8n/verify_notes.md`.

## Import

1. In n8n: **Workflows -> Add workflow -> ... menu -> Import from File**, then choose
   `n8n/draftstudio_pipeline.workflow.json`.
2. Create the credentials below and select them on each node that shows a credential
   warning. The file only refers to credentials by name, with id `REPLACE_ME`.
3. Test it: click **Test workflow** (this runs Manual Trigger -> Test Input, a sample
   vacation-policy memo request), or call the webhook test URL.
4. **Security: set authentication before activating.** The Webhook node ships with
   Authentication = *None*. Once the workflow is active, anyone who knows the URL can start a
   run, and each run makes 5-13 LLM calls plus Tavily searches on your Groq and Tavily quota.
   Before step 5, open the **Webhook** node and set **Authentication** to *Header Auth*,
   *Basic Auth* or *JWT Auth* with a credential of its own. Consider changing the path from
   `draftstudio` to something hard to guess, and change it (and the credential) if it leaks.
   The request text goes straight into the prompts, so prompt injection is possible. The
   only tools any agent can call are Wikipedia and Tavily search, both read-only.
5. Go live: activate the workflow. The production URL is `POST <n8n-base>/webhook/draftstudio`
   (or the path you chose), called with the authentication you set in step 4.

## Credentials to create

| Credential type | Name | Used by | Value |
|---|---|---|---|
| Groq API (`groqApi`) | `DraftStudio Groq` | Groq Intake / Research / Draft / Review / Dispatch and Groq Fallback Intake / Research / Draft / Review / Dispatch | Your Groq API key |
| Header Auth (`httpHeaderAuth`), optional | `DraftStudio Tavily` | Tavily Search | Name `Authorization`, value `Bearer <Tavily API key>` |

If you don't set up Tavily, delete or disconnect the **Tavily Search** node. ResearchAgent
still works with the Wikipedia tool. Keep keys out of the JSON file: they live only in n8n's
credential store.

## Models

- Primary: `openai/gpt-oss-120b` on every `Groq <Agent>` Chat Model node.
- Fallback: `qwen/qwen3.8-27b` on every `Groq Fallback <Agent>` node. Each chain/agent has
  **Enable Fallback Model** on (`needsFallback: true`) and the fallback node is wired to its
  second model input (*Fallback Model*, `ai_languageModel` index 1). If a call to the primary
  model throws (for example a 429 when the daily token quota is exhausted), LangChain's
  `withFallbacks` re-runs the same prompt on the fallback model. This needs Basic LLM Chain
  1.2, or 1.4 and later (1.5 is used; 1.3 hides the option) and AI Agent >= 2.1 (ResearchAgent uses 2.2).
- Max output tokens (`maxTokensToSample`, sent to Groq as `max_tokens`) are sized for
  reasoning models, which spend part of the budget on hidden reasoning: Intake 4000,
  Research 12000, Draft 12000, Review 10000, Dispatch 3000. Primary and fallback nodes use
  the same values. Temperature is 0.3.
- n8n does not read `.env`. To change a model, edit the Model field on the Groq node.

## Request / response

Request:

```http
POST /webhook/draftstudio
Content-Type: application/json

{ "request": "Write a 300-word memo announcing our new vacation policy ..." }
```

The Webhook uses `responseMode: responseNode`, so the HTTP call stays open until one of the
two Respond nodes answers. Both answers use HTTP 200.

Delivered (from **Respond Delivered**):

```json
{
  "status": "delivered",
  "run_id": "123",
  "score": 86,
  "rounds": 1,
  "title": "Updated Vacation Policy",
  "deliverable": "# Updated Vacation Policy\n...markdown...",
  "delivery_note": "Short client-facing note",
  "package_status": "delivered",
  "issues": []
}
```

Escalated (from **Respond Escalated**, sent after the 3-cycle cap; a failing draft is never
delivered silently):

```json
{
  "status": "escalated",
  "run_id": "123",
  "reason": "Revision cap reached: 3 revision cycles exhausted ... Needs human review.",
  "last_score": 72,
  "rounds": 3,
  "issues": [{ "severity": "high", "description": "...", "suggested_fix": "..." }],
  "last_draft": { "title": "...", "content": "...", "word_count": 310 }
}
```

`run_id` is the n8n execution id (`$execution.id`), so you can open the matching execution
in n8n's Executions list.

## Flow

```
Webhook (POST /draftstudio) ─┐
Manual Trigger ──► Test Input ┴► Normalize Request
  → IntakeAgent (Basic LLM Chain + Groq Intake + Groq Fallback Intake + Intake Parser)
  → Needs Research?
       true  → ResearchAgent (AI Agent + Groq Research + Wikipedia + Tavily Search) → Build Draft Input
       false → Build Draft Input
  → DraftAgent (Basic LLM Chain + Groq Draft + Draft Parser)                    ◄────────┐
  → Deterministic Checks → ReviewAgent (Chain + Groq Review + Review Parser)             │
  → Compute Verdict → Approved?                                                          │
       true  → DispatchAgent (Chain + Groq Dispatch + Dispatch Parser) → Respond Delivered
       false → Rounds Left? ─ true  → Prepare Revision ──────────────────────────────────┘
                             └ false → Respond Escalated
```

- **Prompts:** each chain/agent's system message is a copy of
  `agents/<Agent>/system_prompt.txt`, pasted in when the workflow was built. The agent
  folder is the single source. After editing a prompt file, paste it into the matching
  node again (the system message of IntakeAgent / DraftAgent / ReviewAgent / DispatchAgent,
  or ResearchAgent's Options -> System Message). The user prompt of each node repeats the
  harness's wire name and format instructions. It also tells the model that the tools named
  in the prompt files (`parse_request`, `outline_content`, ...) don't exist in n8n. ResearchAgent
  is told to use its real tools, Wikipedia and Tavily_Search, for its web_search step.
- **Structured output:** Intake, Draft, Review and Dispatch each have a Structured Output
  Parser in manual JSON-schema mode. The schemas are the same as the harness's contracts:
  Intake `{brief{topic,audience,tone,length,key_points[],format}, work_type, needs_research,
  routing_plan[]}`, Draft `{draft{title,content,word_count}}`, Review `{dimension_scores{clarity,
  accuracy,completeness,tone_alignment}, score, requirements[{requirement,passed}],
  issues[{severity,description,suggested_fix}], status}`, Dispatch `{package{title,
  delivery_note,status}}`. Each chain's result is at `$json.output`. Severity and status are
  plain strings rather than enums, so a capitalised value doesn't fail parsing. The verdict
  compares severities without regard to case.
- **Fallback models:** every chain/agent also has a `Groq Fallback <Agent>` model node (see
  Models). The flow diagram shows Groq Fallback Intake as an example. The other four
  (Research, Draft, Review, Dispatch) are wired the same way, to their root node's
  `ai_languageModel` input at index 1.
- **Research:** ResearchAgent is an AI Agent v2.2 (always a Tools Agent; max 6 iterations)
  with no output parser. Its
  final text (a JSON dossier) is stored as the string `dossier` in Build Draft Input. When
  research is skipped, `dossier` is empty and DraftAgent is told to state its limitations.
- **Retries:** every chain/agent node has Retry On Fail (3 tries, 3 s apart). This matches
  the harness's 3 attempts at getting valid JSON.

## State carrying

LLM nodes output only `{ output: ... }`, so the Edit Fields (Set) nodes put the pipeline
state back together by referencing earlier nodes by name:

| Node | Adds / carries |
|---|---|
| Normalize Request | `raw_request`, `round = 0`, `run_id`, `issues = []` |
| Build Draft Input | `raw_request`, `run_id`, `brief`, `work_type`, `dossier`, `round`, `issues`, `previous_draft = {}`. It reads `$('Normalize Request').first()`, `$('IntakeAgent').first()` and, if it ran, `$('ResearchAgent').first()`, so it works whichever IF branch it came from |
| Deterministic Checks | constant state from `$('Build Draft Input').first()`, the current `round` (`$('Prepare Revision').last().json.round` once a revision has happened, else 0), `draft`, plus the check results |
| Compute Verdict | everything from `$('Deterministic Checks').last()`, plus `review`, `score`, `critical_count`, merged `issues`, `approved` |
| Prepare Revision | same shape as Build Draft Input with `round + 1`, `issues` and `previous_draft` (plus `last_score`) |

Build Draft Input and Prepare Revision output the same shape, so DraftAgent's prompt uses
`$json` whichever of the two fed it. `.first()` is only used on nodes that run once per
execution. Inside the loop, `.last()` (the node's latest run) gives the current cycle's
values: Compute Verdict reads `$('Deterministic Checks').last()` and Respond Delivered reads
`$('Compute Verdict').last()`. `.last()` is used instead of paired-item `.item` because
paired-item lookups back through a loop are fragile, and with one item per run the latest
run is the current cycle.

## The revision loop and the 3-cycle cap

- `round` counts revision cycles. The first draft is round 0.
- **Approved?** true -> DispatchAgent -> Respond Delivered.
- **Approved?** false -> **Rounds Left?** (`round < 3`):
  - true -> **Prepare Revision** sets `round = round + 1`, passes on the merged issues and
    the previous draft, and connects back into DraftAgent's main input. n8n allows several
    connections into the same input. DraftAgent then gets the `ReviewAgent_to_DraftAgent`
    revision prompt with the previous draft and a bulleted issue list.
  - false -> **Respond Escalated**.
- This allows the first draft plus up to 3 revisions, the same as the harness's
  `MAX_REVISION_CYCLES = 3`. A draft that still fails at round 3 is escalated, never delivered.

## Deterministic checks (no LLM)

**Deterministic Checks** (Edit Fields) computes these facts with expressions and passes
them to ReviewAgent as facts:

- `word_count`: the draft content trimmed, split on whitespace, and empty strings dropped.
  The model's self-reported `word_count` is shown alongside it but never trusted.
- `has_placeholder`: true when the regex below finds placeholder text:

  ```
  /\[(?:insert|add)\b[^\]]*\](?!\()|\[(?:name|date|company name|todo|tbd|placeholder|your [^\]]+)\](?!\()|\bTODO\b|\bTBD\b|\bX{3,}\b|lorem ipsum/i
  ```

  It matches `[insert ...]` / `[add ...]` (whole words only), the exact bracketed
  placeholders `[Name]`, `[Date]`, `[Company Name]`, `[TODO]`, `[TBD]`, `[Placeholder]` and
  `[Your ...]`, plus bare `TODO`, `TBD`, `XXX` and `lorem ipsum`. The `(?!\()` lookahead skips
  markdown link text, and the `\b` / exact-word anchors skip ordinary words. So
  `[Additional resources](url)`, `[Your HR portal](url)`, `[Dates and deadlines](#d)` and
  `[Addendum]` do not match.
- `length_ok`: when `brief.length` mentions "word", its numbers are parsed (`"300-400
  words"` gives 300 and 400) and the word count must fall within `[min * 0.85, max * 1.15]`.
  When there is no word target (e.g. "1 page", "short"), `length_ok` is true.

**Compute Verdict** (Edit Fields) then sets:

- `critical_count`: the number of ReviewAgent issues with severity `critical`, ignoring case.
- `issues`: ReviewAgent's issues, plus a `critical` placeholder issue when `has_placeholder`
  is true, plus a `high` length issue when `length_ok` is false. The next revision sees these.
- `approved = score >= 80 && !has_placeholder && critical_count == 0`. The workflow computes
  this itself instead of trusting the model's `status`. A length miss alone does not block
  approval, because it is a `high` issue (as in the plan). It is still reported in `issues`.

## Known n8n limits

- **Respond nodes on the manual path:** when you start from the Manual Trigger, there is no
  HTTP request to answer. Inspect the final node's output in the editor instead.
- **No escalated response when an AI node fails after retries:** if an LLM node still fails
  after its retries and its fallback model (Groq outage, both models' quotas exhausted, or
  output that fails the schema 3 times), the execution stops before a Respond node runs.
  The caller then gets n8n's error response (or a timeout from a proxy in between), not an
  `escalated` body. Look in the Executions list, or add an Error Workflow.
- **Webhook timeouts:** a full run with 3 revisions can take several minutes. Reverse
  proxies or clients in front of n8n may time out first.
- **Loop references:** the loop depends on `$('Prepare Revision').isExecuted` and on
  `.last()` returning the latest run of a node that runs once per cycle. Keep exactly one
  item flowing through the workflow. The design assumes a single request per
  execution.
- **Model/tool support:** ResearchAgent needs models that support tool calling, both the
  primary (`openai/gpt-oss-120b` on Groq does) and the fallback. `qwen/qwen3.8-27b` was
  confirmed against Groq's API: it returns `tool_calls`, and `/models` reports
  `max_completion_tokens` 16384, so the 12000-token setting is valid. The Structured Output Parser relies on the model
  following the format instructions n8n adds to the prompt.
- **Curly braces:** braces in prompts are safe in the verified versions. The Basic LLM
  Chain doubles every `{`/`}` in its Chat Messages before building the LangChain template,
  and the user prompt is passed in as the `{query}` variable. The AI Agent passes its
  system message as the `{system_message}` variable and the prompt as `{input}`. So
  `agents/ResearchAgent/system_prompt.txt` line 12 (`{claim, sources, confidence (0-100),
  notes}`) works in either node. Do not escape braces by hand (`{{` would reach the model
  as a literal `{{`). Remember that n8n treats `{{ ... }}` as an expression in any field
  that starts with `=`.
- **Prompt drift:** system prompts are copies (see Prompts above). Editing
  `agents/*/system_prompt.txt` does not update the workflow automatically.
- **Tavily tool:** `toolHttpRequest` v1.1 (HTTP Request Tool) still loads and runs in
  n8n 2.41, but it is marked `hidden`: it is no longer offered in the node picker, and n8n
  recommends the HTTP Request node used as a tool (`n8n-nodes-base.httpRequestTool`). The
  body uses **Specify Body: Using Fields Below** with a single `query` field
  (*By Model (and is required)*). The node sets the model's value as a real JSON value, so
  quotes or backslashes in a query cannot break the request body. A JSON-template body with
  `"{query}"` would do a raw text substitution with no escaping. Tavily's defaults
  (`max_results` 5, `search_depth` "basic") apply. To move to `httpRequestTool`, use the same
  URL, header credential and a `query` body field filled by `$fromAI('query')`.
