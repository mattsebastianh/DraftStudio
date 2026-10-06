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
    """Compute Verdict + Approved?: approved only if a valid score >= 80 and no blocking issue.

    Blocking, as in the harness: a critical ReviewAgent issue, a placeholder, a request-constraint failure, a
    malformed review. Everything the reviewer rates high (and a missed word-count target, issue #9, and a
    requirement it marks failed) guides the reviser but does not block. Executions 402-409: reviewer high
    issues were often wrong and escalated good drafts, so they stopped blocking.
    """

    def verdict(self, score=90, issues=None, placeholder=False, length_ok=True, failures=None,
                requirements=None, review=None, checks=None):
        if review is None:
            review = {"score": score, "issues": [] if issues is None else issues}
            if requirements is not None:
                review["requirements"] = requirements
        passed = {"id": "length", "passed": True, "severity": "low", "detail": "ok", "suggested_fix": ""}
        det = {
            "has_placeholder": placeholder,
            "length_check": passed if length_ok else {
                "id": "length", "passed": False, "severity": "high",
                "detail": "Draft is 300 words; the brief allows 425-575 words.", "suggested_fix": "Rewrite to 425-575 words."},
            "key_points_check": dict(passed, id="key_points_covered"),
            "citations_check": dict(passed, id="citations_present"),
            "format_check": dict(passed, id="format"),
            "word_count": 500,
            "brief": {"length": "500 words"},
            "constraint_failures": failures or [],
        }
        det.update(checks or {})
        nodes = {"Deterministic Checks": det}
        item = {"output": review}
        out = {f: _evaluate(_assignment("Compute Verdict", f), item, nodes) for f in ("score", "issues")}
        gate = _nodes()["Approved?"]["parameters"]["conditions"]["conditions"][0]["leftValue"]
        approved = _evaluate(gate, out)
        self.assertIs(type(approved), bool)
        for issue in out["issues"]:
            self.assertIs(type(issue["blocking"]), bool, issue)
        self.issues, self.score = out["issues"], out["score"]
        return approved, out["issues"]

    def categories(self):
        return [i.get("category") for i in self.issues]

    def test_clean_high_score_is_approved(self):
        self.assertTrue(self.verdict()[0])
        self.assertEqual(self.issues, [])

    def test_a_high_issue_guides_the_reviser_but_does_not_block(self):
        issue = {"severity": "high", "description": "thin on tone", "suggested_fix": "fix"}
        approved, issues = self.verdict(score=86, issues=[issue])
        self.assertTrue(approved)
        self.assertEqual([i["blocking"] for i in issues], [False])

    def test_a_critical_issue_blocks_approval(self):
        issue = {"severity": "critical", "description": "invented statistic", "suggested_fix": "fix"}
        approved, issues = self.verdict(score=95, issues=[issue])
        self.assertFalse(approved)
        self.assertEqual([i["blocking"] for i in issues], [True])

    def test_severity_case_is_ignored(self):
        self.assertFalse(self.verdict(issues=[{"severity": "CRITICAL", "description": "d", "suggested_fix": "f"}])[0])
        self.assertTrue(self.verdict(issues=[{"severity": "HIGH", "description": "d", "suggested_fix": "f"}])[0])

    def test_medium_and_low_issues_do_not_block(self):
        issues = [{"severity": "medium", "description": "d", "suggested_fix": "f"},
                  {"severity": "low", "description": "d", "suggested_fix": "f"}]
        self.assertTrue(self.verdict(issues=issues)[0])
        self.assertEqual([i["blocking"] for i in self.issues], [False, False])

    def test_each_blocking_deterministic_failure_blocks(self):
        self.assertFalse(self.verdict(score=79)[0])
        self.assertFalse(self.verdict(placeholder=True)[0])
        self.assertFalse(self.verdict(failures=["must end with X"])[0])

    def test_a_length_miss_guides_the_reviser_but_does_not_block(self):
        approved, issues = self.verdict(length_ok=False)
        self.assertTrue(approved)
        [length] = [i for i in issues if i["category"] == "deterministic:length"]
        self.assertEqual(length["severity"], "high")
        self.assertFalse(length["blocking"])
        self.assertIn("425-575 words", length["description"])
        self.assertEqual(length["suggested_fix"], "Rewrite to 425-575 words.")

    def test_key_point_citation_and_format_misses_guide_but_do_not_block(self):
        failed = {
            "key_points_check": {"id": "key_points_covered", "passed": False, "severity": "medium",
                                 "detail": "Key points not covered: parking", "suggested_fix": "Add a passage."},
            "citations_check": {"id": "citations_present", "passed": False, "severity": "medium",
                                "detail": "Research was used but the draft cites none of its sources.", "suggested_fix": "Cite."},
            "format_check": {"id": "format", "passed": False, "severity": "low",
                             "detail": "Markdown was requested but the draft has no headings.", "suggested_fix": "Add."},
        }
        approved, _ = self.verdict(checks=failed)
        self.assertTrue(approved)
        self.assertEqual(self.categories(), ["deterministic:key_points_covered", "deterministic:citations_present", "deterministic:format"])
        self.assertEqual([i["severity"] for i in self.issues], ["medium", "medium", "low"])

    def test_a_check_that_did_not_run_blocks(self):
        approved, _ = self.verdict(checks={"citations_check": None})
        self.assertFalse(approved)
        self.assertEqual(self.issues[0]["severity"], "critical")

    def test_a_length_miss_does_not_hide_a_real_blocker(self):
        issue = {"severity": "critical", "description": "d", "suggested_fix": "f"}
        self.assertFalse(self.verdict(length_ok=False, issues=[issue])[0])

    def test_constraint_failures_become_critical_issues_with_a_fix(self):
        approved, issues = self.verdict(failures=['The draft must end with the sentence "Bye."'])
        critical = [i for i in issues if i["severity"] == "critical"]
        self.assertEqual(len(critical), 1)
        self.assertIn("Bye.", critical[0]["description"])
        self.assertTrue(critical[0]["suggested_fix"])
        self.assertTrue(critical[0]["blocking"])

    def test_a_failed_requirement_guides_the_reviser_but_does_not_block(self):
        reqs = [{"requirement": "mention the parking change", "passed": False},
                {"requirement": "friendly tone", "passed": True}]
        approved, issues = self.verdict(requirements=reqs)
        self.assertTrue(approved)
        [req] = [i for i in issues if i["category"] == "requirement_failed"]
        self.assertEqual(req["severity"], "high")
        self.assertFalse(req["blocking"])
        self.assertIn("mention the parking change", req["description"])

    def test_scores_outside_0_to_100_fail_closed(self):
        for bad in (120, -1, "85", None, True, float("nan")):
            with self.subTest(score=bad):
                approved, _ = self.verdict(score=bad)
                self.assertFalse(approved)
                self.assertEqual(self.score, 0)
                self.assertIn("malformed_review", self.categories())

    def test_a_missing_score_fails_closed(self):
        self.assertFalse(self.verdict(review={"issues": []})[0])
        self.assertIn("malformed_review", self.categories())

    def test_issues_that_are_not_a_list_fail_closed(self):
        for bad in ("all good", {"severity": "low"}, 3):
            with self.subTest(issues=bad):
                self.assertFalse(self.verdict(review={"score": 95, "issues": bad})[0])
                self.assertIn("malformed_review", self.categories())

    def test_missing_issues_mean_none(self):
        self.assertTrue(self.verdict(review={"score": 95})[0])

    def test_an_issue_that_is_not_an_object_fails_closed(self):
        self.assertFalse(self.verdict(issues=["looks fine"])[0])
        self.assertIn("malformed_review", self.categories())

    def test_a_low_score_with_only_guiding_issues_still_tells_the_reviser_why(self):
        issue = {"severity": "medium", "description": "dull intro", "suggested_fix": "tighten"}
        approved, issues = self.verdict(score=72, issues=[issue])
        self.assertFalse(approved)
        self.assertEqual(self.categories(), [None, "score_below_threshold"])
        self.assertTrue(issues[1]["blocking"])

    def test_a_low_score_next_to_a_blocking_issue_adds_nothing(self):
        issue = {"severity": "critical", "description": "invented statistic", "suggested_fix": "fix"}
        self.verdict(score=72, issues=[issue])
        self.assertEqual(self.categories(), [None])

    def test_a_low_score_without_issues_gets_one_for_the_reviser(self):
        approved, issues = self.verdict(score=70)
        self.assertFalse(approved)
        self.assertEqual(self.categories(), ["score_below_threshold"])
        self.assertIn("70", issues[0]["description"])

    def test_a_null_gate_never_approves(self):
        gate = _nodes()["Approved?"]["parameters"]["conditions"]["conditions"][0]["leftValue"]
        self.assertFalse(_evaluate(gate, {"score": 95, "issues": None}))
        self.assertFalse(_evaluate(gate, {"score": 95, "issues": [{"severity": "low"}]}))  # no blocking flag


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

    def test_unverified_research_is_a_failure(self):
        # Only Verify Research's verified dossier reaches DraftAgent (tests/unit/test_n8n_research.py).
        self.assertEqual(self.run_field("dossier", "Findings: ..."), "")
        self.assertTrue(self.run_field("research_failed", "Findings: ..."))

    def test_no_research_is_not_a_failure(self):
        self.assertEqual(self.run_field("dossier", executed=False), "")
        self.assertFalse(self.run_field("research_failed", executed=False))

    def test_research_failed_survives_a_revision_round(self):
        names = [a["name"] for a in _nodes()["Prepare Revision"]["parameters"]["assignments"]["assignments"]]
        self.assertIn("research_failed", names)

    def test_research_agent_is_capped_at_six_tool_calls_plus_the_answer(self):
        # The prompt allows at most 6 tool calls; one iteration is one call, plus one for the final answer.
        self.assertEqual(_nodes()["ResearchAgent"]["parameters"]["options"]["maxIterations"], 7)


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
        self.assertIn("no issue is critical", text)
        self.assertNotIn("critical or high", text)
        self.assertIn("constraint_failures", text)
        self.assertNotIn("non-critical issues do not block approval", text)

    def test_delivered_reply_is_the_deliverable_only(self):
        text = self.nodes["Telegram Reply Delivered"]["parameters"]["text"]
        self.assertNotIn("delivery_note", text)
        self.assertIn("draft.content", text)
        self.assertIn("substring(0, 3900)", text)
        self.assertTrue(text.startswith("={{ ('Approved"))

    def test_escalation_messages_describe_the_gate(self):
        body = self.nodes["Respond Escalated"]["parameters"]["responseBody"]
        tg = self.nodes["Telegram Reply Escalated"]["parameters"]["text"]
        for text in (body, tg):
            self.assertIn("no critical issue", text)
            self.assertNotIn("critical or high", text)

    @unittest.skipUnless(NODE, "node is required to evaluate n8n expressions")
    def test_escalated_telegram_reply_lists_blocking_issues_first(self):
        tg = self.nodes["Telegram Reply Escalated"]["parameters"]["text"]
        issues = [{"severity": "high", "description": "length", "blocking": False}] + [
            {"severity": "high", "description": f"blocker {n}", "blocking": True} for n in range(5)]
        text = _evaluate(tg, {"round": 3, "score": 72, "issues": issues})
        self.assertIn("blocker 4", text)
        self.assertNotIn("- [high] length", text)


