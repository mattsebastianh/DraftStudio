"""Research sources in the n8n workflow (gaps 6-8 of the n8n modernization).

Verify Research ports harness/research.py enforce_sources: a finding survives only if it cites a URL the
research tools actually returned (read from the AI Agent's intermediate steps). Build Draft Input, Prepare
Revision and the Draft / Review / Dispatch prompts then carry the verified dossier and its sources, like
the harness wires (DraftAgent_to_ReviewAgent 1.2 `dossier`, ReviewAgent_to_DraftAgent 1.2 `sources`).
"""
import json
import shutil
import unittest
from pathlib import Path

from harness import research, urls
from tests.unit.test_n8n_checks_parity import evaluate_many

WORKFLOW = Path(__file__).resolve().parents[2] / "n8n" / "draftstudio_pipeline.workflow.json"
NODE = shutil.which("node")
INTAKE = {"output": {"brief": {"topic": "Remote work"}, "work_type": "full_service"}}


def _wf():
    return json.loads(WORKFLOW.read_text())


def _nodes():
    return {n["name"]: n for n in _wf()["nodes"]}


def _assignment(node_name, field):
    for a in _nodes()[node_name]["parameters"]["assignments"]["assignments"]:
        if a["name"] == field:
            return a["value"]
    raise KeyError(f"{node_name}.{field}")


def tavily(*results):
    """An intermediate step as the Tavily tool returns it: the HTTP response body as a string."""
    body = {"query": "q", "results": [{"title": t, "url": u, "content": "..."} for u, t in results]}
    return {"action": {"tool": "Tavily_Search", "toolInput": {"query": "q"}}, "observation": json.dumps(body)}


def wikipedia(*titles):
    """An intermediate step as the Wikipedia Search HTTP tool returns it (MediaWiki query API, formatversion 2)."""
    pages = [{"title": t, "fullurl": "https://en.wikipedia.org/wiki/" + t.replace(" ", "_"), "extract": "Some summary."} for t in titles]
    return {"action": {"tool": "Wikipedia_Search", "toolInput": {"query": "q"}}, "observation": json.dumps({"query": {"pages": pages}})}


def verify(output, steps=(), nodes=None):
    item = {"output": output, "intermediateSteps": list(steps)}
    return evaluate_many(_assignment("Verify Research", "research"), [{"json": item, "nodes": nodes or {"IntakeAgent": INTAKE}}])[0]


