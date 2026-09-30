# DraftStudio Pipeline: n8n Workflow Design

`n8n/draftstudio_pipeline.workflow.json` runs the DraftStudio agent pipeline
(Intake -> Research -> Draft <-> Review -> Dispatch) inside n8n. It uses only n8n
built-in nodes (`n8n-nodes-base.*` and `@n8n/n8n-nodes-langchain.*`): no Code or
Function nodes, no community nodes. Its behaviour mirrors `harness/run_pipeline.py`:
quality threshold 80, at most 3 revision cycles, then escalation.

Check it with `python3 scripts/validate_n8n_workflow.py n8n/draftstudio_pipeline.workflow.json`.

## Diagrams

- [02_pipeline_architecture_n8n.svg](02_pipeline_architecture_n8n.svg): this workflow (n8n nodes, revision loop, escalation).
- [01_pipeline_architecture_groq_harness.svg](01_pipeline_architecture_groq_harness.svg): the same pipeline as the Python harness on Groq, for comparison.

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
| Groq API (`groqApi`) | `DraftStudio Groq` | Groq Intake / Research / Draft / Dispatch | Your Groq API key |
| OpenRouter (`openRouterApi`) | `DraftStudio OpenRouter` | OpenRouter Review and OpenRouter Fallback Intake / Research / Draft / Review / Dispatch | Your OpenRouter API key |
| Header Auth (`httpHeaderAuth`), optional | `DraftStudio Tavily` | Tavily Search | Name `Authorization`, value `Bearer <Tavily API key>` |
| Telegram API (`telegramApi`), optional | `DraftStudio Telegram` | Telegram Trigger, Telegram Reply Delivered, Telegram Reply Escalated | Bot token from BotFather |

If you don't set up Tavily, delete or disconnect the **Tavily Search** node. ResearchAgent
still works with the Wikipedia tool. Keep keys out of the JSON file: they live only in n8n's
credential store.

## Models

- Primary: `openai/gpt-oss-120b` on every `Groq <Agent>` Chat Model node.
- Fallback: `openai/gpt-oss-20b` on OpenRouter, on every
  `OpenRouter Fallback <Agent>` node. It is a smaller, cheaper sibling of the primary and is
  served through OpenRouter's own provider accounts, so a Groq org rate limit (429) does not
  also hit the fallback. Each chain/agent has
  **Enable Fallback Model** on (`needsFallback: true`) and the fallback node is wired to its
  second model input (*Fallback Model*, `ai_languageModel` index 1). If a call to the primary
  model throws (for example a 429 when the daily token quota is exhausted), LangChain's
  `withFallbacks` re-runs the same prompt on the fallback model. This needs Basic LLM Chain
  1.2, or 1.4 and later (1.5 is used; 1.3 hides the option) and AI Agent >= 2.1 (ResearchAgent uses 2.2).
- **ReviewAgent is the exception.** Its primary is `qwen/qwen3-235b-a22b-2507` on OpenRouter
  (`OpenRouter Review`, temperature 0.1, max 4000 output tokens: it is not a reasoning model, so
  no budget goes to hidden reasoning). A different model family from the drafter avoids the
  judge favouring its own style, and moving the review off Groq takes about 4000 tokens per
  round out of Groq's per-minute budget (execution 377 hit that limit in ReviewAgent). Its
  fallback is `meta-llama/llama-3.3-70b-instruct` on OpenRouter (`OpenRouter Fallback Review`, temperature 0.1, max 4000
  output tokens): a third model family (not Qwen, not gpt-oss) and not a reasoning model, since
  the gpt-oss-20b fallback returned an empty response once (execution 378). Both review models
  now run on OpenRouter, so an OpenRouter outage or empty credit balance takes out the review
  and its fallback together; the trade was made to keep the review off Groq's rate limit.
  About $0.001-0.002 per review at list prices.
- Max output tokens (`maxTokensToSample`, sent to Groq as `max_tokens`) are sized for
  reasoning models, which spend part of the budget on hidden reasoning: Intake 4000,
  Research 12000, Draft 12000, Review 10000, Dispatch 3000. Primary and fallback nodes use
  the same values (the OpenRouter option is `maxTokens`). Temperature is 0.3.
