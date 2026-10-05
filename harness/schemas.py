"""Per-agent output contracts (agents/<Agent>/output_schema.json)."""

import json

from harness import config


def output_schema(agent):
    return json.loads((config.REPO / "agents" / agent / "output_schema.json").read_text())
