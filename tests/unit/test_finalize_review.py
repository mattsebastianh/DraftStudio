from harness import checks

REVIEW = {
    "score": 92,
    "dimension_scores": {"clarity": 92, "accuracy": 92, "completeness": 92, "tone_alignment": 92},
    "issues": [],
    "status": "approved",
}


def results_for(content, brief=None, dossier=None):
    return checks.run_checks(brief or {}, content, dossier)


def test_clean_draft_approved():
    out = checks.finalize_review(REVIEW, results_for("# Title\n\nSolid text."), 80)
    assert out["status"] == "approved"
    assert out["status_disagreed"] is False
    assert len(out["checks"]) == 5


def test_placeholder_blocks_even_when_llm_scores_high():
    """Acceptance A3: a seeded TODO is blocked by code regardless of the LLM."""
    out = checks.finalize_review(REVIEW, results_for("# Title\n\nTODO write this"), 80)
    assert out["status"] == "revision_required"
    assert out["status_disagreed"] is True
    assert out["llm_status"] == "approved"
    assert any(i["severity"] == "critical" and i["category"] == "deterministic:no_placeholders" for i in out["issues"])


def test_non_critical_failure_adds_issue_but_does_not_block():
    out = checks.finalize_review(REVIEW, results_for("# T\n\nfine", brief={"key_points": ["quantum computing"]}), 80)
    assert out["status"] == "approved"
    assert any(i["category"] == "deterministic:key_points_covered" for i in out["issues"])


def test_length_violation_blocks_even_with_a_high_score():
    out = checks.finalize_review(REVIEW, results_for("# T\n\nshort", brief={"length": "500 words"}), 80)
    assert out["status"] == "revision_required"
    assert any(i["category"] == "deterministic:length" and i["severity"] == "critical" for i in out["issues"])


def test_low_score_without_issues_gets_a_synthesized_issue():
    out = checks.finalize_review(dict(REVIEW, score=72, issues=[]), results_for("# T\n\nfine"), 80)
    assert out["status"] == "revision_required"
    assert [i["category"] for i in out["issues"]] == ["score_below_threshold"]


def test_low_score_blocks():
    out = checks.finalize_review(dict(REVIEW, score=79), results_for("# T\n\nfine"), 80)
    assert out["status"] == "revision_required"


def test_llm_critical_issue_blocks():
    review = dict(REVIEW, issues=[{"severity": "critical", "description": "false claim", "suggested_fix": "remove"}])
    assert checks.finalize_review(review, results_for("# T\n\nfine"), 80)["status"] == "revision_required"


def test_model_saying_revision_but_code_approves_is_flagged():
    out = checks.finalize_review(dict(REVIEW, status="revision_required"), results_for("# T\n\nfine"), 80)
    assert out["status"] == "approved" and out["status_disagreed"] is True


def test_missing_advisory_status_is_not_a_disagreement():
    review = {key: value for key, value in REVIEW.items() if key != "status"}
    out = checks.finalize_review(review, results_for("# T\n\nfine"), 80)
    assert out["llm_status"] is None and out["status_disagreed"] is False


def test_input_review_is_not_mutated():
    review = dict(REVIEW, issues=[])
    checks.finalize_review(review, results_for("TODO"), 80)
    assert review["issues"] == []


def _clean(review):
    return checks.finalize_review(review, results_for("# T\n\nfine"), 80)


def test_severity_match_ignores_case_and_whitespace():
    for severity in ("Critical", " critical ", "CRITICAL"):
        review = dict(REVIEW, issues=[{"severity": severity, "description": "x", "suggested_fix": "y"}])
        assert _clean(review)["status"] == "revision_required"


def test_non_dict_issue_fails_closed():
    assert _clean(dict(REVIEW, issues=["bad"]))["status"] == "revision_required"


def test_invalid_score_is_malformed_and_blocks():
    missing = {key: value for key, value in REVIEW.items() if key != "score"}
    for review in (missing, dict(REVIEW, score=None), dict(REVIEW, score="90/100"), dict(REVIEW, score=float("nan")), dict(REVIEW, score=True)):
        out = _clean(review)
        assert out["status"] == "revision_required"
        assert out["score"] == 0
        assert any(i["severity"] == "critical" and i["category"] == "malformed_review" for i in out["issues"])


def test_malformed_issues_are_treated_as_no_llm_issues():
    for bad in (None, "oops"):
        out = _clean(dict(REVIEW, issues=bad))
        assert out["status"] == "approved"
        assert out["issues"] == []


def test_score_is_compared_without_truncation():
    assert _clean(dict(REVIEW, score=79.9))["status"] == "revision_required"
    assert _clean(dict(REVIEW, score=80.0))["status"] == "approved"


def test_out_of_range_or_non_finite_scores_are_malformed():
    for score in (float("inf"), float("-inf"), 10**400, 150, -1):
        out = _clean(dict(REVIEW, score=score))
        assert out["status"] == "revision_required"
        assert out["score"] == 0
        assert any(i["severity"] == "critical" and i["category"] == "malformed_review" for i in out["issues"])


def test_score_range_boundaries_are_valid():
    assert _clean(dict(REVIEW, score=100))["status"] == "approved"
    zero = _clean(dict(REVIEW, score=0))
    assert zero["status"] == "revision_required"
    assert not any(i.get("category") == "malformed_review" for i in zero["issues"])
