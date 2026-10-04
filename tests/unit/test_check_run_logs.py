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
