"""Behaviour tests for the n8n quality gate (executions 378-380).

The workflow's own expressions are evaluated in Node.js with a stub for $json / $('Node'), so these
tests exercise the real logic in n8n/draftstudio_pipeline.workflow.json, not a Python copy of it.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / "n8n" / "draftstudio_pipeline.workflow.json"
NODE = shutil.which("node")

MEMO_REQUEST = (
    "Write a memo to all staff announcing that the office will close at 3pm on Fridays starting next month. "
    'Requirements: exactly 500 words, include a bulleted list of at least four items, and end with the sentence '
    '"Thank you for your flexibility."'
)


def _nodes():
    return {n["name"]: n for n in json.loads(WORKFLOW.read_text())["nodes"]}


def _assignment(node_name, field):
    for a in _nodes()[node_name]["parameters"]["assignments"]["assignments"]:
        if a["name"] == field:
            return a["value"]
    raise KeyError(f"{node_name}.{field}")


def _evaluate(expression, json_item, nodes=None):
    """Evaluate an n8n `={{ ... }}` expression in Node with minimal $json / $('Name') stubs."""
    body = expression.strip()
    assert body.startswith("={{") and body.endswith("}}"), body[:40]
    body = body[3:-2]
    script = f"""
const J = {json.dumps(json_item)}, NODES = {json.dumps(nodes or {})};
const $json = J;
const $ = (n) => ({{ first: () => ({{ json: NODES[n] }}), last: () => ({{ json: NODES[n] }}),
  isExecuted: Object.prototype.hasOwnProperty.call(NODES, n) }});
const $execution = {{ id: '1' }};
console.log(JSON.stringify(({body})));
"""
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=20)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def _words(n, tail=""):
    return " ".join(["word"] * n) + (" " + tail if tail else "")


@unittest.skipUnless(NODE, "node is required to evaluate n8n expressions")
class ConstraintCheckTests(unittest.TestCase):
    """Deterministic Checks turns the request's hard constraints into constraint_failures."""

    def failures(self, content, request=MEMO_REQUEST):
        expr = _assignment("Deterministic Checks", "constraint_failures")
        return _evaluate(
            expr, {"output": {"draft": {"content": content}}}, {"Build Draft Input": {"raw_request": request}}
        )

    def good_memo(self, ending="Thank you for your flexibility."):
        bullets = "\n".join(f"- item {i}" for i in range(1, 6))
        filler = _words(480)
        return f"{filler}\n\n{bullets}\n\n{ending}"

    def test_compliant_memo_has_no_failures(self):
        self.assertEqual(self.failures(self.good_memo()), [])

    def test_wrong_final_sentence_is_a_failure_execution_378(self):
        result = self.failures(self.good_memo("Thank you for your attention to this important update."))
        self.assertEqual(len(result), 1)
        self.assertIn("Thank you for your flexibility.", result[0])

    def test_markdown_emphasis_around_the_final_sentence_is_tolerated(self):
        self.assertEqual(self.failures(self.good_memo("**Thank you for your flexibility.**")), [])

    def test_text_after_the_final_sentence_is_a_failure(self):
        result = self.failures(self.good_memo() + "\n\nYour memo is attached.")
        self.assertTrue(any("end with" in f for f in result))

    def test_exact_word_count_allows_five_percent(self):
        # ~500 words +-5% (475-525) passes; 590 (execution 379 round 0) does not.
        far = self.failures(_words(560) + "\n- a\n- b\n- c\n- d\nThank you for your flexibility.")
        self.assertTrue(any("500" in f for f in far), far)

    def test_too_few_bullets_is_a_failure(self):
        content = _words(480) + "\n- one\n- two\n- three\n\nThank you for your flexibility."
        result = self.failures(content)
        self.assertTrue(any("bullet" in f for f in result), result)

    def test_number_words_are_understood_for_bullets(self):
        # "at least four items" (spelled out) must be enforced, not ignored.
        content = _words(480) + "\n- one\n- two\n\nThank you for your flexibility."
        self.assertTrue(any("4" in f for f in self.failures(content)))

    def test_request_without_constraints_has_no_failures(self):
        self.assertEqual(self.failures(_words(120), "Write a friendly note about the team lunch."), [])


