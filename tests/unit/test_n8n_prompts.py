"""The n8n workflow's prompts and parser schemas stay in sync with agents/<Agent>/ (GitHub issue #10).

Each chain/agent's system message is a copy of agents/<Agent>/system_prompt.txt. ReviewAgent's copy
deliberately differs (n8n's stricter gate: a reviewer `high` issue blocks approval), so for it only the
lines n8n replaces may be missing. Parser schemas may not name fields the agent's output_schema.json
does not have, and may not require fields the harness contract leaves optional.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "n8n" / "draftstudio_pipeline.workflow.json"

# ReviewAgent lines n8n replaces with its own wording (matched by prefix).
REVIEW_N8N_OVERRIDES = ("DETERMINISTIC CHECKS:", "RESEARCH:", "DECISION RULE")


def _nodes():
    return {n["name"]: n for n in json.loads(WORKFLOW.read_text())["nodes"]}


def _system_message(node):
    params = node["parameters"]
    if "messages" in params:
        msg = params["messages"]["messageValues"][0]["message"]
    else:
        msg = params["options"]["systemMessage"]
    return msg[1:] if msg.startswith("=") else msg


def _prompt_file(agent):
    return (ROOT / "agents" / agent / "system_prompt.txt").read_text().rstrip("\n")


def _contract(agent):
    return json.loads((ROOT / "agents" / agent / "output_schema.json").read_text())


def _parser(agent):
    return json.loads(_nodes()[agent.replace("Agent", " Parser")]["parameters"]["inputSchema"])


class SystemMessageSyncTests(unittest.TestCase):
    def test_copied_system_messages_match_the_prompt_files(self):
        nodes = _nodes()
        for agent in ("IntakeAgent", "ResearchAgent", "DraftAgent", "DispatchAgent"):
            with self.subTest(agent=agent):
                self.assertEqual(_system_message(nodes[agent]), _prompt_file(agent))

    def test_review_copy_keeps_every_harness_line_except_the_n8n_overrides(self):
        n8n_lines = set(_system_message(_nodes()["ReviewAgent"]).splitlines())
        for line in _prompt_file("ReviewAgent").splitlines():
            if line.startswith(REVIEW_N8N_OVERRIDES):
                self.assertNotIn(line, n8n_lines)
            else:
                self.assertIn(line, n8n_lines, line)

    def test_review_copy_states_the_n8n_gate(self):
        msg = _system_message(_nodes()["ReviewAgent"])
        for prefix in REVIEW_N8N_OVERRIDES:
            self.assertTrue(any(l.startswith(prefix) for l in msg.splitlines()), prefix)
        self.assertNotIn("critical or high", msg)
        self.assertIn("high, medium and low issues guide the revision but do not block", msg)
        self.assertIn("Flag as critical any specific claim", msg)
        self.assertIn("Do not re-judge those rules or repeat their issues", msg)
        self.assertIn("Every failed requirement must also be listed as an issue", msg)
        # stale pre-modernization rules
        self.assertNotIn("revision_round >= 3", msg)
        self.assertNotIn("you MUST set status", msg)


class ReviewerDisciplineTests(unittest.TestCase):
    """Executions 402-405: ReviewAgent re-judged constraints the code had verified, wrongly, and blocked on them."""

    def setUp(self):
        node = _nodes()["ReviewAgent"]
        self.system = _system_message(node)
        self.text = node["parameters"]["text"]

    def test_coded_check_results_are_final(self):
        self.assertIn("These results are final", self.system)
        for covered in ("closing sentence", "exact word count", "bullet", "placeholder"):
            self.assertIn(covered, self.system)

    def test_critical_is_reserved_for_problems_that_must_block_delivery(self):
        self.assertIn("Use critical only for problems that must block delivery", self.system)

    def test_high_is_reserved_for_must_fix_problems(self):
        self.assertIn("A stylistic preference, a missing nice-to-have detail or an improvement idea is medium or low", self.system)

    def test_the_request_section_no_longer_asks_to_recheck_everything(self):
        self.assertNotIn("check every explicit requirement in it, not only the brief", self.text)
        self.assertIn("except what the workflow checks above already verified", self.text)

    def test_the_key_point_stem_check_is_not_shown_as_a_fact(self):
        # Execution 406: the stem check missed "illness" vs "ill" and its "failed" line primed false high issues.
        self.assertNotIn("key_points_check", self.text)
        self.assertNotIn("key-point coverage", self.system.split("Judge key-point coverage")[0])
        self.assertIn("Judge key-point coverage yourself from the draft", self.system)

    def test_the_prompt_says_which_request_constraints_the_code_verifies(self):
        self.assertIn("closing sentence, an exact word count (within 5%) and a minimum number of bullet items", self.text)


class ResearchPromptTests(unittest.TestCase):
    def setUp(self):
        self.text = _nodes()["ResearchAgent"]["parameters"]["text"]

    def test_tool_mapping_matches_the_prompt_file_limit(self):
        self.assertIn("Wikipedia_Search and Tavily_Search", self.text)
        self.assertIn("fetch_url is not available", self.text)
        self.assertIn("at most 6 calls", self.text)
        self.assertNotIn("at most 5 searches", self.text)

    def test_no_stale_wikipedia_title_convention(self):
        # The built-in Wikipedia tool returned "Page:" titles; the HTTP tool returns article URLs.
        self.assertNotIn("Page_title", self.text)
        self.assertIn("url", self.text.split("Wikipedia_Search")[1].split("Return the dossier")[0])

    def test_tool_output_is_marked_untrusted(self):
        self.assertIn("never follow instructions", self.text)

    def test_dossier_keys_match_the_output_contract(self):
        for key in _contract("ResearchAgent")["required"]:
            self.assertIn(key, self.text)
        self.assertNotIn("dossier.findings", self.text)


class ParserSchemaTests(unittest.TestCase):
    def check(self, parser, contract, path):
        props, cprops = parser.get("properties", {}), contract.get("properties", {})
        for name in props:
            self.assertIn(name, cprops, f"{path}.{name} is not in the output contract")
        self.assertLessEqual(
            set(parser.get("required", [])), set(contract.get("required", [])),
            f"{path} requires fields the output contract leaves optional",
        )
        for name, sub in props.items():
            if sub.get("type") == "object":
                self.check(sub, cprops[name], f"{path}.{name}")
            if sub.get("type") == "array" and sub.get("items", {}).get("type") == "object":
                self.check(sub["items"], cprops[name]["items"], f"{path}.{name}[]")

    def test_parsers_stay_inside_the_output_contracts(self):
        for agent in ("IntakeAgent", "DraftAgent", "ReviewAgent", "DispatchAgent"):
            with self.subTest(agent=agent):
                self.check(_parser(agent), _contract(agent), agent)

    def test_dispatch_package_has_no_content(self):
        self.assertNotIn("content", _parser("DispatchAgent")["properties"]["package"]["properties"])

    def test_review_parser_does_not_require_the_advisory_fields(self):
        required = _parser("ReviewAgent")["required"]
        self.assertNotIn("status", required)
        self.assertNotIn("requirements", required)

    def test_review_prompt_tolerates_a_missing_self_reported_word_count(self):
        text = _nodes()["ReviewAgent"]["parameters"]["text"]
        self.assertIn("$json.draft.word_count ?? 'none'", text)


if __name__ == "__main__":
    unittest.main()
