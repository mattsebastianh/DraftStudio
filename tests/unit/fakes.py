"""Test doubles shared by the harness unit tests. Nothing here touches the network."""

import json

from harness.llm import LLMClient

ENV = {
    "GROQ_API_KEY": "groq-key",
    "GROQ_BASE_URL": "https://groq.test/v1",
    "GROQ_PRIMARY_MODEL": "primary/model",
    "GROQ_FALLBACK_MODEL": "fallback/model",
}
OPENROUTER_ENV = {
    **ENV,
    "OPENROUTER_API_KEY": "or-key",
    "OPENROUTER_BASE_URL": "https://or.test/v1",
    "OPENROUTER_PRIMARY_MODEL": "or/model",
}


def body(content, finish="stop", tool_calls=None):
    """A chat-completions response body."""
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def tool_call(name, args, call_id="c1"):
    return [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]


class FakePost:
    """Stands in for llm.http_post: replays responses (bodies or exceptions) in order and records requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []  # (base_url, api_key, payload)

    def __call__(self, base_url, api_key, payload):
        self.calls.append((base_url, api_key, json.loads(json.dumps(payload))))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def payloads(self):
        return [payload for _, _, payload in self.calls]

    @property
    def urls(self):
        return [url for url, _, _ in self.calls]


def make_client(post, env=ENV):
    return LLMClient(env, post=post, sleep=lambda seconds: None, log=lambda *args: None)