@unittest.skipUnless(NODE, "node is required to evaluate n8n expressions")
class VerdictTests(unittest.TestCase):
    """Compute Verdict: approved only if score>=80 and nothing critical/high, no placeholder, length and constraints ok."""

    def verdict(self, score=90, issues=None, placeholder=False, length_ok=True, failures=None):
        review = {"score": score, "issues": issues or []}
        det = {
            "has_placeholder": placeholder,
            "length_ok": length_ok,
            "word_count": 500,
            "brief": {"length": "500 words"},
            "constraint_failures": failures or [],
        }
        nodes = {"Deterministic Checks": det}
        item = {"output": review}
        return (
            _evaluate(_assignment("Compute Verdict", "approved"), item, nodes),
            _evaluate(_assignment("Compute Verdict", "issues"), item, nodes),
        )

    def test_clean_high_score_is_approved(self):
        self.assertTrue(self.verdict()[0])

    def test_high_severity_issue_blocks_approval_execution_380(self):
        issue = {"severity": "high", "description": "wrong year", "suggested_fix": "fix"}
        self.assertFalse(self.verdict(score=86, issues=[issue])[0])

    def test_severity_case_is_ignored(self):
        issue = {"severity": "HIGH", "description": "d", "suggested_fix": "f"}
        self.assertFalse(self.verdict(issues=[issue])[0])

    def test_medium_and_low_issues_do_not_block(self):
        issues = [{"severity": "medium", "description": "d", "suggested_fix": "f"},
                  {"severity": "low", "description": "d", "suggested_fix": "f"}]
        self.assertTrue(self.verdict(issues=issues)[0])

    def test_each_deterministic_failure_blocks(self):
        self.assertFalse(self.verdict(score=79)[0])
        self.assertFalse(self.verdict(placeholder=True)[0])
        self.assertFalse(self.verdict(length_ok=False)[0])
        self.assertFalse(self.verdict(failures=["must end with X"])[0])

    def test_constraint_failures_become_critical_issues_with_a_fix(self):
        approved, issues = self.verdict(failures=['The draft must end with the sentence "Bye."'])
        critical = [i for i in issues if i["severity"] == "critical"]
        self.assertEqual(len(critical), 1)
        self.assertIn("Bye.", critical[0]["description"])
        self.assertTrue(critical[0]["suggested_fix"])


@unittest.skipUnless(NODE, "node is required to evaluate n8n expressions")
class ResearchFailureTests(unittest.TestCase):
    """A failed research run must not reach DraftAgent as if it were a dossier (execution 380)."""

    def run_field(self, field, research_output=None, executed=True):
        nodes = {"Normalize Request": {"raw_request": "r", "run_id": "1", "round": 0, "issues": []},
                 "IntakeAgent": {"output": {"brief": {}, "work_type": "draft_from_scratch"}}}
        if executed:
            nodes["ResearchAgent"] = {"output": research_output}
        return _evaluate(_assignment("Build Draft Input", field), {}, nodes)

    def test_max_iterations_message_is_scrubbed_and_flagged(self):
        out = "Agent stopped due to max iterations."
        self.assertEqual(self.run_field("dossier", out), "")
        self.assertTrue(self.run_field("research_failed", out))

    def test_real_dossier_passes_through(self):
        self.assertEqual(self.run_field("dossier", "Findings: ..."), "Findings: ...")
        self.assertFalse(self.run_field("research_failed", "Findings: ..."))

    def test_no_research_is_not_a_failure(self):
        self.assertEqual(self.run_field("dossier", executed=False), "")
        self.assertFalse(self.run_field("research_failed", executed=False))

    def test_research_failed_survives_a_revision_round(self):
        names = [a["name"] for a in _nodes()["Prepare Revision"]["parameters"]["assignments"]["assignments"]]
        self.assertIn("research_failed", names)

    def test_research_agent_gets_more_iterations(self):
        self.assertEqual(_nodes()["ResearchAgent"]["parameters"]["options"]["maxIterations"], 10)


class PromptAndReplyTests(unittest.TestCase):
    def setUp(self):
        self.nodes = _nodes()

    def test_draft_prompt_forbids_invented_details(self):
        text = self.nodes["DraftAgent"]["parameters"]["text"]
        self.assertIn("Do not invent", text)
        self.assertIn("research_failed", text)
        self.assertNotIn("flag unsupported claims", text)

    def test_review_prompt_matches_the_new_gate(self):
        text = self.nodes["ReviewAgent"]["parameters"]["text"]
        self.assertIn("critical or high", text)
        self.assertIn("constraint_failures", text)
        self.assertNotIn("non-critical issues do not block approval", text)

    def test_delivered_reply_is_the_deliverable_only(self):
        text = self.nodes["Telegram Reply Delivered"]["parameters"]["text"]
        self.assertNotIn("delivery_note", text)
        self.assertIn("draft.content", text)
        self.assertIn("substring(0, 4000)", text)
        self.assertTrue(text.startswith("={{ ('Approved"))

    def test_escalation_messages_describe_the_stricter_gate(self):
        body = self.nodes["Respond Escalated"]["parameters"]["responseBody"]
        tg = self.nodes["Telegram Reply Escalated"]["parameters"]["text"]
        self.assertIn("high", body)
        self.assertIn("high", tg)


if __name__ == "__main__":
    unittest.main()