- n8n does not read `.env`. To change a model, edit the Model field on the node. `.env` keeps
  `OPENROUTER_PRIMARY_MODEL=openai/gpt-oss-120b` and
  `OPENROUTER_FALLBACK_MODEL=openai/gpt-oss-20b` and
  `OPENROUTER_REVIEW_MODEL=qwen/qwen3-235b-a22b-2507` as the reference values. The workflow
  hard-codes the fallback ID on its four OpenRouter fallback nodes and the review ID on
  `OpenRouter Review`; the primary ID is only for the Python harness.

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
  → IntakeAgent (Basic LLM Chain + Groq Intake + OpenRouter Fallback Intake + Intake Parser)
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
- **Fallback models:** every chain/agent also has an `OpenRouter Fallback <Agent>` model node (see
  Models). The flow diagram shows OpenRouter Fallback Intake as an example. The other four
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
- `approved` = score >= 80, no placeholder, `length_ok`, no `constraint_failures`, and no ReviewAgent
  issue with severity `critical` or `high` (case ignored). The workflow computes this itself
  instead of trusting the model's `status`: executions 378-380 showed the model saying
  `approved` while listing placeholders, and `revision_required` for a draft the old rule
  shipped. Earlier versions let `high` issues through (execution 370 shipped a 244-word memo
  against a 300-word target); they now block, so expect more revision rounds and more
  escalations. `medium` and `low` issues are reported but do not block.

**Request constraints** (`constraint_failures`, Deterministic Checks). Expressions read the
original request text and check the draft: (1) *end with the sentence "X"* (trailing
markdown emphasis and quotes are ignored, text after it fails), (2) *exactly N words*, allowed
N +-5% (a model cannot hit an exact count; the check is the draft's whole-text count), and
(3) *at least N bullet items* (N as digits or one..ten; counts lines starting with `-`, `*` or
a bullet). Each failure becomes a `critical` issue with a fix, so DraftAgent sees it on the
next round, and ReviewAgent receives the failures and the original request as well. Other
phrasings are not detected; extend the regexes when a real request needs it.

**Research and invented details.** If ResearchAgent ends with `Agent stopped due to max
iterations.` (execution 380), Build Draft Input clears the dossier and sets `research_failed`, so
DraftAgent is told that no verified sources exist instead of citing an error string. Research
iterations are capped at 10 (was 6). DraftAgent is told not to invent contact details,
statistics, studies, quotes, names or dates, and ReviewAgent flags any such unsupported claim
as `high`, which blocks approval.

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
  primary (`openai/gpt-oss-120b` on Groq does) and the fallback. OpenRouter's `/models` list
  shows `tools` in `supported_parameters` for `openai/gpt-oss-20b`, with
  `max_completion_tokens` 32768, so the 12000-token setting is valid. That check is of the
  catalog metadata only; no tool call has been run against the fallback yet. The Structured Output Parser relies on the model
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

## Telegram entry and reply

Messages to the bot start the pipeline, and the result is sent back to the same chat.

```
Telegram Trigger (message) -> Has Request Text? -yes-> Telegram Input -> Normalize Request -> ...
Respond Delivered  -> Reply on Telegram? (delivered)  -yes-> Telegram Reply Delivered
Respond Escalated  -> Reply on Telegram? (escalated)  -yes-> Telegram Reply Escalated
```

- **Filter:** updates without message text (stickers, photos) are dropped silently.
- **chat_id:** `Telegram Input` writes the chat id to a top-level `telegram_chat_id` field and
  `Normalize Request` copies it to `chat_id` (empty for Webhook and Manual runs). The Webhook's
  payload lives under `body`, so a webhook caller can never set `chat_id` or make the workflow
  message an arbitrary chat. The reply gates test `chat_id` is not empty, so Webhook and Manual
  runs never call Telegram.
- **Replies:** plain text (no parse mode: Groq Markdown often breaks Telegram's parser), cut to
  4000 characters (Telegram's limit is 4096). `**bold**` shows as literal asterisks.
  Delivered sends a header line (score, revision count) and the deliverable only, so the
  requested closing line stays last; the DispatchAgent's delivery note is not sent (it said
  "attached" when nothing was). Text over 4000 characters is cut, which can drop the ending.
  Escalated
  sends the last score and the top five issues, with a needs-human-review notice.
- **One webhook per bot:** activating the trigger points the bot's Telegram webhook at this
  workflow (`WEBHOOK_URL` must be public HTTPS). Use a bot no other workflow uses, or that
  workflow stops receiving messages.
- **Restrict who can use it:** open the trigger's *Additional Fields* and add **Restrict to
  Chat IDs** (and/or User IDs). Otherwise anyone who finds the bot can spend your Groq quota.
- **Unclear messages:** chat messages are not always writing requests ("where is my cake"), and
  the model then answers in prose instead of JSON, which the Intake Parser rejects. IntakeAgent
  uses **On Error: Continue (using error output)** (after its 3 retries), and the error output goes
  to `Respond Needs Clarification` (webhook JSON `status: needs_clarification`) and, for Telegram
  runs, `Telegram Reply Clarify`, which asks for topic, audience, tone and length.
  Failures in later agents still stop the run without a reply.
