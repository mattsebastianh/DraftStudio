import json
import urllib.error

from harness import research, tools
from tests.unit.fakes import ENV, FakePost, body, make_client, opener_returning, public_resolve, tool_call

WIRE_MSG = {"topic": "EU AI Act", "focus_areas": ["scope"]}
REG_URL = "https://eur-lex.europa.eu/eli/reg/2024/1689/oj"
OTHER_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689"
EVIDENCE = {REG_URL: {"url": REG_URL, "title": "Regulation (EU) 2024/1689", "excerpt": "Artificial Intelligence Act"}}
SEARCH_ENV = {**ENV, "TAVILY_API_KEY": "real"}


def test_enforce_sources_keeps_only_retrieved_urls():
    dossier = {
        "topic": "t",
        "findings": [
            {"claim": "A", "sources": [REG_URL + "/"], "confidence": 80},  # same URL, trailing slash
            {"claim": "B", "sources": [], "confidence": 90},
            {"claim": "C", "sources": ["  "], "confidence": 70},
            {"claim": "D", "sources": [OTHER_URL], "confidence": 85},  # plausible, but never retrieved
        ],
        "gaps": ["g1"],
        "confidence": 80,
        "sources": [{"title": "made up", "url": "https://made.up/source"}],
        "summary": "extra field",
    }
    dossier["findings"][0]["url"] = "https://smuggled.example/"  # a key outside the wire's finding shape
    dossier["findings"][0]["notes"] = "kept"
    clean, dropped = research.enforce_sources(dossier, EVIDENCE)
    assert [f["claim"] for f in clean["findings"]] == ["A"]
    assert clean["findings"][0] == {"claim": "A", "sources": [REG_URL], "confidence": 80, "notes": "kept"}
    assert dropped == 3
    assert clean["gaps"] == ["g1", "unsourced claim dropped: B", "unsourced claim dropped: C", "unsourced claim dropped: D"]
    assert clean["sources"] == [{"title": "Regulation (EU) 2024/1689", "url": REG_URL}]
    assert set(clean) == {"topic", "findings", "gaps", "confidence", "sources"}
    assert clean["confidence"] == 80


def test_enforce_sources_topic_argument_wins_over_the_models():
    dossier = {"topic": "model's topic", "findings": [], "gaps": [], "confidence": 50, "sources": []}
    assert research.enforce_sources(dossier, EVIDENCE, topic="wire topic")[0]["topic"] == "wire topic"
    assert research.enforce_sources(dossier, EVIDENCE)[0]["topic"] == "model's topic"


def test_enforce_sources_all_dropped_lowers_confidence():
    dossier = {"topic": "t", "findings": [{"claim": "B", "sources": [], "confidence": 90}], "gaps": [], "confidence": 90, "sources": []}
    clean, dropped = research.enforce_sources(dossier, EVIDENCE)
    assert clean["findings"] == [] and dropped == 1 and clean["confidence"] <= 40


def test_empty_dossier_shape():
    assert research.empty_dossier("t", "no key") == {
        "topic": "t",
        "findings": [],
        "gaps": ["research unavailable: no key"],
        "confidence": 30,
        "sources": [],
    }


def test_evidence_digest_is_wrapped_and_bounded():
    evidence = {f"https://s{i}.com": {"url": f"https://s{i}.com", "title": f"S{i}", "excerpt": "x" * 5_000} for i in range(20)}
    digest = research.evidence_digest(evidence)
    assert digest.startswith("<untrusted_tool_output>") and "[1] S0" in digest
    assert len(digest) <= research.DIGEST_MAX_CHARS + 100


def test_run_research_fails_soft_without_search_key():
    post = FakePost()  # any model call would fail with IndexError
    dossier, meta = research.run_research(make_client(post), {}, "sys", WIRE_MSG)
    assert dossier["findings"] == [] and "TAVILY_API_KEY" in dossier["gaps"][0]
    assert post.calls == [] and meta["skipped"] is True and meta["dropped_findings"] == 0
    assert meta["retrieved_urls"] == []


def test_run_research_fails_soft_when_nothing_could_be_retrieved():
    def down(req, timeout=None):
        raise urllib.error.URLError("down")

    post = FakePost(body("", finish="tool_calls", tool_calls=tool_call("web_search", {"query": "EU AI Act"})), body("Nothing found."))
    box = tools.ToolBox(SEARCH_ENV, opener=down, resolve=public_resolve)
    dossier, meta = research.run_research(make_client(post, SEARCH_ENV), SEARCH_ENV, "sys", WIRE_MSG, toolbox=box)
    assert dossier == research.empty_dossier("EU AI Act", "no sources could be retrieved")
    assert len(post.calls) == 2 and meta["skipped"] is True and meta["tool_calls"][0]["ok"] is False
    assert meta["retrieved_urls"] == []


def test_run_research_keeps_only_findings_that_cite_retrieved_urls():
    search_body = {"results": [{"title": "Regulation (EU) 2024/1689", "url": REG_URL, "content": "Artificial Intelligence Act"}]}
    reply = {
        "topic": "EU AI Act",
        "findings": [
            {"claim": "The AI Act is Regulation (EU) 2024/1689", "sources": [REG_URL], "confidence": 90},
            {"claim": "Fabricated", "sources": [OTHER_URL], "confidence": 80},
        ],
        "gaps": [],
        "confidence": 80,
        "sources": [],
    }
    post = FakePost(
        body("", finish="tool_calls", tool_calls=tool_call("web_search", {"query": "EU AI Act"})),
        body("The regulation is on EUR-Lex."),
        body(json.dumps(reply)),
    )
    box = tools.ToolBox(SEARCH_ENV, opener=opener_returning(search_body), resolve=public_resolve)
    dossier, meta = research.run_research(make_client(post, SEARCH_ENV), SEARCH_ENV, "sys", WIRE_MSG, toolbox=box)
    assert [f["claim"] for f in dossier["findings"]] == ["The AI Act is Regulation (EU) 2024/1689"]
    assert dossier["sources"] == [{"title": "Regulation (EU) 2024/1689", "url": REG_URL}]
    assert dossier["topic"] == "EU AI Act" and meta["retrieved_urls"] == [REG_URL]
    assert meta["dropped_findings"] == 1 and meta["sources_retrieved"] == 1 and meta["skipped"] is False
    assert meta["schema_enforced"] is True
    dossier_call = post.payloads[2]["messages"]
    assert [m["role"] for m in dossier_call] == ["system", "user"]  # an evidence digest, not the raw transcript
    assert "<untrusted_tool_output>" in dossier_call[1]["content"] and REG_URL in dossier_call[1]["content"]
    assert "<untrusted_tool_output>\nThe regulation is on EUR-Lex.\n</untrusted_tool_output>" in dossier_call[1]["content"]
    assert "summary derived from untrusted web content" in dossier_call[1]["content"]


def test_run_research_takes_the_topic_from_the_wire_message_not_the_model():
    search_body = {"results": [{"title": "Reg", "url": REG_URL, "content": "text"}]}
    reply = {"topic": "something else", "findings": [], "gaps": [], "confidence": 50, "sources": []}
    post = FakePost(
        body("", finish="tool_calls", tool_calls=tool_call("web_search", {"query": "q"})), body("notes"), body(json.dumps(reply))
    )
    box = tools.ToolBox(SEARCH_ENV, opener=opener_returning(search_body), resolve=public_resolve)
    dossier, _ = research.run_research(make_client(post, SEARCH_ENV), SEARCH_ENV, "sys", WIRE_MSG, toolbox=box)
    assert dossier["topic"] == "EU AI Act"
