import pytest

from harness import checks

GOOD = "# Vacation Policy\n\nEvery employee receives 25 days of paid vacation each year and may carry over five unused days."


def by_id(results):
    return {r.id: r for r in results}


def check(brief, content, dossier=None):
    return by_id(checks.run_checks(brief, content, dossier))


def test_returns_five_results_in_order():
    ids = [r.id for r in checks.run_checks({}, GOOD, None)]
    assert ids == ["length", "key_points_covered", "no_placeholders", "citations_present", "format"]


def test_missing_brief_fields_do_not_raise_and_pass():
    """Sparse briefs skip cleanly."""
    assert all(r.passed for r in check({}, GOOD).values())
    assert all(r.passed for r in check({"length": "short", "key_points": None, "format": None}, GOOD).values())


def test_length_range_with_tolerance():
    brief = {"length": "300-400 words"}
    assert check(brief, "w " * 350)["length"].passed
    assert check(brief, "w " * 270)["length"].passed  # 300 * 0.85 = 255
    assert not check(brief, "w " * 100)["length"].passed
    assert not check(brief, "w " * 600)["length"].passed


def test_length_single_number_and_severity():
    r = check({"length": "about 500 words"}, "w " * 200)["length"]
    assert not r.passed and r.severity == "medium" and "200" in r.detail


def test_length_accepts_integer():
    assert check({"length": 100}, "w " * 100)["length"].passed


def test_character_limits_count_characters():
    brief = {"length": "≤ 270 characters including the link"}
    assert check(brief, "x" * 250)["length"].passed
    r = check(brief, "word " * 100)["length"]
    assert not r.passed and "characters" in r.detail


def test_lengths_without_a_word_or_character_count_are_skipped():
    for length in ["1-2 pages", "short", "Single sentence"]:
        assert check({"length": length}, "w " * 999)["length"].passed, length


def test_maximum_and_minimum_lengths():
    assert check({"length": "Maximum 380 words total"}, "w " * 100)["length"].passed
    assert not check({"length": "Maximum 380 words total"}, "w " * 500)["length"].passed
    assert not check({"length": "at least 300 words"}, "w " * 200)["length"].passed
    assert check({"length": "at least 300 words"}, "w " * 900)["length"].passed


def test_key_points_coverage():
    brief = {"key_points": ["25 days of paid vacation", "carry-over of unused days", "quarterly bonus schedule"]}
    r = check(brief, GOOD)["key_points_covered"]
    assert not r.passed
    assert "quarterly bonus schedule" in r.detail
    assert "25 days" not in r.detail


def test_placeholders_are_critical():
    for text in ["Please TODO this", "Contact [insert name] soon", "Lorem ipsum dolor", "Dear [Your Name]", "TBD", "Read it here: [link]"]:
        r = check({}, text)["no_placeholders"]
        assert not r.passed and r.severity == "critical", text
    assert check({}, GOOD)["no_placeholders"].passed


def test_placeholder_detection_ignores_markdown_links_and_lowercase_prose():
    for text in ["See [the report](https://x.org).", "[Name](https://x.org) wrote it.", "Update your todo list."]:
        assert check({}, text)["no_placeholders"].passed, text


def test_citations_required_only_when_dossier_has_sources():
    dossier = {"sources": [{"title": "EUR-Lex", "url": "https://eur-lex.europa.eu/act"}]}
    assert not check({}, GOOD, dossier)["citations_present"].passed
    assert check({}, GOOD + "\nSource: eur-lex.europa.eu", dossier)["citations_present"].passed
    assert check({}, GOOD, {"sources": []})["citations_present"].passed
    assert check({}, GOOD, None)["citations_present"].passed


def test_format_markdown_requires_heading():
    assert not check({"format": "markdown"}, "just text")["format"].passed
    assert check({"format": "markdown"}, GOOD)["format"].passed
    assert check({"format": "plain email"}, "just text")["format"].passed


