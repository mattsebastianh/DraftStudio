import pytest

from harness import config
from harness.llm import LLMHTTPError, SchemaValidationError, TruncatedReply, build_messages
from harness.urls import require_safe_base_url
from tests.unit.fakes import ENV, OPENROUTER_ENV, FakePost, body, make_client

SCHEMA = {"type": "object", "required": ["score"], "properties": {"score": {"type": "integer"}}}
MSGS = build_messages("sys", "user asks for JSON")
QUOTA = "Rate limit reached for model on tokens per day (TPD): Limit 200000, Used 199990, Requested 900"
DENIED = "Access denied. Please check your network settings."


# --- structured output ---------------------------------------------------------


def test_schema_enforced_success():
    post = FakePost(body('{"score": 90}'))
    data, meta = make_client(post).chat_structured(MSGS, SCHEMA, "R", 1000)
    assert data == {"score": 90}
    assert meta["schema_enforced"] is True and meta["validation_retries"] == 0
    assert meta["provider"] == "groq" and meta["model"] == "primary/model"
    assert post.payloads[0]["response_format"]["type"] == "json_schema"
    assert post.urls == ["https://groq.test/v1"]
    assert meta["usage"]["total_tokens"] == 15


def test_falls_back_to_json_object_and_caches_per_provider_model():
    unsupported = LLMHTTPError(400, "response_format json_schema is not supported with this model")
    post = FakePost(unsupported, body('{"score": 1}'), body('{"score": 2}'))
    client = make_client(post)
    _, meta1 = client.chat_structured(MSGS, SCHEMA, "R", 1000)
    _, meta2 = client.chat_structured(MSGS, SCHEMA, "R", 1000)
    assert meta1["schema_enforced"] is False and meta2["schema_enforced"] is False
    assert [p["response_format"]["type"] for p in post.payloads] == ["json_schema", "json_object", "json_object"]
    assert client.schema_mode == {"groq:primary/model": "json_object"}
    assert "JSON Schema" in post.payloads[1]["messages"][-1]["content"]  # JSON mode carries the schema in the prompt


def test_validation_failure_retries_with_error_text():
    post = FakePost(body('{"score": "high"}'), body('{"score": 7}'))
    data, meta = make_client(post).chat_structured(MSGS, SCHEMA, "R", 1000)
    assert data == {"score": 7} and meta["validation_retries"] == 1
    retry = post.payloads[1]["messages"]
    assert retry[-2] == {"role": "assistant", "content": '{"score": "high"}'}
    assert "failed validation" in retry[-1]["content"] and "score" in retry[-1]["content"]


def test_validation_gives_up_after_max_retries():
    post = FakePost(*[body('{"score": "x"}')] * 3)
    with pytest.raises(SchemaValidationError) as exc:
        make_client(post).chat_structured(MSGS, SCHEMA, "R", 1000)
    assert exc.value.raw == '{"score": "x"}'
    assert len(post.calls) == 3


def test_non_json_reply_uses_extract_json_and_is_flagged():
    post = FakePost(body('Sure!\n```json\n{"score": 3}\n```'))
    data, meta = make_client(post).chat_structured(MSGS, SCHEMA, "R", 1000)
    assert data == {"score": 3} and meta["used_extract_json"] is True


def test_provider_json_validate_failure_counts_as_a_validation_retry():
    """Groq answers 400 json_validate_failed when the model's JSON breaks: retryable, not 'unsupported'."""
    detail = (
        '{"error": {"message": "Generated JSON does not match the expected schema (response_format).", '
        '"code": "json_validate_failed", "failed_generation": "{\\"score\\": \\"x\\"}"}}'
    )
    post = FakePost(LLMHTTPError(400, detail), body('{"score": 4}'))
    client = make_client(post)
    data, meta = client.chat_structured(MSGS, SCHEMA, "R", 1000)
    assert data == {"score": 4} and meta["validation_retries"] == 1
    assert client.schema_mode == {}
    assert post.payloads[1]["messages"][-2] == {"role": "assistant", "content": '{"score": "x"}'}


# --- budgets ---------------------------------------------------------------------


