import json
import shutil

import pytest

from harness import config, run_pipeline, tools, wires
from harness.llm import LLMHTTPError, SchemaValidationError
from tests.unit.fakes import ENV, OPENROUTER_ENV, FakePost, body, make_client, opener_returning, public_resolve, tool_call

INTAKE = {
    "brief": {
        "topic": "Vacation policy",
        "audience": "staff",
        "tone": "warm",
        "length": "10-30 words",
        "key_points": ["25 days vacation"],
        "format": "markdown",
    },
    "work_type": "memo",
    "needs_research": False,
    "routing_plan": ["DraftAgent", "ReviewAgent", "DispatchAgent"],
}
GOOD = "# Vacation Policy\n\nEveryone gets 25 days vacation each year, planned with their manager."
PACKAGE = {"package": {"title": "Vacation Policy", "delivery_note": "Attached.", "status": "ready"}}
REG_URL = "https://eur-lex.europa.eu/eli/reg/2024/1689/oj"


def draft(content):
    return {"draft": {"title": "Vacation Policy", "content": content, "word_count": len(content.split())}}


def review(score):
    return {
        "dimension_scores": {"clarity": score, "accuracy": score, "completeness": score, "tone_alignment": score},
        "score": score,
        "requirements": [],
        "issues": [],
        "status": "approved" if score >= 80 else "revision_required",
    }


@pytest.fixture
def repo(tmp_path):
    for sub in ("agents", "wires"):
        shutil.copytree(config.REPO / sub, tmp_path / sub)
    return tmp_path


def run(repo, *replies, env=ENV, toolbox=None):
    post = FakePost(*[r if isinstance(r, Exception) else body(json.dumps(r)) for r in replies])
    log = run_pipeline.run("Write a vacation policy memo", make_client(post, env), env, repo=repo, toolbox=toolbox)
    return log, post


def test_happy_path_approves_and_writes_deliverable(repo):
    log, post = run(repo, INTAKE, draft(GOOD), review(90), PACKAGE)
    assert not log.get("escalated") and "error" not in log
    assert (repo / log["deliverable"]).read_text().strip() == GOOD
    assert [s["agent"] for s in log["steps"]] == ["IntakeAgent", "DraftAgent", "ReviewAgent", "DispatchAgent"]
    step = log["steps"][2]
    assert step["schema_enforced"] is True and step["validation_retries"] == 0 and step["finish_reasons"] == ["stop"]
    assert step["output"]["status"] == "approved" and len(step["output"]["checks"]) == 5
    dispatch_input = log["steps"][3]["input"]
    assert dispatch_input["draft"]["content"] == GOOD and dispatch_input["review_summary"]["revision_rounds"] == 0
    saved = json.loads((repo / "tests" / "live_runs" / f"run_{log['run_id']}.json").read_text())
    assert saved["final_score"] == 90
    assert not post.responses  # every scripted reply was used


def test_placeholder_forces_revision_then_approves(repo):
    bad = "# Vacation Policy\n\nTODO 25 days vacation."
    log, _ = run(repo, INTAKE, draft(bad), review(95), draft(GOOD), review(90), PACKAGE)
    reviews = [s for s in log["steps"] if s["agent"] == "ReviewAgent"]
    assert reviews[0]["output"]["status"] == "revision_required" and reviews[0]["output"]["status_disagreed"] is True
    assert reviews[1]["output"]["status"] == "approved"
    revision = [s for s in log["steps"] if s["agent"] == "DraftAgent"][1]
    assert revision["wire"] == "ReviewAgent_to_DraftAgent" and revision["input"]["previous_draft"]["content"] == bad
    assert log["steps"][-1]["input"]["review_summary"]["revision_rounds"] == 1


def test_three_failed_revisions_escalate_without_delivery(repo):
    bad = "# Vacation Policy\n\nTODO"
    replies = [INTAKE, draft(bad)]
    for _ in range(config.MAX_REVISION_CYCLES):
        replies += [review(50), draft(bad)]
    replies.append(review(50))
    log, post = run(repo, *replies)
    assert log["escalated"] is True and "deliverable" not in log
    assert not (repo / "deliverables").exists()
    assert not post.responses


