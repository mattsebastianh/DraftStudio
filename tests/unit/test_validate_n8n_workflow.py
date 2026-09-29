"""Unit tests for scripts/validate_n8n_workflow.py (stdlib unittest)."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "validate_n8n_workflow.py"

_spec = importlib.util.spec_from_file_location("validate_n8n_workflow", SCRIPT)
vnw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vnw)


def _node(name, node_type, node_id=None, **extra):
    node = {
        "id": node_id or f"id-{name}",
        "name": name,
        "type": node_type,
        "typeVersion": 1,
        "position": [0, 0],
        "parameters": {},
    }
    node.update(extra)
    return node


def minimal_workflow():
    return {
        "name": "Test",
        "nodes": [
            _node("Webhook", "n8n-nodes-base.webhook"),
            _node("Set", "n8n-nodes-base.set",
                  parameters={"value": "={{ $json.body.request }}"}),
            _node("Agent", "@n8n/n8n-nodes-langchain.agent"),
            _node("Model", "@n8n/n8n-nodes-langchain.lmChatGroq",
                  credentials={"groqApi": {"id": "1", "name": "Groq"}}),
            _node("Note", "n8n-nodes-base.stickyNote"),
        ],
        "connections": {
            "Webhook": {"main": [[{"node": "Set", "type": "main", "index": 0}]]},
            "Set": {"main": [[{"node": "Agent", "type": "main", "index": 0}]]},
            "Model": {"ai_languageModel": [[
                {"node": "Agent", "type": "ai_languageModel", "index": 0}]]},
        },
    }


def errors_text(wf):
    return "\n".join(vnw.validate(wf))


class ValidateTests(unittest.TestCase):
    def test_minimal_valid_workflow_passes(self):
        self.assertEqual(vnw.validate(minimal_workflow()), [])

    def test_missing_top_level_key(self):
        wf = minimal_workflow()
        del wf["connections"]
        self.assertIn("connections", errors_text(wf))

    def test_duplicate_node_names(self):
        wf = minimal_workflow()
        wf["nodes"][1]["name"] = "Webhook"
        self.assertIn("duplicate node name", errors_text(wf).lower())

    def test_duplicate_node_ids(self):
        wf = minimal_workflow()
        wf["nodes"][1]["id"] = wf["nodes"][0]["id"]
        self.assertIn("duplicate node id", errors_text(wf).lower())

    def test_missing_node_fields(self):
        wf = minimal_workflow()
        wf["nodes"][1]["typeVersion"] = "1"
        wf["nodes"][1]["position"] = [0]
        wf["nodes"][1]["parameters"] = []
        text = errors_text(wf)
        self.assertIn("typeVersion", text)
        self.assertIn("position", text)
        self.assertIn("parameters", text)

    def test_missing_type(self):
        wf = minimal_workflow()
        del wf["nodes"][1]["type"]
        self.assertIn("type", errors_text(wf))

    def test_non_native_type(self):
        wf = minimal_workflow()
        wf["nodes"][1]["type"] = "n8n-nodes-community.thing"
        text = errors_text(wf)
        self.assertIn("non-native", text.lower())
        self.assertIn("n8n-nodes-community.thing", text)

    def test_forbidden_code_nodes(self):
        for bad in ("code", "function", "functionItem", "executeCommand"):
            with self.subTest(bad=bad):
                wf = minimal_workflow()
                wf["nodes"][1]["type"] = f"n8n-nodes-base.{bad}"
                text = errors_text(wf)
                self.assertIn("forbidden", text.lower())
                self.assertIn(f"n8n-nodes-base.{bad}", text)

    def test_unknown_connection_target(self):
        wf = minimal_workflow()
        wf["connections"]["Set"]["main"][0][0]["node"] = "Ghost"
        text = errors_text(wf)
        self.assertIn("unknown", text.lower())
        self.assertIn("Ghost", text)

    def test_unknown_connection_source(self):
        wf = minimal_workflow()
        wf["connections"]["Phantom"] = {
            "main": [[{"node": "Set", "type": "main", "index": 0}]]}
        text = errors_text(wf)
        self.assertIn("unknown", text.lower())
        self.assertIn("Phantom", text)

    def test_invalid_connection_type(self):
        wf = minimal_workflow()
        wf["connections"]["Model"] = {"ai_bogus": [[
            {"node": "Agent", "type": "ai_bogus", "index": 0}]]}
        self.assertIn("ai_bogus", errors_text(wf))

    def test_unreachable_node(self):
        wf = minimal_workflow()
        wf["nodes"].append(_node("Orphan", "n8n-nodes-base.set"))
        text = errors_text(wf)
        self.assertIn("unreachable", text.lower())
        self.assertIn("Orphan", text)

    def test_sticky_note_not_required_reachable(self):
        wf = minimal_workflow()
        wf["nodes"].append(_node("Note2", "n8n-nodes-base.stickyNote"))
        self.assertEqual(vnw.validate(wf), [])

    def test_trigger_type_counts_as_root(self):
        wf = minimal_workflow()
        wf["nodes"].append(_node("Manual", "n8n-nodes-base.manualTrigger"))
        self.assertEqual(vnw.validate(wf), [])

    def test_credentials_need_id_and_name(self):
        wf = minimal_workflow()
        wf["nodes"][3]["credentials"] = {"groqApi": {"name": "Groq"}}
        text = errors_text(wf)
        self.assertIn("credential", text.lower())
        self.assertIn("id", text)

    def test_secret_pattern_detected(self):
        for secret in ("gsk_" + "A" * 12, "tvly-" + "b" * 12, "sk-" + "c" * 24):
            with self.subTest(secret=secret[:5]):
                wf = minimal_workflow()
                wf["nodes"][1]["parameters"]["apiKey"] = secret
                self.assertIn("secret", errors_text(wf).lower())

    def test_unbalanced_expression_braces(self):
        wf = minimal_workflow()
        wf["nodes"][1]["parameters"]["value"] = "={{ $json.body.request }"
        text = errors_text(wf)
        self.assertIn("unbalanced", text.lower())


class CliTests(unittest.TestCase):
    def _run(self, wf):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(wf, fh)
            path = fh.name
        try:
            return subprocess.run([sys.executable, str(SCRIPT), path],
                                  capture_output=True, text=True)
        finally:
            Path(path).unlink()

    def test_cli_ok(self):
        result = self._run(minimal_workflow())
        self.assertEqual(result.returncode, 0)
        self.assertIn("OK: 5 nodes", result.stdout)

    def test_cli_errors_exit_1(self):
        wf = copy.deepcopy(minimal_workflow())
        wf["nodes"][1]["type"] = "n8n-nodes-base.code"
        result = self._run(wf)
        self.assertEqual(result.returncode, 1)
        self.assertIn("n8n-nodes-base.code", result.stdout)


if __name__ == "__main__":
    unittest.main()
