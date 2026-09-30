"""Wiring tests for the Telegram entry/reply added to the n8n DraftStudio workflow."""
import json
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / "n8n" / "draftstudio_pipeline.workflow.json"


def _load():
    w = json.loads(WORKFLOW.read_text())
    return {n["name"]: n for n in w["nodes"]}, w["connections"]


def _targets(conns, name, output=0):
    outs = conns.get(name, {}).get("main", [])
    if output >= len(outs):
        return []
    return [edge["node"] for edge in outs[output]]


class TelegramEntryTests(unittest.TestCase):
    def setUp(self):
        self.nodes, self.conns = _load()

    def test_trigger_listens_for_messages_only(self):
        node = self.nodes["Telegram Trigger"]
        self.assertEqual(node["type"], "n8n-nodes-base.telegramTrigger")
        self.assertEqual(node["parameters"]["updates"], ["message"])

    def test_trigger_filters_then_maps_then_normalizes(self):
        self.assertEqual(_targets(self.conns, "Telegram Trigger"), ["Has Request Text?"])
        self.assertEqual(_targets(self.conns, "Has Request Text?", 0), ["Telegram Input"])
        self.assertEqual(_targets(self.conns, "Has Request Text?", 1), [])
        self.assertEqual(_targets(self.conns, "Telegram Input"), ["Normalize Request"])

    def test_existing_entries_still_feed_normalize(self):
        self.assertEqual(_targets(self.conns, "Webhook"), ["Normalize Request"])
        self.assertEqual(_targets(self.conns, "Test Input"), ["Normalize Request"])

    def test_chat_id_comes_only_from_top_level_field_not_webhook_body(self):
        assignments = self.nodes["Normalize Request"]["parameters"]["assignments"]["assignments"]
        chat = next(a for a in assignments if a["name"] == "chat_id")
        self.assertIn("$json.telegram_chat_id", chat["value"])
        self.assertNotIn("body", chat["value"])
        mapped = self.nodes["Telegram Input"]["parameters"]["assignments"]["assignments"]
        self.assertIn("telegram_chat_id", [a["name"] for a in mapped])


class TelegramReplyTests(unittest.TestCase):
    def setUp(self):
        self.nodes, self.conns = _load()

    def test_each_terminal_reply_is_gated_on_chat_id(self):
        cases = {
            "Respond Delivered": ("Reply on Telegram? (delivered)", "Telegram Reply Delivered"),
            "Respond Escalated": ("Reply on Telegram? (escalated)", "Telegram Reply Escalated"),
        }
        for respond, (gate, send) in cases.items():
            with self.subTest(respond=respond):
                self.assertEqual(_targets(self.conns, respond), [gate])
                self.assertEqual(_targets(self.conns, gate, 0), [send])
                self.assertEqual(_targets(self.conns, gate, 1), [])
                self.assertIn("chat_id", json.dumps(self.nodes[gate]["parameters"]))

    def test_send_nodes_are_plain_text_and_capped(self):
        for name in ("Telegram Reply Delivered", "Telegram Reply Escalated"):
            with self.subTest(node=name):
                node = self.nodes[name]
                self.assertEqual(node["type"], "n8n-nodes-base.telegram")
                params = node["parameters"]
                self.assertEqual(params["operation"], "sendMessage")
                self.assertIn("chat_id", params["chatId"])
                self.assertIn("substring(0, 4000)", params["text"])
                self.assertNotIn("parseMode", params.get("additionalFields", {}))
                self.assertEqual(node["credentials"]["telegramApi"]["id"], "REPLACE_ME")

    def test_telegram_nodes_share_one_credential_name(self):
        names = {
            self.nodes[n]["credentials"]["telegramApi"]["name"]
            for n in ("Telegram Trigger", "Telegram Reply Delivered", "Telegram Reply Escalated")
        }
        self.assertEqual(names, {"DraftStudio Telegram"})


class IntakeFailureTests(unittest.TestCase):
    """A message the IntakeAgent cannot turn into a brief must get a reply, not a crash (execution 371)."""

    def setUp(self):
        self.nodes, self.conns = _load()

    def test_intake_errors_route_to_clarification_not_a_crash(self):
        self.assertEqual(self.nodes["IntakeAgent"].get("onError"), "continueErrorOutput")
        self.assertEqual(_targets(self.conns, "IntakeAgent", 0), ["Needs Research?"])
        self.assertEqual(_targets(self.conns, "IntakeAgent", 1), ["Respond Needs Clarification"])

    def test_clarification_is_returned_to_webhook_and_telegram(self):
        self.assertEqual(
            _targets(self.conns, "Respond Needs Clarification"),
            ["Reply on Telegram? (clarify)"],
        )
        self.assertEqual(
            _targets(self.conns, "Reply on Telegram? (clarify)", 0), ["Telegram Reply Clarify"]
        )
        self.assertEqual(_targets(self.conns, "Reply on Telegram? (clarify)", 1), [])
        body = self.nodes["Respond Needs Clarification"]["parameters"]["responseBody"]
        self.assertIn("needs_clarification", body)
        send = self.nodes["Telegram Reply Clarify"]
        self.assertEqual(send["credentials"]["telegramApi"]["id"], "REPLACE_ME")
        self.assertIn("chat_id", send["parameters"]["chatId"])