@unittest.skipUnless(NODE, "node is required to evaluate n8n expressions")
class VerifyResearchTests(unittest.TestCase):
    def test_matches_harness_enforce_sources(self):
        found = [("https://Example.com/report/", "  The <b>2026</b> {Report}  "), ("https://b.org/x#frag", "B")]
        dossiers = [
            {"topic": "model topic", "confidence": 80, "gaps": ["g"], "sources": [{"url": "https://made.up"}],
             "findings": [
                 {"claim": "kept", "sources": ["https://example.com/report", "https://made.up/x"], "confidence": 70, "notes": "n"},
                 {"claim": "dropped", "sources": ["https://made.up/y"], "confidence": 60},
                 {"claim": "kept twice", "sources": ["HTTPS://EXAMPLE.COM/report#a", "https://b.org/x"], "confidence": 65},
                 {"claim": "no sources", "confidence": 50},
             ]},
            {"topic": "t", "confidence": 90, "gaps": [], "sources": [], "findings": [{"claim": "c", "sources": ["https://x.io"], "confidence": 90}]},
            {"topic": "t", "confidence": 55.9, "gaps": [], "sources": [], "findings": []},
        ]
        evidence = {urls.normalize_url(u): {"url": u, "title": t, "excerpt": ""} for u, t in found}
        for dossier in dossiers:
            with self.subTest(dossier=dossier["findings"][:1]):
                expected, dropped = research.enforce_sources(dossier, evidence, topic="Remote work")
                got = verify(json.dumps(dossier), [tavily(*found)])
                self.assertTrue(got["verified"])
                self.assertEqual(got["dossier"], expected)
                self.assertEqual(got["dropped_findings"], dropped)

    def test_wikipedia_search_results_count_as_retrieved(self):
        dossier = {"topic": "t", "confidence": 70, "gaps": [], "sources": [],
                   "findings": [{"claim": "c", "sources": ["https://en.wikipedia.org/wiki/Remote_work"], "confidence": 70}]}
        got = verify(json.dumps(dossier), [wikipedia("Remote work", "Telecommuting")])
        self.assertEqual(got["dossier"]["sources"], [{"title": "Remote work", "url": "https://en.wikipedia.org/wiki/Remote_work"}])
        self.assertIn("https://en.wikipedia.org/wiki/Telecommuting", got["retrieved_urls"])

    def test_without_tool_calls_every_finding_is_dropped(self):
        dossier = {"topic": "t", "confidence": 90, "gaps": [], "sources": [{"url": "https://a.org"}],
                   "findings": [{"claim": "invented", "sources": ["https://a.org"], "confidence": 90}]}
        got = verify(json.dumps(dossier))
        self.assertEqual(got["dossier"]["findings"], [])
        self.assertEqual(got["dossier"]["sources"], [])
        self.assertEqual(got["dossier"]["confidence"], 40)
        self.assertIn("unsourced claim dropped: invented", got["dossier"]["gaps"])

    def test_text_around_the_json_and_a_dossier_wrapper_are_tolerated(self):
        text = 'Here:\n```json\n{"dossier": {"topic": "t", "confidence": 70, "gaps": [], "sources": [], "findings": [' \
               '{"claim": "c", "sources": ["https://a.org/p"], "confidence": 70}]}}\n```'
        got = verify(text, [tavily(("https://a.org/p", "A"))])
        self.assertEqual(len(got["dossier"]["findings"]), 1)

    def test_a_url_that_only_appears_in_page_text_does_not_count(self):
        # A link inside a snippet, an extract, a non-JSON observation or Wikipedia's editurl was not "returned by the tool".
        step = tavily(("https://real.org/page", "Real"))
        body = json.loads(step["observation"])
        body["results"][0]["content"] = "Read more at https://planted.example/offer and https://planted.example/b."
        step["observation"] = json.dumps(body)
        wiki = wikipedia("Remote work")
        page = json.loads(wiki["observation"])
        page["query"]["pages"][0].update({"editurl": "https://en.wikipedia.org/w/index.php?title=Remote_work&action=edit",
                                          "extract": "See https://planted.example/c for details."})
        wiki["observation"] = json.dumps(page)
        plain = {"action": {"tool": "Tavily_Search"}, "observation": "See https://plain.example/p, and more."}
        cited = ["https://real.org/page", "https://en.wikipedia.org/wiki/Remote_work", "https://planted.example/offer",
                 "https://planted.example/c", "https://en.wikipedia.org/w/index.php?title=Remote_work&action=edit",
                 "https://plain.example/p"]
        dossier = {"topic": "t", "confidence": 70, "gaps": [], "sources": [],
                   "findings": [{"claim": str(i), "sources": [u], "confidence": 70} for i, u in enumerate(cited)]}
        got = verify(json.dumps(dossier), [step, wiki, plain])
        self.assertEqual([f["claim"] for f in got["dossier"]["findings"]], ["0", "1"])
        self.assertEqual(sorted(got["retrieved_urls"]), sorted(["https://real.org/page", "https://en.wikipedia.org/wiki/Remote_work"]))
        self.assertEqual(got["dropped_findings"], 4)

    def test_unusable_output_is_not_verified(self):
        for output in ("Agent stopped due to max iterations.", "Just prose, no JSON.", None, "", "[1, 2]"):
            with self.subTest(output=output):
                got = verify(output)
                self.assertFalse(got["verified"])
                self.assertEqual(got["dossier"], {})

    def test_an_object_output_is_read_directly(self):
        got = verify({"topic": "t", "confidence": 50, "gaps": [], "sources": [], "findings": []})
        self.assertTrue(got["verified"])