def test_as_issue_and_as_dict():
    r = check({}, "TODO")["no_placeholders"]
    issue = r.as_issue()
    assert set(issue) == {"severity", "category", "description", "suggested_fix"}
    assert issue["category"] == "deterministic:no_placeholders"
    assert r.as_dict()["passed"] is False


def test_length_binds_numbers_to_unit_words():
    """Numbers must be bound to the unit word, not taken as first occurrence."""
    # "2 paragraphs, about 120 words" -> should parse as ~120 words, not 2.
    assert check({"length": "2 paragraphs, about 120 words"}, "w " * 120)["length"].passed
    # "Max 2 paragraphs, 150 words" -> should parse as ≤150 words, not ≤2.
    assert check({"length": "Max 2 paragraphs, 150 words"}, "w " * 150)["length"].passed
    assert not check({"length": "Max 2 paragraphs, 150 words"}, "w " * 400)["length"].passed
    # "1–2 pages, ~600 words" -> should parse as ~600 words, not 1-2.
    assert check({"length": "1–2 pages, ~600 words"}, "w " * 600)["length"].passed
    # "about 1.5k words" -> should parse as ~1500 words.
    assert check({"length": "about 1.5k words"}, "w " * 1500)["length"].passed
    # "1,500-2,500 words" -> should parse as 1500-2500 words.
    assert check({"length": "1,500-2,500 words"}, "w " * 2000)["length"].passed


def test_length_zero_or_negative_is_skipped():
    """Integer lengths <= 0 should be skipped (pass the check)."""
    assert check({"length": 0}, "w " * 999)["length"].passed
    assert check({"length": -5}, "w " * 999)["length"].passed


def test_citations_match_sources_by_name():
    dossier = {
        "sources": [
            {"title": "Europe Electric Vehicle Charging Infrastructure Market Size", "url": "https://www.gminsights.com/industry-analysis/x"},
            {"title": "EV charging outlook", "url": "https://finance.yahoo.com/news/ev-charging"},
        ]
    }
    assert check({}, GOOD + "\nSource: GM Insights 2025", dossier)["citations_present"].passed
    assert check({}, GOOD + "\nSource: Yahoo Finance 2024", dossier)["citations_present"].passed
    assert check({}, GOOD + "\nSource: europe electric vehicle charging infrastructure market size", dossier)["citations_present"].passed
    assert not check({}, GOOD + "\nSource: Reuters 2024", dossier)["citations_present"].passed


def test_citation_label_matches_for_country_domains_but_not_short_labels():
    assert checks._host_label("bbc.co.uk") == "bbc" and checks._host_label("finance.yahoo.com") == "yahoo"
    paper = {"sources": [{"title": "Report", "url": "https://www.theguardian.co.uk/news/1"}]}
    assert check({}, GOOD + " per The Guardian", paper)["citations_present"].passed
    ft = {"sources": [{"title": "Market report", "url": "https://www.ft.com/content/1"}]}
    assert not check({}, GOOD + " the draft is soft on the facts", ft)["citations_present"].passed


def test_citations_with_non_dict_sources():
    """Non-dict entries and None values in sources should not raise."""
    dossier = {
        "sources": [
            "https://a.com",  # String instead of dict.
            None,  # None entry.
            {"url": None, "title": None},  # Dict with None values.
        ]
    }
    # Should not raise; should still look for citations.
    assert not check({}, GOOD, dossier)["citations_present"].passed


def test_malformed_numbers_do_not_raise():
    """Malformed number patterns should skip the check without raising ValueError."""
    for length in ["3.2.1 words", "1... words", "words"]:
        r = check({"length": length}, "w " * 999)["length"]
        assert r.passed, f"Expected pass for '{length}', got {r}"


def test_constraint_search_includes_text_after_match():
    """at-most/at-least hints after the match should be recognized."""
    # "150 words max" -> max applies to 150 (text after match).
    assert check({"length": "150 words max"}, "w " * 100)["length"].passed
    assert not check({"length": "150 words max"}, "w " * 400)["length"].passed
    # "at least 300 words" still works (text before match).
    assert not check({"length": "at least 300 words"}, "w " * 200)["length"].passed
    assert check({"length": "at least 300 words"}, "w " * 300)["length"].passed


