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
    out = checks.finalize_review(REVIEW, results_for("# T\n\nshort", brief={"length": "500 words"}), 80)
    assert out["status"] == "approved"
    assert any(i["category"] == "deterministic:length" for i in out["issues"])


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
