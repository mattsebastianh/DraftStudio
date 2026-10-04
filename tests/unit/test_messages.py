from harness import messages, wires

BRIEF = {"topic": "Vacation policy", "key_points": ["25 days", "carry-over"], "length": "300 words"}
DRAFT = {"title": "Vacation Policy", "content": "# Vacation Policy\nBody", "word_count": 3}
CHECKS = [{"id": "length", "passed": True, "severity": "low", "detail": "ok", "suggested_fix": ""}]
DOSSIER = {"topic": "t", "findings": [], "gaps": ["g"], "confidence": 30, "sources": []}


def assert_valid(wire_id, message):
    assert wires.validate_message(wire_id, message) == []


def test_intake_to_research():
    msg = messages.intake_to_research(BRIEF)
    assert msg == {"topic": "Vacation policy", "focus_areas": ["25 days", "carry-over"]}
    assert_valid("IntakeAgent_to_ResearchAgent", msg)


def test_intake_to_research_tolerates_missing_key_points():
    assert messages.intake_to_research({"topic": "t"})["focus_areas"] == []


def test_intake_to_draft_omits_the_dossier_when_research_did_not_run():
    assert messages.intake_to_draft(BRIEF, None) == {"brief": BRIEF}
    assert_valid("IntakeAgent_to_DraftAgent", messages.intake_to_draft(BRIEF, None))
    assert_valid("IntakeAgent_to_DraftAgent", messages.intake_to_draft(BRIEF, DOSSIER))


def test_draft_to_review_carries_deterministic_checks():
    msg = messages.draft_to_review(BRIEF, DRAFT, 0, CHECKS)
    assert msg["deterministic_checks"] == CHECKS
    assert_valid("DraftAgent_to_ReviewAgent", msg)


def test_review_to_draft_includes_title_and_previous_draft():
    issues = [{"severity": "high", "description": "d", "suggested_fix": "f"}]
    msg = messages.review_to_draft(BRIEF, DRAFT, issues, 1)
    assert msg["draft_title"] == "Vacation Policy" and msg["previous_draft"] == DRAFT
    assert_valid("ReviewAgent_to_DraftAgent", msg)


def test_review_to_draft_carries_the_research_sources():
    issues = [{"severity": "high", "description": "no citations", "suggested_fix": "cite"}]
    dossier = {"sources": [{"title": "EUR-Lex", "url": "https://eur-lex.europa.eu/x"}, {"title": "no url"}]}
    msg = messages.review_to_draft(BRIEF, DRAFT, issues, 1, dossier)
    assert msg["sources"] == [{"title": "EUR-Lex", "url": "https://eur-lex.europa.eu/x"}]
    assert_valid("ReviewAgent_to_DraftAgent", msg)


def test_review_to_draft_without_research_has_no_sources():
    for dossier in (None, {"sources": []}, {"sources": [{"title": "no url"}]}):
        msg = messages.review_to_draft(BRIEF, DRAFT, [], 1, dossier)
        assert "sources" not in msg
        assert_valid("ReviewAgent_to_DraftAgent", msg)


def test_review_to_dispatch_carries_draft_rounds_and_sources():
    review = {"score": 88, "dimension_scores": {"clarity": 90}}
    dossier = {"sources": [{"title": "EUR-Lex", "url": "https://eur-lex.europa.eu/x"}, {"title": "no url"}]}
    msg = messages.review_to_dispatch(DRAFT, review, 2, dossier)
    assert msg["draft"] == DRAFT
    assert msg["review_summary"] == {
        "score": 88,
        "dimension_scores": {"clarity": 90},
        "revision_rounds": 2,
        "review_status": "approved",
    }
    assert msg["sources"] == [{"title": "EUR-Lex", "url": "https://eur-lex.europa.eu/x"}]
    assert_valid("ReviewAgent_to_DispatchAgent", msg)


def test_review_to_dispatch_without_research_has_no_sources():
    msg = messages.review_to_dispatch(DRAFT, {"score": 81}, 0)
    assert "sources" not in msg
    assert_valid("ReviewAgent_to_DispatchAgent", msg)