def test_research_without_search_key_fails_soft_and_flags_the_run(repo):
    log, _ = run(repo, {**INTAKE, "needs_research": True}, draft(GOOD), review(90), PACKAGE)
    research = log["steps"][1]
    assert research["agent"] == "ResearchAgent" and research["skipped"] is True
    assert research["output"]["findings"] == [] and research["output"]["confidence"] == 30
    assert log["steps"][2]["input"]["dossier"] == research["output"]
    assert any("research confidence 30" in flag for flag in log["flags"])
    assert "deliverable" in log


def test_research_with_tools_feeds_a_sourced_dossier_downstream(repo):
    env = {**ENV, "SEARCH_API_KEY": "real"}
    search_body = {"results": [{"title": "Regulation (EU) 2024/1689", "url": REG_URL, "content": "AI Act"}]}
    dossier = {
        "topic": "Vacation policy",
        "findings": [{"claim": "The AI Act is Regulation (EU) 2024/1689", "sources": [REG_URL], "confidence": 90}],
        "gaps": [],
        "confidence": 80,
        "sources": [],
    }
    box = tools.ToolBox(env, opener=opener_returning(search_body), resolve=public_resolve)
    post = FakePost(
        body(json.dumps({**INTAKE, "needs_research": True})),
        body("", finish="tool_calls", tool_calls=tool_call("web_search", {"query": "vacation law"})),
        body("Found the regulation."),
        body(json.dumps(dossier)),
        body(json.dumps(draft(GOOD + " Source: eur-lex.europa.eu"))),
        body(json.dumps(review(90))),
        body(json.dumps(PACKAGE)),
    )
    log = run_pipeline.run("Write a vacation policy memo", make_client(post, env), env, repo=repo, toolbox=box)
    research = log["steps"][1]
    assert research["skipped"] is False and research["output"]["sources"] == [{"title": "Regulation (EU) 2024/1689", "url": REG_URL}]
    assert log["steps"][-1]["input"]["sources"] == [{"title": "Regulation (EU) 2024/1689", "url": REG_URL}]
    assert "flags" not in log and not post.responses


def test_a_revision_after_research_receives_the_sources(repo):
    env = {**ENV, "SEARCH_API_KEY": "real"}
    search_body = {"results": [{"title": "Regulation (EU) 2024/1689", "url": REG_URL, "content": "AI Act"}]}
    dossier = {
        "topic": "Vacation policy",
        "findings": [{"claim": "The AI Act is Regulation (EU) 2024/1689", "sources": [REG_URL], "confidence": 90}],
        "gaps": [],
        "confidence": 80,
        "sources": [],
    }
    box = tools.ToolBox(env, opener=opener_returning(search_body), resolve=public_resolve)
    post = FakePost(
        body(json.dumps({**INTAKE, "needs_research": True})),
        body("", finish="tool_calls", tool_calls=tool_call("web_search", {"query": "vacation law"})),
        body("Found the regulation."),
        body(json.dumps(dossier)),
        body(json.dumps(draft(GOOD))),  # cites nothing: citations_present fails
        body(json.dumps(review(70))),
        body(json.dumps(draft(GOOD + " Source: eur-lex.europa.eu"))),
        body(json.dumps(review(90))),
        body(json.dumps(PACKAGE)),
    )
    log = run_pipeline.run("Write a vacation policy memo", make_client(post, env), env, repo=repo, toolbox=box)
    revision = [s for s in log["steps"] if s["agent"] == "DraftAgent"][1]
    assert revision["wire"] == "ReviewAgent_to_DraftAgent"
    assert revision["input"]["sources"] == [{"title": "Regulation (EU) 2024/1689", "url": REG_URL}]
    revision_prompt = post.payloads[6]["messages"][-1]["content"]
    assert REG_URL in revision_prompt and "do not add sources that are not listed" in revision_prompt
    assert not post.responses


def test_groq_refusal_moves_the_run_to_openrouter(repo):
    denied = LLMHTTPError(403, "Access denied. Please check your network settings.")
    log, post = run(repo, denied, INTAKE, draft(GOOD), review(90), PACKAGE, env=OPENROUTER_ENV)
    assert log["fallback_provider_used"] == "openrouter"
    assert post.urls[0] == "https://groq.test/v1" and set(post.urls[1:]) == {"https://or.test/v1"}
    assert {s["provider"] for s in log["steps"]} == {"openrouter"}


