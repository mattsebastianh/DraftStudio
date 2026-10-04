from harness import config


def test_load_env_parses_pairs_and_skips_comments(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# c\nA=1\n\nB = two words \nNOEQUALS\n")
    assert config.load_env(p) == {"A": "1", "B": "two words"}


def test_load_env_strips_matching_quotes(tmp_path):
    p = tmp_path / ".env"
    p.write_text("A=\"quoted\"\nB='single'\nC=\"unbalanced\nD=\"\"\n")
    assert config.load_env(p) == {"A": "quoted", "B": "single", "C": '"unbalanced', "D": ""}


def test_every_agent_has_a_budget_under_the_completion_cap():
    for agent in ["IntakeAgent", "ResearchAgent", "DraftAgent", "ReviewAgent", "DispatchAgent"]:
        max_tokens, effort = config.AGENT_BUDGETS[agent]
        assert 3000 <= max_tokens <= config.MAX_COMPLETION_TOKENS
        assert effort in ("low", "medium", "high")


def test_thresholds_preserved():
    assert config.QUALITY_THRESHOLD == 80
    assert config.MAX_REVISION_CYCLES == 3
