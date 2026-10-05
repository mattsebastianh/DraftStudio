import json

from harness import check_run_logs

STEP = {
    "agent": "DraftAgent",
    "output": {"draft": {}},
    "schema_enforced": True,
    "validation_retries": 1,
    "finish_reasons": ["stop"],
    "used_extract_json": False,
}
REVIEW = {**STEP, "agent": "ReviewAgent", "output": {"checks": []}}
SKIPPED_RESEARCH = {"agent": "ResearchAgent", "skipped": True, "output": {"findings": []}}


def log_with(*steps, **extra):
    return {"steps": list(steps), **extra}


def problems(*steps, **extra):
    return check_run_logs.check(log_with(*steps, **extra))


def test_clean_log_passes():
    assert problems(SKIPPED_RESEARCH, STEP, REVIEW) == []


def test_missing_meta_fields_fail_a5():
    step = {k: v for k, v in STEP.items() if k != "schema_enforced"}
    assert any(p.startswith("A5") for p in problems(step))


def test_truncated_final_reply_fails_a1():
    assert any(p.startswith("A1") for p in problems({**STEP, "finish_reasons": ["stop", "length"]}))


def test_truncation_that_was_recovered_passes():
    assert problems({**STEP, "finish_reasons": ["length", "stop"]}) == []


def test_extract_json_fallback_fails_a1():
    assert any(p.startswith("A1") for p in problems({**STEP, "used_extract_json": True}))


def test_unsourced_research_finding_fails_a2():
    research = {**STEP, "agent": "ResearchAgent", "skipped": False, "output": {"findings": [{"claim": "x", "sources": []}]}}
    assert any(p.startswith("A2") for p in problems(research))


def test_review_without_check_results_fails_a5():
    assert any(p.startswith("A5") for p in problems({**REVIEW, "output": {}}))


def test_failed_run_fails():
    assert problems(STEP, error="LLMHTTPError: HTTP 401: bad key") == ["run failed: LLMHTTPError: HTTP 401: bad key"]


def test_main_reports_and_exits_nonzero_on_failure(tmp_path, capsys):
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(log_with(STEP)))
    bad.write_text(json.dumps(log_with(error="boom")))
    assert check_run_logs.main([str(good)]) == 0
    assert check_run_logs.main([str(good), str(bad)]) == 1
    out = capsys.readouterr().out
    assert f"PASS {good}" in out and f"FAIL {bad}" in out


def research_step(findings, **extra):
    return {**STEP, "agent": "ResearchAgent", "skipped": False, "output": {"findings": findings}, **extra}


def test_finding_citing_an_unretrieved_url_fails_a2():
    finding = {"claim": "x", "sources": ["https://made.up/x"]}
    found = problems(research_step([finding], retrieved_urls=["https://real.example/page"]))
    assert any(p.startswith("A2") and "never retrieved" in p for p in found)


def test_finding_citing_a_retrieved_url_passes_even_with_a_trailing_slash_difference():
    finding = {"claim": "x", "sources": ["https://Real.example/page/"]}
    assert problems(research_step([finding], retrieved_urls=["https://real.example/page"])) == []


def test_logs_without_retrieved_urls_keep_the_non_empty_sources_check():
    finding = {"claim": "x", "sources": ["https://anything.example/"]}
    assert problems(research_step([finding])) == []


def test_unreadable_and_invalid_logs_fail_without_stopping_the_batch(tmp_path, capsys):
    good, garbage, missing, wrong_shape = (tmp_path / n for n in ("good.json", "garbage.json", "missing.json", "list.json"))
    good.write_text(json.dumps(log_with(STEP)))
    garbage.write_text("{not json")
    wrong_shape.write_text("[1, 2]")
    assert check_run_logs.main([str(garbage), str(missing), str(wrong_shape), str(good)]) == 1
    out = capsys.readouterr().out
    assert f"FAIL {garbage}\n   - could not read run log: JSONDecodeError" in out
    assert f"FAIL {missing}\n   - could not read run log: FileNotFoundError" in out
    assert f"FAIL {wrong_shape}\n   - could not read run log: AttributeError" in out
    assert f"PASS {good}" in out and "Traceback" not in out


def test_an_escalated_run_is_a_problem():
    from harness import check_run_logs

    assert any("escalated" in p for p in check_run_logs.check({"steps": [], "escalated": True}))
