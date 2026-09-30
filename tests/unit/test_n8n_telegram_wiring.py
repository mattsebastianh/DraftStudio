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
        caps = {"Telegram Reply Delivered": "substring(0, 3900)", "Telegram Reply Escalated": "substring(0, 4000)"}
        for name, cap in caps.items():
            with self.subTest(node=name):
                node = self.nodes[name]
                self.assertEqual(node["type"], "n8n-nodes-base.telegram")
                params = node["parameters"]
                self.assertEqual(params["operation"], "sendMessage")
                self.assertIn("chat_id", params["chatId"])
                self.assertIn(cap, params["text"])
                self.assertNotIn("parseMode", params.get("additionalFields", {}))
                self.assertEqual(node["credentials"]["telegramApi"]["id"], "REPLACE_ME")

    def test_telegram_nodes_share_one_credential_name(self):
        names = {
            self.nodes[n]["credentials"]["telegramApi"]["name"]
            for n in self.nodes
            if self.nodes[n]["type"].startswith("n8n-nodes-base.telegram")
        }
        self.assertGreaterEqual(len([n for n in self.nodes if n.startswith("Telegram Reply")]), 6)
        self.assertEqual(names, {"DraftStudio Telegram"})


class IntakeFailureTests(unittest.TestCase):
    """A message the IntakeAgent cannot turn into a brief must get a reply, not a crash (execution 371)."""

    def setUp(self):
        self.nodes, self.conns = _load()

    def test_intake_errors_route_to_clarification_not_a_crash(self):
        self.assertEqual(self.nodes["IntakeAgent"].get("onError"), "continueErrorOutput")
        self.assertEqual(_targets(self.conns, "IntakeAgent", 0), ["Needs Research?"])
        self.assertEqual(_targets(self.conns, "IntakeAgent", 1), ["Intake Reply Unparseable?"])
        # only an unparseable model reply is "unclear"; any other failure is a service error
        self.assertEqual(_targets(self.conns, "Intake Reply Unparseable?", 0), ["Respond Needs Clarification"])
        self.assertEqual(_targets(self.conns, "Intake Reply Unparseable?", 1), ["Respond Service Error"])

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

    def test_only_the_reviewer_has_a_groq_fallback(self):
        # the four Groq-primary agents fall back to OpenRouter; the OpenRouter reviewer falls back to Groq
        self.assertEqual([n for n in self.nodes if n.startswith("Groq Fallback")], ["Groq Fallback Review"])

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

    def test_review_fallback_is_a_different_provider_and_model_family(self):
        node = self.nodes["Groq Fallback Review"]
        self.assertEqual(node["type"], "@n8n/n8n-nodes-langchain.lmChatGroq")
        model = node["parameters"]["model"]
        self.assertEqual(model, "llama-3.3-70b-versatile")
        # different provider from the primary judge (OpenRouter) and different family from qwen
        self.assertNotIn("qwen", model)
        self.assertEqual(node["parameters"]["options"]["temperature"], 0.1)
        cred = node["credentials"]["groqApi"]
        self.assertEqual((cred["id"], cred["name"]), ("REPLACE_ME", "DraftStudio Groq"))
        self.assertEqual(
            self._edges("Groq Fallback Review"),
            [{"node": "ReviewAgent", "type": "ai_languageModel", "index": 1}],
        )
        self.assertTrue(self.nodes["ReviewAgent"]["parameters"]["needsFallback"])

    def test_every_agent_has_two_different_llm_providers(self):
        providers = {}
        for src, conns in self.conns.items():
            for groups in conns.get("ai_languageModel", []):
                for edge in groups:
                    providers.setdefault(edge["node"], set()).add(self.nodes[src]["type"])
        self.assertEqual(len(providers), 5)
        for agent, types in providers.items():
            self.assertEqual(len(types), 2, agent)

    def test_old_review_model_nodes_are_gone(self):
        self.assertNotIn("Groq Review", self.nodes)
        self.assertNotIn("OpenRouter Fallback Review", self.nodes)


class TelegramSafetyTests(unittest.TestCase):
    """Review findings 1 and 7: fail closed on who may use the bot; never cut a deliverable silently."""

    def setUp(self):
        self.nodes, self.conns = _load()

    def test_trigger_is_restricted_to_a_chat_id_and_fails_closed(self):
        ids = self.nodes["Telegram Trigger"]["parameters"]["additionalFields"].get("chatIds")
        self.assertTrue(ids, "chatIds must be set so an unconfigured import rejects everyone")
        self.assertIn("REPLACE", ids)  # the committed file holds a placeholder, never a real chat id

    def test_long_deliverables_are_sent_in_up_to_three_parts(self):
        self.assertEqual(_targets(self.conns, "Telegram Reply Delivered"), ["More Text? (part 2)"])
        self.assertEqual(_targets(self.conns, "More Text? (part 2)", 0), ["Telegram Reply Delivered 2"])
        self.assertEqual(_targets(self.conns, "More Text? (part 2)", 1), [])
        self.assertEqual(_targets(self.conns, "Telegram Reply Delivered 2"), ["More Text? (part 3)"])
        self.assertEqual(_targets(self.conns, "More Text? (part 3)", 0), ["Telegram Reply Delivered 3"])
        self.assertEqual(_targets(self.conns, "More Text? (part 3)", 1), [])
        for name in ("Telegram Reply Delivered 2", "Telegram Reply Delivered 3"):
            self.assertEqual(self.nodes[name]["credentials"]["telegramApi"]["id"], "REPLACE_ME")


class ErrorRoutingTests(unittest.TestCase):
    """Review finding 6: an agent failure must produce a reply, and infra errors must not look like unclear requests."""

    def setUp(self):
        self.nodes, self.conns = _load()

    def test_every_agent_has_an_error_output(self):
        for agent in ("IntakeAgent", "ResearchAgent", "DraftAgent", "ReviewAgent", "DispatchAgent"):
            with self.subTest(agent=agent):
                self.assertEqual(self.nodes[agent].get("onError"), "continueErrorOutput")

    def test_research_failure_degrades_instead_of_aborting(self):
        self.assertEqual(_targets(self.conns, "ResearchAgent", 1), ["Build Draft Input"])

    def test_draft_review_dispatch_failures_reach_the_service_error_reply(self):
        for agent in ("DraftAgent", "ReviewAgent", "DispatchAgent"):
            with self.subTest(agent=agent):
                self.assertEqual(_targets(self.conns, agent, 1), ["Respond Service Error"])

    def test_service_error_is_a_500_for_webhook_and_a_telegram_message(self):
        respond = self.nodes["Respond Service Error"]["parameters"]
        self.assertEqual(respond["options"]["responseCode"], 500)
        self.assertIn("'error'", respond["responseBody"])
        self.assertEqual(_targets(self.conns, "Respond Service Error"), ["Reply on Telegram? (error)"])
        self.assertEqual(_targets(self.conns, "Reply on Telegram? (error)", 0), ["Telegram Reply Error"])
        self.assertEqual(_targets(self.conns, "Reply on Telegram? (error)", 1), [])
        text = self.nodes["Telegram Reply Error"]["parameters"]["text"]
        self.assertNotIn("$json.error", text)  # never leak internal error text to a chat user


if __name__ == "__main__":
    unittest.main()