class RateLimitResilienceTests(unittest.TestCase):
    """Groq on_demand TPM limits (execution 377: 429 asking for ~7.5s) need a longer retry budget."""

    def test_agents_wait_long_enough_to_outlast_a_tpm_window_slice(self):
        nodes, _ = _load()
        for name in ("IntakeAgent", "ResearchAgent", "DraftAgent", "ReviewAgent", "DispatchAgent"):
            with self.subTest(node=name):
                node = nodes[name]
                self.assertTrue(node.get("retryOnFail"))
                self.assertGreaterEqual(node["maxTries"], 5)
                self.assertGreaterEqual(node["waitBetweenTries"], 5000)


class OpenRouterFallbackTests(unittest.TestCase):
    """Fallback models run on OpenRouter (a different provider), so a Groq 429 does not hit both."""

    # ReviewAgent is the exception: OpenRouter is its primary, Groq its fallback (see ReviewerModelTests).
    AGENTS = {"Intake": 4000, "Research": 12000, "Draft": 12000, "Dispatch": 3000}
    MODEL = "openai/gpt-oss-20b"

    def setUp(self):
        self.nodes, self.conns = _load()

    def test_no_groq_fallback_nodes_remain(self):
        self.assertEqual([n for n in self.nodes if n.startswith("Groq Fallback")], [])

    def test_each_agent_has_an_openrouter_fallback_on_its_second_model_input(self):
        for agent, max_tokens in self.AGENTS.items():
            with self.subTest(agent=agent):
                node = self.nodes[f"OpenRouter Fallback {agent}"]
                self.assertEqual(node["type"], "@n8n/n8n-nodes-langchain.lmChatOpenRouter")
                self.assertEqual(node["parameters"]["model"], self.MODEL)
                self.assertEqual(node["parameters"]["options"]["maxTokens"], max_tokens)
                cred = node["credentials"]["openRouterApi"]
                self.assertEqual((cred["id"], cred["name"]), ("REPLACE_ME", "DraftStudio OpenRouter"))
                edges = self.conns[node["name"]]["ai_languageModel"][0]
                self.assertEqual(edges, [{"node": f"{agent}Agent", "type": "ai_languageModel", "index": 1}])
                self.assertTrue(self.nodes[f"{agent}Agent"]["parameters"]["needsFallback"])

    def test_groq_primaries_are_untouched(self):
        for agent in self.AGENTS:
            with self.subTest(agent=agent):
                node = self.nodes[f"Groq {agent}"]
                self.assertEqual(node["type"], "@n8n/n8n-nodes-langchain.lmChatGroq")
                self.assertEqual(node["parameters"]["model"], "openai/gpt-oss-120b")


class ReviewerModelTests(unittest.TestCase):
    """The judge runs on a different model family and provider than the drafter, off Groq's TPM budget."""

    def setUp(self):
        self.nodes, self.conns = _load()

    def _edges(self, name):
        return self.conns[name]["ai_languageModel"][0]

    def test_review_primary_is_openrouter_qwen_at_low_temperature(self):
        node = self.nodes["OpenRouter Review"]
        self.assertEqual(node["type"], "@n8n/n8n-nodes-langchain.lmChatOpenRouter")
        self.assertEqual(node["parameters"]["model"], "qwen/qwen3-235b-a22b-2507")
        self.assertEqual(node["parameters"]["options"]["temperature"], 0.1)
        cred = node["credentials"]["openRouterApi"]
        self.assertEqual((cred["id"], cred["name"]), ("REPLACE_ME", "DraftStudio OpenRouter"))
        self.assertEqual(self._edges("OpenRouter Review"), [{"node": "ReviewAgent", "type": "ai_languageModel", "index": 0}])

    def test_review_fallback_is_a_third_family_non_reasoning_model_on_openrouter(self):
        node = self.nodes["OpenRouter Fallback Review"]
        self.assertEqual(node["type"], "@n8n/n8n-nodes-langchain.lmChatOpenRouter")
        model = node["parameters"]["model"]
        self.assertEqual(model, "meta-llama/llama-3.3-70b-instruct")
        # different family from the primary judge (qwen) and from the drafter (gpt-oss)
        self.assertNotIn("qwen", model)
        self.assertNotIn("gpt-oss", model)
        self.assertEqual(node["parameters"]["options"]["temperature"], 0.1)
        cred = node["credentials"]["openRouterApi"]
        self.assertEqual((cred["id"], cred["name"]), ("REPLACE_ME", "DraftStudio OpenRouter"))
        self.assertEqual(
            self._edges("OpenRouter Fallback Review"),
            [{"node": "ReviewAgent", "type": "ai_languageModel", "index": 1}],
        )
        self.assertTrue(self.nodes["ReviewAgent"]["parameters"]["needsFallback"])

    def test_old_review_model_nodes_are_gone(self):
        self.assertNotIn("Groq Review", self.nodes)
        self.assertNotIn("Groq Fallback Review", self.nodes)


if __name__ == "__main__":
    unittest.main()
