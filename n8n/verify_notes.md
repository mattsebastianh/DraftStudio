# Node verification notes

These notes check `n8n/draftstudio_pipeline.workflow.json` against the published n8n node packages.

- **Date:** 2026-09-29
- **Packages:** fetched with `npm pack` into a scratch directory and read only. No package code was run.

| Package | Version | Why this version |
|---|---|---|
| `@n8n/n8n-nodes-langchain` | 2.41.2 | npm `latest`, and the version `n8n@2.41.3` pins |
| `n8n-nodes-base` | 2.41.2 | The version `n8n@2.41.3` pins. npm's `latest` tag for this package is stale at 2.15.1. I also checked 2.15.1 and found the same results for every node used here. |
| `n8n-core` | 2.41.2 | Read only to confirm how the fallback-model input is resolved (`getInputConnectionData`) |

`n8n@2.41.3` is the current npm `latest` and `stable` release.

## Verification table

"Params" lists the top-level `parameters` keys the workflow uses (plus nested option keys where relevant). A key passes if it is a property `name` in the node's description for that version.

| Node(s) | type | Version used | Supported versions | Params check |
|---|---|---|---|---|
| Webhook | `n8n-nodes-base.webhook` | 2 | 1, 1.1, 2, 2.1 | OK: `httpMethod`, `path`, `responseMode` (`responseNode`; this property is shown for versions 1, 1.1 and 2), `options`. `webhookId` is a node-level field. |
| Manual Trigger | `n8n-nodes-base.manualTrigger` | 1 | 1 | OK (no parameters) |
| Test Input, Normalize Request, Build Draft Input, Deterministic Checks, Compute Verdict, Prepare Revision | `n8n-nodes-base.set` | 3.4 | 3, 3.1, 3.2, 3.3, 3.4, 3.5 (the 2.15.1 package stops at 3.4) | OK: `mode` (`manual`), `assignments` (an assignmentCollection, versions 3.3 and later), `includeOtherFields` (3.3 and later), `options`. The assignment types are string, number, boolean, array and object. |
| Needs Research?, Approved?, Rounds Left? | `n8n-nodes-base.if` | 2.2 | 1, 2, 2.1, 2.2, 2.3 | OK: `conditions` (filter; version 2.2 uses filter version 2, which matches `conditions.options.version: 2`), `looseTypeValidation` (root level, 2.1 and later), `options` |
| IntakeAgent, DraftAgent, ReviewAgent, DispatchAgent | `@n8n/n8n-nodes-langchain.chainLlm` | 1.5 | 1, 1.1 … 1.9 | OK: `promptType` (`define`; the deprecated options list applies to 1.4–1.7), `text`, `hasOutputParser`, `needsFallback` (hidden only for 1, 1.1 and 1.3), `messages.messageValues[].{type, message}` (`SystemMessagePromptTemplate` is a valid type value) |
| ResearchAgent | `@n8n/n8n-nodes-langchain.agent` | **2.2** (was 1.7) | V1: 1–1.9 · V2: 2, 2.1, 2.2 · V3: 3, 3.1 (default 3.1) | OK: `promptType` (`define`), `text`, `needsFallback` (2.1 and later), `options.systemMessage`, `options.maxIterations`. The `agent: toolsAgent` key was removed because V2 has no such property; V2 is always the Tools Agent. |
| Groq Intake/Research/Draft/Review/Dispatch, Groq Fallback Intake/Research/Draft/Review/Dispatch | `@n8n/n8n-nodes-langchain.lmChatGroq` | 1 | 1 | OK: `model` (an options field that loads its list from `/models`, so a plain string ID is valid), `options.maxTokensToSample` (passed to `ChatGroq` as `maxTokens`), `options.temperature` (0–1, one decimal place) |
| Intake/Draft/Review/Dispatch Parser | `@n8n/n8n-nodes-langchain.outputParserStructured` | 1.2 | 1, 1.1, 1.2, 1.3 | OK: `schemaType` (`manual`, 1.2 and later), `inputSchema` |
| Wikipedia | `@n8n/n8n-nodes-langchain.toolWikipedia` | 1 | 1 | OK (no parameters) |
| Tavily Search | `@n8n/n8n-nodes-langchain.toolHttpRequest` | 1.1 | 1, 1.1 | OK: `toolDescription`, `method`, `url`, `authentication` (`genericCredentialType`), `genericAuthType` (`httpHeaderAuth`), `sendBody`, `specifyBody`, `parametersBody` (changed from `jsonBody`), `placeholderDefinitions.values[].{name, description, type}`. **Note:** the node is `hidden: true`, which means it is not in the node picker; n8n recommends `n8n-nodes-base.httpRequestTool`. It still loads and runs. |
| Respond Delivered, Respond Escalated | `n8n-nodes-base.respondToWebhook` | 1.1 | 1, 1.1, 1.2, 1.3, 1.4, 1.5 | OK: `respondWith` (`json`), `responseBody` (a string is parsed with `jsonParse`), `options.responseCode` |
| Notes: Overview / Credentials / Fallback model | `n8n-nodes-base.stickyNote` | 1 | 1 | OK: `content`, `height`, `width`, `color` |

