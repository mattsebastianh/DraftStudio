# Node verification notes

Checks of `n8n/draftstudio_pipeline.workflow.json` against n8n's node definitions. For the design
itself (state carried between nodes, quality gate, Telegram, known limits) see the overview sticky note inside the workflow and the README; this file only covers node verification and live-run findings.

| | |
|---|---|
| **Package source check** | 2026-09-29. Packages fetched with `npm pack` into a scratch directory and read only; no package code was run. |
| **Later additions** | Telegram, OpenRouter, the extra Respond and IF nodes: checked against the n8n-mcp node catalog (`get_node`) and by live runs, **not** against package source (table below marks each). |
| **Live runs** | Local n8n 2.x, executions 370-380. The modernized workflow (prompts and parsers following `agents/*`, harness checks, Verify Research) was imported as a separate copy and run on `n8nio/n8n:2.20.11`, executions 401-403 (2026-10-05): the new expressions (lookbehind regexes, `matchAll`, `try`/`catch`, destructuring) evaluate correctly in that engine. |

## 1. Package versions

| Package | Version | Why this version |
|---|---|---|
| `@n8n/n8n-nodes-langchain` | 2.41.2 | npm `latest`, and the version `n8n@2.41.3` pins |
| `n8n-nodes-base` | 2.41.2 | The version `n8n@2.41.3` pins. npm's `latest` tag for this package is stale at 2.15.1; 2.15.1 gave the same results for every node used at the time |
| `n8n-core` | 2.41.2 | Read only to confirm how the fallback-model input is resolved (`getInputConnectionData`) |

`n8n@2.41.3` is the current npm `latest` and `stable` release.

## 2. Verification table

"Params" lists the top-level `parameters` keys the workflow uses (plus nested option keys where
relevant). A key passes if it is a property `name` in the node's description for that version.
**Source** says how it was checked: *pkg* = package source, *catalog* = n8n-mcp node catalog,
*live* = ran in executions 370-380.

