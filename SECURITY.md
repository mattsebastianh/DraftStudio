# Security Policy

## Reporting a vulnerability

Please report security issues privately, not in a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/mattsebastianh/DraftStudio/security/advisories/new)
for this repository. Include what you found, how to reproduce it, and the impact you expect.

I aim to acknowledge a report within 7 days. This is a personal project, so there is no bug bounty
and fixes are best effort.

## Scope

In scope: the Python harness (`harness/`), the n8n workflow (`n8n/`), and the agent and wire
definitions.

Things to know when running it:

- **Keys:** API keys belong in `.env`, which is gitignored. Never commit real keys. If you
  committed one by mistake, revoke it with the provider first; removing it from git is not enough.
- **n8n webhook:** the workflow's Webhook node requires Header Auth. Create the
  `DraftStudio Webhook` credential with a long random value before activating, and never set the
  node to no authentication: each run makes 5-13 LLM calls on your quota.
- **Telegram:** set *Restrict to Chat IDs* on the trigger to your own chat id. The imported
  placeholder rejects every message until you do.
- **Prompt injection:** request text goes into the agents' prompts. The n8n workflow's agents can
  call Wikipedia and Tavily search. The Python harness runs two tools for ResearchAgent,
  `web_search` (Tavily) and `fetch_url`. All of them are read-only, but the model writes the search
  query and, with `fetch_url`, chooses the URLs to fetch, so anything in a prompt can end up in a
  query or steer a request to an attacker-controlled public host. The harness fetches only public
  http(s) hosts: private, loopback, link-local and cloud-metadata addresses are refused, whether
  given directly, returned by DNS or reached through a redirect, so such a request cannot reach
  internal services. Fetched content is untrusted: it is truncated and wrapped in marker tags, and
  the agent is told never to follow instructions inside it. Do not put secrets in requests, and
  treat generated content as untrusted.

## Supported versions

Only the latest release receives fixes.