@unittest.skipUnless(NODE, "node is required to evaluate n8n expressions")
class ReviewFindingsTests(unittest.TestCase):
    """Regression tests for the PR review findings (2, 3, 4, 5, 6, 7)."""

    # -- helpers ---------------------------------------------------------------------------
    def failures(self, content, request):
        return _evaluate(
            _assignment("Deterministic Checks", "constraint_failures"),
            {"output": {"draft": {"content": content}}},
            {"Build Draft Input": {"raw_request": request}},
        )

    def test_exactly_n_words_each_is_not_a_whole_draft_constraint(self):
        req = "Write three paragraphs of exactly 100 words each."
        self.assertEqual(self.failures(_words(300), req), [])
        self.assertEqual(self.failures(_words(300), "Write three sections, exactly 100 words per section."), [])
        self.assertEqual(len(self.failures(_words(300), "Write exactly 100 words.")), 1)

    def test_exact_word_count_message_states_the_real_window(self):
        [msg] = self.failures(_words(60), "Write exactly 50 words.")
        self.assertIn("allowed 45-55", msg)
        [msg] = self.failures(_words(300), "Write exactly 250 words.")
        self.assertIn("allowed 238-263", msg)
        self.assertEqual(self.failures(_words(55), "Write exactly 50 words."), [])
        self.assertEqual(len(self.failures(_words(56), "Write exactly 50 words.")), 1)

    def test_a_single_quoted_closing_sentence_may_contain_an_apostrophe(self):
        req = "End with the sentence 'Don't hesitate to reach out.'"
        self.assertEqual(self.failures("Body.\n\nDon't hesitate to reach out.", req), [])
        [msg] = self.failures("Body text. Don", req)
        self.assertIn("Don't hesitate to reach out.", msg)
        self.assertEqual(self.failures("Body.\n\nThanks!", "End with the sentence 'Thanks!'"), [])

    def length_ok(self, brief_length, words):
        return _evaluate(
            _assignment("Deterministic Checks", "length_check"),
            {"output": {"draft": {"content": _words(words)}}},
            {"Build Draft Input": {"brief": {"length": brief_length}}},
        )["passed"]

    def placeholder(self, content):
        return _evaluate(
            _assignment("Deterministic Checks", "has_placeholder"), {"output": {"draft": {"content": content}}}
        )

    # -- finding 2: apostrophes in the required sentence ------------------------------------
    def test_required_sentence_may_contain_an_apostrophe(self):
        req = 'Write a note. End with the sentence "Don\'t hesitate to ask."'
        self.assertEqual(self.failures("Hello.\n\nDon't hesitate to ask.", req), [])
        bad = self.failures("Hello.\n\nThanks.", req)
        self.assertEqual(len(bad), 1)
        self.assertIn("Don't hesitate to ask.", bad[0])

    def test_curly_quoted_required_sentence(self):
        req = "End with the sentence \u201cSee you Friday.\u201d"
        self.assertEqual(self.failures("Hi.\n\nSee you Friday.", req), [])

    # -- finding 4: length bounds ----------------------------------------------------------
    def test_upper_bounds_are_ceilings_not_targets(self):
        self.assertTrue(self.length_ok("under 200 words", 120))
        self.assertFalse(self.length_ok("under 200 words", 260))
        self.assertTrue(self.length_ok("max 300 words", 280))
        self.assertFalse(self.length_ok("no more than 300 words", 320))

    def test_lower_bounds_are_floors_not_targets(self):
        self.assertTrue(self.length_ok("at least 500 words", 900))
        self.assertFalse(self.length_ok("at least 500 words", 300))
        self.assertTrue(self.length_ok("no fewer than 500 words", 900))
        self.assertFalse(self.length_ok("no less than 500 words", 300))
        self.assertTrue(self.length_ok("more than 500 words", 900))
        self.assertTrue(self.length_ok("less than 200 words", 120))
        self.assertFalse(self.length_ok("fewer than 200 words", 260))

    def test_targets_and_ranges_keep_a_15_percent_band(self):
        self.assertTrue(self.length_ok("400 words", 350))
        self.assertFalse(self.length_ok("400 words", 300))
        self.assertTrue(self.length_ok("300-400 words", 350))
        self.assertFalse(self.length_ok("300-400 words", 250))
        self.assertFalse(self.length_ok("within 300-400 words", 120))

    def test_no_word_target_is_always_ok(self):
        self.assertTrue(self.length_ok("one page", 5000))
        self.assertTrue(self.length_ok("short", 5))

    # -- finding 5: constraint regexes must not over-match ---------------------------------
    def test_exactly_n_words_about_each_item_is_not_a_whole_draft_constraint(self):
        req = "Write five headlines, each headline exactly 8 words, then a two paragraph summary."
        self.assertEqual(self.failures(_words(200), req), [])

    def test_at_least_n_points_without_the_word_bullet_is_not_a_bullet_constraint(self):
        req = "Explain the plan and cover at least three points in the introduction."
        self.assertEqual(self.failures(_words(80), req), [])

    def test_numbered_list_items_count_toward_a_bullet_minimum(self):
        req = "Include a bulleted list of at least four items."
        content = _words(50) + "\n1. one\n2. two\n3. three\n4. four\n"
        self.assertEqual(self.failures(content, req), [])

    def test_bullet_word_forms_are_understood(self):
        req = "Use at least three bullet points."
        self.assertTrue(any("3" in f for f in self.failures(_words(50) + "\n- a\n", req)))

    def test_todo_in_ordinary_prose_is_not_a_placeholder(self):
        self.assertFalse(self.placeholder("Our todo app and the tbd column help teams plan."))

    def test_real_placeholders_are_still_caught(self):
        for text in ("TODO: fill in", "Pricing TBD", "[Insert name here]", "Dear [Name],", "lorem ipsum dolor", "XXX"):
            with self.subTest(text=text):
                self.assertTrue(self.placeholder(text), text)

    def test_markdown_links_are_still_not_placeholders(self):
        self.assertFalse(self.placeholder("See [Your HR portal](https://example.com/hr) and [Addendum]."))

    # -- finding 6: research errors and unparseable intake replies -------------------------
    def test_a_research_error_item_is_scrubbed_and_flagged(self):
        nodes = {"Normalize Request": {"raw_request": "r", "run_id": "1", "round": 0, "issues": []},
                 "IntakeAgent": {"output": {"brief": {}, "work_type": "draft_from_scratch"}},
                 "ResearchAgent": {"error": "The service is receiving too many requests from you"}}
        self.assertEqual(_evaluate(_assignment("Build Draft Input", "dossier"), {}, nodes), "")
        self.assertTrue(_evaluate(_assignment("Build Draft Input", "research_failed"), {}, nodes))

    def kind(self, error):
        expr = _nodes()["Intake Reply Unparseable?"]["parameters"]["conditions"]["conditions"][0]["leftValue"]
        return _evaluate(expr, {"error": error})

    def test_only_unparseable_replies_are_treated_as_unclear_requests(self):
        self.assertTrue(self.kind("Model output doesn't fit required format"))
        self.assertTrue(self.kind("The AI model returned an empty response to the Structured Output Parser"))
        self.assertFalse(self.kind("The service is receiving too many requests from you"))
        self.assertFalse(self.kind("Invalid API key"))
        self.assertFalse(self.kind(""))

    # -- finding 3: ReviewAgent system message must match the gate -------------------------
    def test_review_system_message_agrees_with_the_gate(self):
        msg = _nodes()["ReviewAgent"]["parameters"]["messages"]["messageValues"][0]["message"]
        self.assertIn("none of your issues is critical", msg)
        self.assertNotIn("critical or high", msg)
        self.assertNotIn("do NOT block approval", msg)
        self.assertNotIn("even if non-critical issues remain", msg)
        # output fields the Review Parser schema does not have
        self.assertNotIn("requirements_check", msg)
        self.assertNotIn("approved: boolean", msg)

    # -- finding 7: long deliverables are split, never cut ---------------------------------
    def parts(self, content):
        nodes = _nodes()
        stub = {"Compute Verdict": {"score": 90, "round": 1, "run_id": "9", "draft": {"content": content}}}
        texts = [
            _evaluate(nodes[n]["parameters"]["text"], {}, stub)
            for n in ("Telegram Reply Delivered", "Telegram Reply Delivered 2", "Telegram Reply Delivered 3")
        ]
        gates = [
            _evaluate(nodes[n]["parameters"]["conditions"]["conditions"][0]["leftValue"], {}, stub)
            for n in ("More Text? (part 2)", "More Text? (part 3)")
        ]
        return texts, gates

    def test_a_short_deliverable_is_one_message_with_nothing_lost(self):
        content = "Body.\n\nThank you for your flexibility."
        texts, gates = self.parts(content)
        self.assertEqual(gates, [False, False])
        self.assertTrue(texts[0].startswith("Approved"))
        self.assertTrue(texts[0].endswith("Thank you for your flexibility."))

    def test_a_long_deliverable_is_split_losslessly_within_telegram_limits(self):
        content = ("word " * 1700) + "END."  # ~8500 chars
        texts, gates = self.parts(content)
        self.assertEqual(gates, [True, True])
        self.assertTrue(all(len(t) <= 4096 for t in texts))
        joined = "".join(t for t in texts)
        self.assertTrue(joined.endswith("END."))
        self.assertIn(content, joined)

    def test_an_enormous_deliverable_gets_a_cut_notice_pointing_at_the_execution(self):
        texts, gates = self.parts("word " * 5000)  # 25000 chars
        self.assertTrue(all(len(t) <= 4096 for t in texts))
        self.assertIn("execution 9", texts[2])


if __name__ == "__main__":
    unittest.main()