def test_truncation_raises_budget_once_then_succeeds():
    post = FakePost(body('{"sco', finish="length"), body('{"score": 4}'))
    data, meta = make_client(post).chat_structured(MSGS, SCHEMA, "R", 100)
    assert data == {"score": 4}
    assert [p["max_tokens"] for p in post.payloads] == [100, 150]
    assert meta["finish_reasons"] == ["length", "stop"]


def test_truncation_twice_raises():
    post = FakePost(body("{", finish="length"), body("{", finish="length"))
    with pytest.raises(TruncatedReply):
        make_client(post).chat_structured(MSGS, SCHEMA, "R", 100)


def test_raised_budget_never_exceeds_the_completion_cap():
    post = FakePost(body("{", finish="length"), body('{"score": 1}'))
    make_client(post).chat_structured(MSGS, SCHEMA, "R", 12_000)
    assert post.payloads[1]["max_tokens"] == config.MAX_COMPLETION_TOKENS


def test_truncation_at_the_cap_is_not_retried():
    post = FakePost(body("{", finish="length"))
    with pytest.raises(TruncatedReply):
        make_client(post).chat_structured(MSGS, SCHEMA, "R", config.MAX_COMPLETION_TOKENS)
    assert len(post.calls) == 1


def test_request_too_large_for_the_rate_limit_retries_with_a_smaller_budget():
    too_large = LLMHTTPError(
        413,
        "Request too large for model `primary/model` on tokens per minute (TPM): Limit 8000, Requested 12500, "
        "please reduce your message size and try again.",
    )
    post = FakePost(too_large, body('{"score": 5}'))
    make_client(post).chat_structured(MSGS, SCHEMA, "R", 10_000)
    assert [p["max_tokens"] for p in post.payloads] == [10_000, 10_000 - 4_500 - 256]


# --- retries and the Groq model fallback --------------------------------------------


def test_daily_quota_switches_model_and_stays_switched():
    post = FakePost(LLMHTTPError(429, QUOTA), body('{"score": 5}'), body('{"score": 6}'))
    client = make_client(post)
    client.chat_structured(MSGS, SCHEMA, "R", 1000)
    client.chat_structured(MSGS, SCHEMA, "R", 1000)
    assert [p["model"] for p in post.payloads] == ["primary/model", "fallback/model", "fallback/model"]
    assert client.active_model == "fallback/model" and client.fallback_model_used == "fallback/model"


def test_fallback_model_without_schema_support_still_works():
    """Schema support is tracked per provider and model, so a mid-run model swap is safe."""
    post = FakePost(LLMHTTPError(429, QUOTA), LLMHTTPError(400, "json_schema unsupported"), body('{"score": 8}'))
    data, meta = make_client(post).chat_structured(MSGS, SCHEMA, "R", 1000)
    assert data == {"score": 8} and meta["schema_enforced"] is False
    assert [p["model"] for p in post.payloads] == ["primary/model", "fallback/model", "fallback/model"]


def test_retryable_http_error_retries_then_succeeds():
    post = FakePost(LLMHTTPError(503, "busy"), body('{"score": 9}'))
    data, _ = make_client(post).chat_structured(MSGS, SCHEMA, "R", 1000)
    assert data == {"score": 9}


def test_response_without_choices_is_retried():
    post = FakePost({"error": {"message": "upstream failed"}}, body('{"score": 9}'))
    data, _ = make_client(post).chat_structured(MSGS, SCHEMA, "R", 1000)
    assert data == {"score": 9}


def test_non_retryable_error_without_openrouter_propagates():
    post = FakePost(LLMHTTPError(401, "bad key"))
    with pytest.raises(LLMHTTPError):
        make_client(post).chat_structured(MSGS, SCHEMA, "R", 1000)
    assert len(post.calls) == 1


def test_reasoning_effort_only_sent_to_gpt_oss_models():
    post = FakePost(body('{"score": 1}'))
    gpt_oss = make_client(post, {**ENV, "GROQ_PRIMARY_MODEL": "openai/gpt-oss-120b"})
    gpt_oss.chat_structured(MSGS, SCHEMA, "R", 1000, reasoning_effort="low")
    assert post.payloads[0]["reasoning_effort"] == "low"
    post2 = FakePost(body('{"score": 1}'))
    make_client(post2).chat_structured(MSGS, SCHEMA, "R", 1000, reasoning_effort="low")
    assert "reasoning_effort" not in post2.payloads[0]