The node-level fields `retryOnFail`, `maxTries`, `waitBetweenTries`, `webhookId` and `credentials` are part of the standard `INode` shape. They are not node properties, so no description was checked for them.

## Mismatches found and fixed

1. **ResearchAgent: `agent` 1.7 had no fallback-model input.** The AI Agent's fallback input exists only in V2.1 and later.
   - Changed `typeVersion` from 1.7 to 2.2 and removed the `agent: "toolsAgent"` key.
   - I chose 2.2 over 3.1 because it is the lowest version that supports a fallback model while keeping the Tools Agent executor.
2. **Tavily Search: the `jsonBody` template `{"query": "{query}", ...}` did no escaping.**
   - In v1.1, a string placeholder that is already inside quotes in a JSON body is replaced as raw text, with no escaping (`utils.js`, `configureToolFunction`). A model query containing `"` or `\` would give invalid JSON. `repairJSON` might or might not recover it.
   - Switched to `specifyBody: "keypair"` with `parametersBody.values = [{name: "query", valueProvider: "modelRequired"}]`. The node then sets the value into the body object, so it is encoded as a proper JSON string.
   - `max_results` and `search_depth` were dropped, so Tavily's defaults apply (5 and "basic", the same values as before). A keypair "fieldValue" would have sent `max_results` as the string "5".
3. No other type, version or parameter name mismatches were found.

## Fallback model

Both of the node types that need a fallback now have one:

- **chainLlm 1.5:** the `needsFallback` property is available. `getInputs` adds a second `ai_languageModel` input, "Fallback Model", when it is true. `chainExecutor` wraps the model in `llm.withFallbacks([fallbackLlm])`.
- **agent 2.2:** same input layout. The Tools Agent executor is built with the fallback model.

Changes made:

- `needsFallback: true` is set on IntakeAgent, ResearchAgent, DraftAgent, ReviewAgent and DispatchAgent.
- New nodes `Groq Fallback Intake`, `Groq Fallback Research`, `Groq Fallback Draft`, `Groq Fallback Review` and `Groq Fallback Dispatch` were added:
  - type `lmChatGroq` v1, model `qwen/qwen3.8-27b`
  - credential `groqApi` "DraftStudio Groq", id `REPLACE_ME`
  - the same options as the matching primary node
- Each fallback node is connected as `ai_languageModel` with `index: 1` to its root node.
- n8n-core's `validateInputConfiguration` reads `ai_languageModel` connections by input index: 0 is Chat Model, 1 is Fallback Model. Both are `required` when `needsFallback` is on.

## Other edits in this task

- **`maxTokensToSample`:** set to Intake 4000, Research 12000, Draft 12000, Review 10000 and Dispatch 3000. The fallback nodes use the same values.
- **Loop references:** `$('Deterministic Checks').item` became `$('Deterministic Checks').last()` in Compute Verdict (14 uses). `$('Compute Verdict').item` became `$('Compute Verdict').last()` in Respond Delivered (6 uses).
- **Sticky note:** "Notes: Fallback model" and `docs/n8n_workflow_design.md` were updated to match.

## Findings recorded without a change

- **chainLlm escapes braces.** `promptUtils.js` doubles every `{`/`}` in Chat Messages before building the template, and the user prompt is passed as the `{query}` variable. The earlier doc warning about braces in chain system messages was wrong for this version and has been corrected.
- **Output wrapping.** chainLlm 1.5 still gives `{output: <parsed object>}` when an output parser is connected, because `shouldUnwrapObjects` is true when a parser is present. The existing `$json.output` references are therefore right.
- **Newer versions exist.** Newer versions are available: chainLlm 1.9, agent 3.1, set 3.5, if 2.3, webhook 2.1 and respondToWebhook 1.5. They are not needed here; every version used is still supported.

## Update: fallback models moved to OpenRouter

The five `Groq Fallback <Agent>` nodes above were replaced by `OpenRouter Fallback <Agent>` nodes:

- type `@n8n/n8n-nodes-langchain.lmChatOpenRouter` v1, model `openai/gpt-oss-20b`
- credential `openRouterApi` "DraftStudio OpenRouter", id `REPLACE_ME`
- `options.maxTokens` (same values as the old `maxTokensToSample`) and `options.temperature` 0.3
- still wired as `ai_languageModel` with `index: 1` to the same root nodes

Reason: execution 377 hit Groq's 8000 tokens-per-minute cap, and the Groq fallback was rate-limited
at the same time. Unlike the section above, this node type and its option names were checked
against the n8n-mcp node catalog (`get_node`), not against the published package source, and the
model against OpenRouter's public `/models` list (`tools` supported, `max_completion_tokens` 32768).