@unittest.skipUnless(NODE, "node is required to evaluate n8n expressions")
class BuildDraftInputTests(unittest.TestCase):
    """Build Draft Input reads the verified dossier; anything else from research counts as a failure."""

    DOSSIER = {"topic": "t", "findings": [{"claim": "c", "sources": ["https://a.org"]}], "gaps": [], "confidence": 70,
               "sources": [{"title": "A", "url": "https://a.org"}]}

    def fields(self, research_ran=True, research=None):
        nodes = {"Normalize Request": {"raw_request": "r", "run_id": "1", "round": 0, "issues": []}, "IntakeAgent": INTAKE}
        if research_ran:
            nodes["ResearchAgent"] = {"output": "x"}
        if research is not None:
            nodes["Verify Research"] = {"research": research}
        names = ("dossier", "sources", "research_failed")
        return {n: evaluate_many(_assignment("Build Draft Input", n), [{"json": {}, "nodes": nodes}])[0] for n in names}

    def test_a_verified_dossier_reaches_the_drafter_as_json(self):
        got = self.fields(research={"verified": True, "dossier": self.DOSSIER})
        self.assertEqual(json.loads(got["dossier"]), self.DOSSIER)
        self.assertEqual(got["sources"], self.DOSSIER["sources"])
        self.assertFalse(got["research_failed"])

    def test_an_unverified_dossier_is_a_research_failure(self):
        got = self.fields(research={"verified": False, "dossier": {}})
        self.assertEqual((got["dossier"], got["sources"], got["research_failed"]), ("", [], True))

    def test_a_research_error_is_a_research_failure(self):
        got = self.fields(research=None)  # the error output skips Verify Research
        self.assertEqual((got["dossier"], got["sources"], got["research_failed"]), ("", [], True))

    def test_no_research_is_not_a_failure(self):
        got = self.fields(research_ran=False)
        self.assertEqual((got["dossier"], got["sources"], got["research_failed"]), ("", [], False))


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.wf = _wf()
        self.nodes = {n["name"]: n for n in self.wf["nodes"]}

    def test_research_agent_returns_its_tool_calls(self):
        self.assertIs(self.nodes["ResearchAgent"]["parameters"]["options"]["returnIntermediateSteps"], True)

    def test_wikipedia_is_an_http_request_tool_with_a_user_agent(self):
        # The built-in Wikipedia tool is answered with HTTP 429 (Node's default User-Agent): executions 401-403.
        self.assertNotIn("Wikipedia", self.nodes)
        tool = self.nodes["Wikipedia Search"]
        self.assertEqual(tool["type"], "n8n-nodes-base.httpRequestTool")
        # The local n8n 2.20.11 has HTTP Request versions up to 4.4; 4.5 (catalog of newer n8n) fails to activate.
        self.assertEqual(tool["typeVersion"], 4.4)
        params = tool["parameters"]
        self.assertEqual(params["url"], "https://en.wikipedia.org/w/api.php")
        headers = {h["name"]: h["value"] for h in params["headerParameters"]["parameters"]}
        self.assertTrue(headers["User-Agent"].startswith("DraftStudio"))
        query = {q["name"]: q["value"] for q in params["queryParameters"]["parameters"]}
        self.assertIn("$fromAI('query'", query["gsrsearch"])
        self.assertEqual((query["action"], query["generator"], query["inprop"], query["format"]), ("query", "search", "url", "json"))
        self.assertEqual([c["node"] for c in self.wf["connections"]["Wikipedia Search"]["ai_tool"][0]], ["ResearchAgent"])

    def test_tavily_search_is_enabled(self):
        tavily = self.nodes["Tavily Search"]
        self.assertFalse(tavily.get("disabled", False))
        self.assertEqual(tavily["credentials"]["httpHeaderAuth"]["name"], "DraftStudio Tavily")

    def test_verify_research_sits_on_the_success_output_only(self):
        out = self.wf["connections"]["ResearchAgent"]["main"]
        self.assertEqual([c["node"] for c in out[0]], ["Verify Research"])
        self.assertEqual([c["node"] for c in out[1]], ["Build Draft Input"])
        self.assertEqual([c["node"] for c in self.wf["connections"]["Verify Research"]["main"][0]], ["Build Draft Input"])

    def test_revision_carries_the_sources(self):
        self.assertEqual(_assignment("Prepare Revision", "sources"), "={{ $('Build Draft Input').first().json.sources }}")

    def test_prompts_carry_sources_and_dossier(self):
        self.assertIn("$json.sources", self.nodes["DraftAgent"]["parameters"]["text"])
        review = self.nodes["ReviewAgent"]["parameters"]["text"]
        self.assertIn("Research dossier", review)
        self.assertIn("$json.dossier", review)
        self.assertIn("sources", self.nodes["DispatchAgent"]["parameters"]["text"])

    def test_citations_check_reads_the_verified_sources(self):
        self.assertIn("$('Build Draft Input').first().json.sources", _assignment("Deterministic Checks", "citations_check"))


@unittest.skipUnless(NODE, "node is required to evaluate n8n expressions")
class PromptRenderingTests(unittest.TestCase):
    """The new prompt segments render the sources as a list, and say so when there are none."""

    def segment(self, node, marker):
        text = _nodes()[node]["parameters"]["text"]
        start = text.index("{{", text.index(marker))
        return "=" + text[start: text.index("}}", start) + 2]

    def test_draft_lists_the_sources_it_may_cite(self):
        expr = self.segment("DraftAgent", "Sources you may cite")
        got = evaluate_many(expr, [{"json": {"sources": [{"title": "A", "url": "https://a.org"}]}, "nodes": {}},
                                   {"json": {"sources": []}, "nodes": {}}])
        self.assertEqual(got[0], "- A: https://a.org")
        self.assertIn("none", got[1])

    def test_dispatch_lists_the_sources(self):
        expr = self.segment("DispatchAgent", "Research sources")
        nodes = {"Build Draft Input": {"sources": [{"title": "A", "url": "https://a.org"}]}}
        self.assertEqual(evaluate_many(expr, [{"json": {}, "nodes": nodes}])[0], "- https://a.org")


if __name__ == "__main__":
    unittest.main()