| Node(s) | type | Version | Supported versions | Params check | Source |
|---|---|---|---|---|---|
| Webhook | `n8n-nodes-base.webhook` | 2 | 1, 1.1, 2, 2.1 | OK: `httpMethod`, `path`, `responseMode` (`responseNode`), `options`; `webhookId` is node-level | pkg |
| Manual Trigger | `n8n-nodes-base.manualTrigger` | 1 | 1 | OK (no parameters) | pkg, live |
| Test Input, Normalize Request, Telegram Input, Verify Research, Build Draft Input, Deterministic Checks, Compute Verdict, Prepare Revision | `n8n-nodes-base.set` | 3.4 | 3 … 3.5 (2.15.1 stops at 3.4) | OK: `mode` (`manual`), `assignments` (3.3+), `includeOtherFields` (3.3+), `options`; assignment types string, number, boolean, array, object | pkg, live |
| Needs Research?, Approved?, Rounds Left?, Has Request Text?, Intake Reply Unparseable?, Reply on Telegram? (×4), More Text? (×2) | `n8n-nodes-base.if` | 2.2 | 1, 2, 2.1, 2.2, 2.3 | OK: `conditions` (filter v2, matches `conditions.options.version: 2`), `looseTypeValidation` (2.1+), `options` | pkg (first three), live |
| IntakeAgent, DraftAgent, ReviewAgent, DispatchAgent | `@n8n/n8n-nodes-langchain.chainLlm` | 1.5 | 1 … 1.9 | OK: `promptType` (`define`), `text`, `hasOutputParser`, `needsFallback` (hidden only for 1, 1.1, 1.3), `messages.messageValues[].{type, message}` | pkg, live |
| ResearchAgent | `@n8n/n8n-nodes-langchain.agent` | **2.2** (was 1.7) | V1: 1-1.9 · V2: 2, 2.1, 2.2 · V3: 3, 3.1 | OK: `promptType`, `text`, `needsFallback` (2.1+), `options.systemMessage`, `options.maxIterations`, `options.returnIntermediateSteps` (catalog, 2026-10-05). The `agent: toolsAgent` key was removed (V2 is always the Tools Agent) | pkg, live |
| Groq Intake / Research / Draft / Dispatch | `@n8n/n8n-nodes-langchain.lmChatGroq` | 1 | 1 | OK: `model` (a string ID is valid), `options.maxTokensToSample`, `options.temperature` (0-1, one decimal) | pkg, live |
| OpenRouter Review, OpenRouter Fallback Intake / Research / Draft / Review / Dispatch | `@n8n/n8n-nodes-langchain.lmChatOpenRouter` | 1 | 1 | OK: `model`, `options.maxTokens`, `options.temperature` | catalog, live (Review 379-380, fallback 378) |
| Intake / Draft / Review / Dispatch Parser | `@n8n/n8n-nodes-langchain.outputParserStructured` | 1.2 | 1 … 1.3 | OK: `schemaType` (`manual`), `inputSchema` | pkg, live |
| Wikipedia Search | `n8n-nodes-base.httpRequestTool` | 4.4 (replaced `@n8n/n8n-nodes-langchain.toolWikipedia`, see section 7; 4.5 in the n8n-mcp catalog does not exist on the local 2.20.11, activation fails with `reading 'supplyData'`) | up to 4.4 on 2.20.11 | OK: `url`, `method`, `toolDescription`, `sendQuery` + `specifyQuery` + `queryParameters.parameters` (a value `={{ $fromAI('query', ...) }}` is the model's input), `sendHeaders` + `specifyHeaders` + `headerParameters.parameters` | catalog (`get_node`), live (2026-10-05) |
| Tavily Search | `@n8n/n8n-nodes-langchain.toolHttpRequest` | 1.1 | 1, 1.1 | OK: `toolDescription`, `method`, `url`, `authentication`, `genericAuthType`, `sendBody`, `specifyBody`, `parametersBody`, `placeholderDefinitions`. **The node is `hidden: true`** (not in the node picker; n8n recommends `n8n-nodes-base.httpRequestTool`) but still loads and runs. Disabled in the dev instance | pkg |
| Respond Delivered / Escalated / Needs Clarification / Service Error | `n8n-nodes-base.respondToWebhook` | 1.1 | 1 … 1.5 | OK: `respondWith` (`json`), `responseBody` (string parsed with `jsonParse`), `options.responseCode` | pkg, live (Delivered) |
| Telegram Trigger | `n8n-nodes-base.telegramTrigger` | 1.2 | up to 1.5 | OK: `updates`, `additionalFields.chatIds` ("Restrict to Chat IDs", 1.1+) | catalog, live |
| Telegram Reply Delivered (1-3) / Escalated / Clarify / Error | `n8n-nodes-base.telegram` | 1.2 | | OK: `resource`, `operation` (`sendMessage`), `chatId`, `text`, `additionalFields.appendAttribution` | catalog, live (Delivered, first message) |
| Notes: Overview / Credentials / Fallback model | `n8n-nodes-base.stickyNote` | 1 | 1 | OK: `content`, `height`, `width`, `color` | pkg |

The node-level fields `retryOnFail`, `maxTries`, `waitBetweenTries`, `onError`, `webhookId` and
`credentials` are part of the standard `INode` shape, not node properties, so no description was
checked for them.

## 3. Fallback-model input

Both node types that need a fallback support one:

- **chainLlm 1.5:** the `needsFallback` property is available. `getInputs` adds a second
  `ai_languageModel` input, "Fallback Model", when it is true, and `chainExecutor` wraps the model in
  `llm.withFallbacks([fallbackLlm])`.
- **agent 2.2:** same input layout; the Tools Agent executor is built with the fallback model.

`needsFallback: true` is set on all five agents, and each fallback node is connected as
`ai_languageModel` with `index: 1`. n8n-core's `validateInputConfiguration` reads these by input
index (0 = Chat Model, 1 = Fallback Model); both are `required` when `needsFallback` is on.

## 4. Mismatches found and fixed (package source check)

1. **ResearchAgent: `agent` 1.7 had no fallback-model input** (it exists only in V2.1+). Changed to
   2.2, the lowest version with a fallback input that keeps the Tools Agent executor, and removed
   the `agent: "toolsAgent"` key.
2. **Tavily Search: the `jsonBody` template `{"query": "{query}", ...}` did no escaping.** In v1.1 a
   string placeholder already inside quotes is replaced as raw text, so a query containing `"` or `\`
   would give invalid JSON. Switched to `specifyBody: "keypair"` with
   `parametersBody.values = [{name: "query", valueProvider: "modelRequired"}]`. `max_results` and
   `search_depth` were dropped (Tavily's defaults, 5 and "basic", are the same values as before; a
   keypair `fieldValue` would have sent `max_results` as the string "5").
3. No other type, version or parameter-name mismatches were found.

## 5. Findings recorded without a change

- **chainLlm escapes braces.** `promptUtils.js` doubles every `{`/`}` in Chat Messages before building
  the template, and the user prompt is passed as the `{query}` variable.
- **Output wrapping.** chainLlm 1.5 gives `{output: <parsed object>}` when an output parser is
  connected (`shouldUnwrapObjects` is true), so `$json.output` references are right.
- **Newer versions exist:** chainLlm 1.9, agent 3.1, set 3.5, if 2.3, webhook 2.1, respondToWebhook
  1.5, Telegram Trigger 1.5. They are not needed; every version used is still supported.

## 6. Changelog

| Date | Change |
|---|---|
| 2026-09-29 | Initial package-source verification; node versions fixed; Groq `qwen/qwen3.8-27b` fallback nodes added; `maxTokensToSample` set (Intake 4000, Research 12000, Draft 12000, Review 10000, Dispatch 3000); `.item` → `.last()` in loop references (Compute Verdict 14 uses, Respond Delivered 6) |
| 2026-09-30 | Groq fallbacks replaced by OpenRouter `openai/gpt-oss-20b` nodes (execution 377: Groq 8000 TPM cap, fallback limited too); Telegram, error-output and quality-gate nodes added; ReviewAgent moved to OpenRouter `qwen/qwen3-235b-a22b-2507` with a `meta-llama/llama-3.3-70b-instruct` fallback; review max tokens 4000; retries 5 × 5 s; ResearchAgent max iterations 10. These were checked against the catalog and live runs, not package source |
| 2026-10-05 | ResearchAgent `options.returnIntermediateSteps` on (checked against the n8n-mcp catalog); new Set node Verify Research between ResearchAgent's success output and Build Draft Input. Run live in executions 401-403 (intermediate steps returned; Verify Research failure path only, see below) |

## 7. Live run findings (2026-10-05, executions 401-403)

- **Wikipedia tool:** Wikipedia answers HTTP 429 to Node's default User-Agent (`node`, `undici`), which `toolWikipedia` sends and cannot change, so every call failed with `Network response was not ok` and an empty observation. Verify Research then reported no verified dossier and the drafter was told no sources exist (execution 401). The positive path of Verify Research (a finding kept because a tool returned its URL) has therefore not run live yet. Replaced by an HTTP Request tool (`Wikipedia Search`, MediaWiki query API with a descriptive `User-Agent` header), which also returns each article's URL (`fullurl`); Verify Research reads `query.pages`.
- **Groq:** every Groq call answered 403 (`Forbidden`), so each agent ran on its OpenRouter fallback; the fallbacks worked.
- **Gate:** delivered after one revision with two non-blocking `medium` issues (403); escalated with blocking constraint and reviewer issues (401, 402).