# --- cross-provider fallback (ported from tests/unit/test_harness_provider_fallback.py) ---


def test_groq_success_does_not_touch_openrouter():
    post = FakePost(body('{"score": 1}'))
    client = make_client(post, OPENROUTER_ENV)
    client.chat_structured(MSGS, SCHEMA, "R", 1000)
    assert post.urls == ["https://groq.test/v1"]
    assert client.fallback_provider_used is None


def test_groq_refusal_switches_to_openrouter_and_sticks():
    post = FakePost(LLMHTTPError(403, DENIED), body('{"score": 1}'), body('{"score": 2}'))
    client = make_client(post, OPENROUTER_ENV)
    _, meta = client.chat_structured(MSGS, SCHEMA, "R", 1000)
    client.chat_structured(MSGS, SCHEMA, "R", 1000)
    assert post.urls == ["https://groq.test/v1", "https://or.test/v1", "https://or.test/v1"]
    assert [p["model"] for p in post.payloads[1:]] == ["or/model", "or/model"]
    assert post.calls[1][1] == "or-key"
    assert meta["provider"] == "openrouter" and client.fallback_provider_used == "openrouter"


def test_connection_errors_exhaust_retries_then_switch_provider():
    post = FakePost(*[LLMHTTPError(0, "timed out")] * 5, body('{"score": 1}'))
    make_client(post, OPENROUTER_ENV).chat_structured(MSGS, SCHEMA, "R", 1000)
    assert post.urls.count("https://groq.test/v1") == 5 and post.urls[-1] == "https://or.test/v1"


def test_both_groq_models_out_of_daily_quota_switch_to_openrouter():
    post = FakePost(LLMHTTPError(429, QUOTA), LLMHTTPError(429, QUOTA), body('{"score": 1}'))
    make_client(post, OPENROUTER_ENV).chat_structured(MSGS, SCHEMA, "R", 1000)
    assert [p["model"] for p in post.payloads] == ["primary/model", "fallback/model", "or/model"]


def test_without_a_real_openrouter_key_the_groq_error_propagates():
    env = {**OPENROUTER_ENV, "OPENROUTER_API_KEY": "your-openrouter-api-key-here"}
    post = FakePost(LLMHTTPError(403, DENIED))
    with pytest.raises(LLMHTTPError):
        make_client(post, env).chat_structured(MSGS, SCHEMA, "R", 1000)


def test_both_providers_failing_raises():
    post = FakePost(LLMHTTPError(403, DENIED), LLMHTTPError(403, "denied too"))
    with pytest.raises(LLMHTTPError):
        make_client(post, OPENROUTER_ENV).chat_structured(MSGS, SCHEMA, "R", 1000)


def test_schema_mode_is_tracked_per_provider():
    post = FakePost(
        LLMHTTPError(400, "json_schema is not supported"),  # groq: downgrade to JSON mode
        body('{"score": 1}'),
        LLMHTTPError(403, DENIED),  # groq refuses: the rest of the run is on OpenRouter
        body('{"score": 2}'),
        body('{"score": 3}'),
    )
    client = make_client(post, OPENROUTER_ENV)
    for _ in range(3):
        client.chat_structured(MSGS, SCHEMA, "R", 1000)
    assert post.urls[4] == "https://or.test/v1"
    assert post.payloads[4]["response_format"]["type"] == "json_schema"


# --- base URL safety (ported) --------------------------------------------------------


@pytest.mark.parametrize("url", ["http://api.example.com/v1", "ftp://api.example.com", "file:///etc/passwd", "api.example.com/v1"])
def test_rejects_non_https_remote_base_urls(url):
    with pytest.raises(ValueError):
        require_safe_base_url(url)


@pytest.mark.parametrize("url", ["https://api.groq.com/openai/v1", "http://localhost:11434/v1", "http://127.0.0.1:8080/v1"])
def test_allows_https_and_local_http(url):
    require_safe_base_url(url)


def test_client_never_sends_a_key_to_an_http_base_url():
    post = FakePost(body('{"score": 1}'))
    client = make_client(post, {**ENV, "GROQ_BASE_URL": "http://api.example.com/v1"})
    with pytest.raises(ValueError):
        client.chat_structured(MSGS, SCHEMA, "R", 1000)
    assert post.calls == []
