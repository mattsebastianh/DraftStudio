"""Load wire contracts (wires/*.yaml) and validate hop messages against them."""

import yaml
from jsonschema import Draft202012Validator

from harness import config

WIRES_DIR = config.REPO / "wires"


class WireContractError(Exception):
    def __init__(self, wire_id, errors):
        super().__init__(f"message on wire {wire_id} violates its contract: " + "; ".join(errors))
        self.wire_id = wire_id
        self.errors = errors


def has_wire(wire_id):
    return (WIRES_DIR / f"{wire_id}.yaml").exists()


def _clean(node):
    """Strip non-standard `example` keywords, keeping properties that are *named* example."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "example":
                continue
            if key == "properties" and isinstance(value, dict):
                out[key] = {name: _clean(sub) for name, sub in value.items()}
            else:
                out[key] = _clean(value)
        return out
    if isinstance(node, list):
        return [_clean(item) for item in node]
    return node


def message_schema(wire_id):
    wire = yaml.safe_load((WIRES_DIR / f"{wire_id}.yaml").read_text())
    return _clean(wire["message_schema"])


def validate_message(wire_id, message):
    """Return the contract violations of `message` on `wire_id` (an empty list means valid)."""
    validator = Draft202012Validator(message_schema(wire_id))
    errors = sorted(validator.iter_errors(message), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"$.{'.'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors]