def test_a_failing_step_still_writes_the_run_log(repo):
    with pytest.raises(LLMHTTPError):
        run(repo, LLMHTTPError(401, "invalid api key"))
    logs = list((repo / "tests" / "live_runs").glob("run_*.json"))
    assert len(logs) == 1
    saved = json.loads(logs[0].read_text())
    assert saved["error"].startswith("LLMHTTPError") and saved["steps"] == []
    assert saved["failed_step"] == "IntakeAgent" and "bad_reply" not in saved


def test_existing_deliverables_are_never_overwritten(repo):
    (repo / "deliverables").mkdir()
    (repo / "deliverables" / "vacation_policy.md").write_text("earlier deliverable\n")
    log, _ = run(repo, INTAKE, draft(GOOD), review(90), PACKAGE)
    assert (repo / "deliverables" / "vacation_policy.md").read_text() == "earlier deliverable\n"
    assert log["deliverable"] == f"deliverables/vacation_policy_{log['run_id']}.md"


def only_log(repo):
    (path,) = (repo / "tests" / "live_runs").glob("run_*.json")
    return json.loads(path.read_text())


def test_invalid_research_dossier_keeps_its_raw_reply_and_names_the_step(repo):
    env = {**ENV, "SEARCH_API_KEY": "real"}
    search_body = {"results": [{"title": "Regulation (EU) 2024/1689", "url": REG_URL, "content": "AI Act"}]}
    box = tools.ToolBox(env, opener=opener_returning(search_body), resolve=public_resolve)
    invalid = json.dumps({"topic": "Vacation policy"})  # no findings, gaps, confidence or sources
    post = FakePost(
        body(json.dumps({**INTAKE, "needs_research": True})),
        body("", finish="tool_calls", tool_calls=tool_call("web_search", {"query": "vacation law"})),
        body("Found the regulation."),
        body(invalid),
        body(invalid),
        body(invalid),
    )
    with pytest.raises(SchemaValidationError):
        run_pipeline.run("Write a vacation policy memo", make_client(post, env), env, repo=repo, toolbox=box)
    saved = only_log(repo)
    assert saved["failed_step"] == "ResearchAgent" and saved["error"].startswith("SchemaValidationError")
    assert (repo / saved["bad_reply"]).read_text() == invalid
    assert not post.responses


def test_http_error_at_a_later_step_names_that_step(repo):
    with pytest.raises(LLMHTTPError):
        run(repo, INTAKE, LLMHTTPError(401, "invalid api key"))
    saved = only_log(repo)
    assert saved["error"].startswith("LLMHTTPError") and saved["failed_step"] == "DraftAgent"
    assert "bad_reply" not in saved and [s["agent"] for s in saved["steps"]] == ["IntakeAgent"]


def test_a_client_without_fallback_attributes_does_not_mask_the_original_error(repo):
    class BareClient:
        def chat_structured(self, *args, **kwargs):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        run_pipeline.run("Write a vacation policy memo", BareClient(), ENV, repo=repo)
    saved = only_log(repo)
    assert saved["error"] == "RuntimeError: boom" and saved["failed_step"] == "IntakeAgent"
    assert "fallback_model_used" not in saved


def test_a_failing_log_write_does_not_replace_the_run_error(repo, monkeypatch, capsys):
    monkeypatch.setattr(run_pipeline, "_live_runs_dir", lambda repo: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(LLMHTTPError):
        run(repo, LLMHTTPError(401, "invalid api key"))
    assert "could not write run log: disk full" in capsys.readouterr().out


def test_a_failing_log_write_on_a_good_run_propagates(repo, monkeypatch):
    monkeypatch.setattr(run_pipeline, "_live_runs_dir", lambda repo: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        run(repo, INTAKE, draft(GOOD), review(90), PACKAGE)


def test_only_the_client_hop_is_unwired_and_every_other_hop_has_a_wire_file(repo):
    assert run_pipeline.UNWIRED == {"client_to_IntakeAgent"}
    assert not wires.has_wire("client_to_IntakeAgent")
    log, _ = run(repo, {**INTAKE, "needs_research": True}, draft(GOOD), review(90), PACKAGE)
    for step in log["steps"]:
        assert step["wire"] in run_pipeline.UNWIRED or wires.has_wire(step["wire"])


def test_a_missing_wire_file_fails_closed(repo, monkeypatch):
    monkeypatch.setattr(wires, "WIRES_DIR", repo / "no_wires")
    with pytest.raises(FileNotFoundError):
        run(repo, INTAKE, draft(GOOD))
    assert only_log(repo)["failed_step"] == "DraftAgent"
