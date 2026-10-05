from harness import llm
from harness.llm import build_messages
from tests.unit.fakes import FakePost, body, make_client, tool_call

TOOLS = [{"type": "function", "function": {"name": "web_search", "parameters": {"type": "object"}}}]


def test_tool_loop_runs_tool_then_returns_final_answer():
    post = FakePost(body("", finish="tool_calls", tool_calls=tool_call("web_search", {"query": "x"})), body("done"))
    calls = []
    messages, final, meta = make_client(post).chat_with_tools(
        build_messages("s", "u"), TOOLS, lambda n, a: calls.append((n, a)) or "RESULT", max_calls=3, max_tokens=500
    )
    assert calls == [("web_search", {"query": "x"})]
    assert final["content"] == "done"
    assert messages[-2] == {"role": "tool", "tool_call_id": "c1", "content": "RESULT"}
    assert messages[-1] == {"role": "assistant", "content": "done"}
    assert "tools" in post.payloads[0]
    assert meta["tool_calls"] == [{"name": "web_search", "args": {"query": "x"}, "ok": True}]
    assert meta["usage"]["total_tokens"] == 30


def test_tool_budget_is_enforced_and_tools_are_withheld():
    post = FakePost(
        body("", finish="tool_calls", tool_calls=tool_call("web_search", {"query": "a"}, "c1")),
        body("", finish="tool_calls", tool_calls=tool_call("web_search", {"query": "b"}, "c2")),
        body("stopped"),
    )
    calls = []
    messages, _, _ = make_client(post).chat_with_tools(
        build_messages("s", "u"), TOOLS, lambda n, a: calls.append(a) or "R", max_calls=1, max_tokens=500
    )
    assert len(calls) == 1
    assert "tools" not in post.payloads[1] and "tools" not in post.payloads[2]
    assert any("budget exhausted" in m["content"] for m in messages if m["role"] == "tool")


def test_loop_ends_even_if_the_model_keeps_requesting_tools():
    post = FakePost(*[body("", finish="tool_calls", tool_calls=tool_call("web_search", {"query": "q"}))] * 3)
    make_client(post).chat_with_tools(build_messages("s", "u"), TOOLS, lambda n, a: "R", max_calls=1, max_tokens=500)
    assert len(post.calls) == 3  # max_calls + 2 turns, then it stops


def test_tool_output_is_truncated():
    post = FakePost(body("", finish="tool_calls", tool_calls=tool_call("web_search", {"query": "a"})), body("ok"))
    messages, _, _ = make_client(post).chat_with_tools(
        build_messages("s", "u"), TOOLS, lambda n, a: "x" * 50_000, max_calls=2, max_tokens=500
    )
    assert len(messages[-2]["content"]) == llm.MAX_TOOL_RESULT_CHARS


def test_bad_tool_arguments_are_reported_not_raised():
    for arguments in ["{not json", "[1, 2]"]:
        bad = [{"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": arguments}}]
        post = FakePost(body("", finish="tool_calls", tool_calls=bad), body("ok"))
        messages, _, meta = make_client(post).chat_with_tools(
            build_messages("s", "u"), TOOLS, lambda n, a: "R", max_calls=2, max_tokens=500
        )
        assert messages[-2]["content"].startswith("error: invalid tool arguments")
        assert meta["tool_calls"] == []


def test_truncated_tool_call_turn_spends_budget_and_is_reported():
    cut = [{"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": '{"query": "half'}}]
    post = FakePost(body("", finish="length", tool_calls=cut), body("answer"))
    calls = []
    messages, final, meta = make_client(post).chat_with_tools(
        build_messages("s", "u"), TOOLS, lambda n, a: calls.append(a) or "R", max_calls=1, max_tokens=500
    )
    assert calls == [] and meta["truncated_turns"] == 1
    assert "tools" not in post.payloads[1]  # the budget is spent, so tools are withdrawn
    assert any("cut off" in m["content"] for m in messages if m["role"] == "tool")
    assert final["content"] == "answer"


def test_malformed_tool_arguments_spend_budget_so_the_loop_ends_with_an_answer():
    bad = [{"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": "{oops"}}]
    post = FakePost(body("", finish="tool_calls", tool_calls=bad), body("answer"))
    _, final, _ = make_client(post).chat_with_tools(build_messages("s", "u"), TOOLS, lambda n, a: "R", max_calls=1, max_tokens=500)
    assert "tools" not in post.payloads[1] and final["content"] == "answer"


def test_truncated_tool_call_is_echoed_with_empty_arguments():
    cut = [{"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": '{"query": "eu ai ac'}}]
    post = FakePost(body("", finish="length", tool_calls=cut), body("answer"))
    make_client(post).chat_with_tools(build_messages("s", "u"), TOOLS, lambda n, a: "R", max_calls=2, max_tokens=500)
    echoed = [m for m in post.payloads[1]["messages"] if m.get("tool_calls")]
    assert echoed and echoed[0]["tool_calls"][0]["function"]["arguments"] == "{}"
