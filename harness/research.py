"""ResearchAgent runner: a capped tool loop, then a schema-enforced dossier whose every source is a URL the
tools actually returned. Fails soft: without a search key, or when nothing could be retrieved, it returns an
empty dossier whose gaps say why, instead of unsourced claims."""

import json

from harness import config, schemas, tools
from harness.llm import build_messages
from harness.urls import normalize_url

TOOL_TURN_MAX_TOKENS = 4_000  # tool-calling turns are short; the dossier call gets the agent's full budget
DIGEST_ITEM_CHARS = 1_200
DIGEST_MAX_CHARS = 9_000
NOTES_MAX_CHARS = 3_000


def empty_dossier(topic, reason):
    return {"topic": topic, "findings": [], "gaps": [f"research unavailable: {reason}"], "confidence": 30, "sources": []}


def enforce_sources(dossier, evidence):
    """Keep only findings that cite a URL the tools returned; record the rest as gaps.

    `evidence` maps normalized URL -> {"url", "title", "excerpt"}. Returns (dossier, dropped_count). The
    dossier has exactly the ResearchAgent_to_DraftAgent fields, with the source list rebuilt from the kept
    findings.
    """
    kept, dropped = [], 0
    gaps = [str(gap) for gap in dossier.get("gaps", [])]
    for finding in dossier.get("findings", []):
        verified = []
        for source in finding.get("sources", []):
            item = evidence.get(normalize_url(str(source)))
            if item and item["url"] not in verified:
                verified.append(item["url"])
        if verified:
            kept.append({**finding, "sources": verified})
        else:
            dropped += 1
            gaps.append(f"unsourced claim dropped: {finding.get('claim', '')}")
    sources = []
    for finding in kept:
        for url in finding["sources"]:
            if all(source["url"] != url for source in sources):
                sources.append({"title": evidence[normalize_url(url)]["title"], "url": url})
    confidence = int(dossier.get("confidence", 0))
    if not kept:
        confidence = min(confidence, 40)
    clean = {"topic": str(dossier.get("topic", "")), "findings": kept, "gaps": gaps, "confidence": confidence, "sources": sources}
    return clean, dropped


def evidence_digest(evidence):
    """The retrieved sources as one compact, untrusted block for the dossier-writing call."""
    entries, used = [], 0
    for number, item in enumerate(evidence.values(), 1):
        entry = f"[{number}] {item['title'] or '(untitled)'}\nURL: {item['url']}\n{item['excerpt'][:DIGEST_ITEM_CHARS]}"
        if used + len(entry) > DIGEST_MAX_CHARS:
            break
        entries.append(entry)
        used += len(entry)
    return tools.wrap_untrusted("\n\n".join(entries))


def run_research(client, env, system_prompt, wire_message, toolbox=None):
    """Return (dossier, meta); the dossier is shaped like the ResearchAgent_to_DraftAgent wire."""
    topic = wire_message["topic"]
    if toolbox is None and not tools.search_available(env):
        reason = "web search unavailable (SEARCH_API_KEY not set)"
        meta = {"skipped": True, "reason": reason, "dropped_findings": 0, "sources_retrieved": 0, "tool_calls": []}
        return empty_dossier(topic, reason), meta
    toolbox = toolbox or tools.ToolBox(env)
    max_tokens, effort = config.AGENT_BUDGETS["ResearchAgent"]
    incoming = "Incoming message on wire `IntakeAgent_to_ResearchAgent`:\n\n" + json.dumps(wire_message, indent=2)
    search_prompt = (
        incoming
        + f"\n\nGather evidence with web_search and fetch_url (at most {config.MAX_TOOL_CALLS} calls in total). "
        + tools.UNTRUSTED_NOTE
        + " When you have enough evidence, stop calling tools and summarize what you found, citing the URLs."
    )
    _, final, loop_meta = client.chat_with_tools(
        build_messages(system_prompt, search_prompt), tools.tool_defs(), toolbox.run, config.MAX_TOOL_CALLS, TOOL_TURN_MAX_TOKENS, effort
    )
    meta = {
        "skipped": False,
        "sources_retrieved": len(toolbox.evidence),
        "tool_calls": loop_meta["tool_calls"],
        "tool_loop_usage": loop_meta["usage"],
    }
    if not toolbox.evidence:
        reason = "no sources could be retrieved"
        return empty_dossier(topic, reason), {**meta, "skipped": True, "reason": reason, "dropped_findings": 0}
    dossier_prompt = (
        incoming
        + "\n\nSources retrieved in the search phase:\n"
        + evidence_digest(toolbox.evidence)
        + "\n\nYour notes from the search phase:\n"
        + (final["content"] or "(none)")[:NOTES_MAX_CHARS]
        + "\n\n"
        + tools.UNTRUSTED_NOTE
        + " Return the research dossier as one JSON object: topic, findings (array of {claim, sources, "
        "confidence 0-100, notes}), gaps, confidence (0-100) and sources (array of {title, url}). Each finding's "
        "`sources` must list URLs from the retrieved sources above; a claim you cannot tie to one of them belongs "
        "in `gaps`, not in `findings`. Respond with ONLY valid JSON."
    )
    dossier, call_meta = client.chat_structured(
        build_messages(system_prompt, dossier_prompt), schemas.output_schema("ResearchAgent"), "ResearchAgent", max_tokens, effort
    )
    dossier, dropped = enforce_sources(dossier, toolbox.evidence)
    return dossier, {**meta, **call_meta, "dropped_findings": dropped}
