"""Shared settings: paths, thresholds, .env loading and per-agent token budgets."""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

QUALITY_THRESHOLD = 80
MAX_REVISION_CYCLES = 3
LENGTH_TOLERANCE = 0.15
MAX_TOOL_CALLS = 6

# Ceiling for any completion budget, including the one-time raise after a truncated reply.
# Groq's qwen/qwen3.8-27b rejects max_tokens above 16,384.
MAX_COMPLETION_TOKENS = 16_384

# agent -> (max_tokens, reasoning_effort). Reasoning models spend completion tokens on reasoning, so each
# budget is about twice the largest completion seen in past runs (gpt-oss-120b: Draft 3.3k, Research 3.0k,
# Review 3.0k, Intake 0.7k, Dispatch 0.7k tokens).
AGENT_BUDGETS = {
    "IntakeAgent": (4_000, "low"),
    "ResearchAgent": (8_000, "medium"),
    "DraftAgent": (8_000, "medium"),
    "ReviewAgent": (6_000, "medium"),
    "DispatchAgent": (3_000, "low"),
}


def load_env(path=None):
    """Read KEY=VALUE pairs from .env, skipping comments and blank lines and unquoting values."""
    env = {}
    for line in (path or REPO / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            env[key.strip()] = value
    return env