def _passes(length, size, unit="w "):
    return check({"length": length}, unit * size)["length"].passed


@pytest.mark.parametrize(
    "length, unit, limit",
    [
        ("less than 200 words", "w ", 200),
        ("fewer than 280 characters", "x", 280),
        ("280 characters or less", "x", 280),
        ("within 280 characters", "x", 280),
        ("not exceeding 280 characters", "x", 280),
        ("no longer than 150 words", "w ", 150),
        ("below 300 words", "w ", 300),
        ("300 words or fewer", "w ", 300),
        ("not more than 300 words", "w ", 300),
        ("≤ 270 characters", "x", 270),
        ("Maximum 380 words total", "w ", 380),
    ],
)
def test_ceilings_have_no_tolerance_above_the_stated_number(length, unit, limit):
    assert _passes(length, limit - 80, unit)
    assert _passes(length, limit, unit)
    assert not _passes(length, limit + 1, unit)


@pytest.mark.parametrize("length", ["more than 500 words", "over 500 words", "500 words or more", "above 500 words", "no less than 500 words"])
def test_floors_phrased_in_other_ways(length):
    assert _passes(length, 900)
    assert not _passes(length, 300)


def test_between_x_and_y_is_a_range_with_tolerance():
    assert _passes("between 200 and 300 words", 250)
    assert _passes("between 200 and 300 words", 220)
    assert _passes("between 200 and 300 words", 175)  # 200 * 0.85 = 170
    assert not _passes("between 200 and 300 words", 100)
    assert not _passes("between 200 and 300 words", 500)


@pytest.mark.parametrize(
    "length",
    ["2 paragraphs (~150 words each)", "2 paragraphs of 150 words", "150 words per section", "each section about 150 words", "3 sentences of at most 20 words"],
)
def test_per_item_counts_are_skipped(length):
    assert _passes(length, 999)
    assert _passes(length, 3)


def test_a_ceiling_is_exact_for_characters():
    assert _passes("≤ 270 characters", 270, "x")
    assert not _passes("≤ 270 characters", 271, "x")


def test_weak_hint_words_elsewhere_in_the_text_are_not_ceilings():
    assert not _passes("a post over email, exactly 500 words", 100)  # exact target, not "over 500"
    assert not _passes("within a week, 500 words", 900)  # "within" is not next to the count


@pytest.mark.parametrize("length", ["9" * 309 + " words", "1" + "0" * 310 + "k words", "9" * 400 + "-" + "1" * 400 + " characters", "between 1" + "0" * 320 + " and 5 words"])
def test_absurd_numbers_skip_the_check_instead_of_raising(length):
    assert check({"length": length}, "w " * 50)["length"].passed


@pytest.mark.parametrize(
    "length, unit, limit",
    [
        ("not to exceed 300 words", "w ", 300),
        ("never exceed 300 words", "w ", 300),
        ("shouldn't exceed 150 words", "w ", 150),
        ("do not exceed 500 words", "w ", 500),
        ("not over 300 words", "w ", 300),
        ("not above 300 words", "w ", 300),
        ("must not exceed 300 words", "w ", 300),
        ("never exceed 280 characters", "x", 280),
        ("not to exceed 280 characters", "x", 280),
    ],
)
def test_negated_limits_are_ceilings(length, unit, limit):
    assert _passes(length, limit - 30, unit)
    assert _passes(length, limit, unit)
    assert not _passes(length, limit + 1, unit)
    assert not _passes(length, limit * 2, unit)


@pytest.mark.parametrize("length", ["more than 500 words", "over 500 words", "exceeds 500 words", "exceed 500 words"])
def test_positive_forms_are_still_floors(length):
    assert _passes(length, 900)
    assert not _passes(length, 300)
