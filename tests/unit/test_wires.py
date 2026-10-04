import json

import pytest
import yaml
from jsonschema import Draft202012Validator

from harness import config, wires

# The wires the harness sends messages on, with the version this plan sets.
HARNESS_WIRES = {
    "IntakeAgent_to_ResearchAgent": "1.1",
    "ResearchAgent_to_DraftAgent": "1.1",
    "IntakeAgent_to_DraftAgent": "1.1",
    "DraftAgent_to_ReviewAgent": "1.1",
    "ReviewAgent_to_DraftAgent": "1.2",
    "ReviewAgent_to_DispatchAgent": "1.2",
}


def all_wire_ids():
    return sorted(p.stem for p in (config.REPO / "wires").glob("*.yaml"))


def wire_doc(wire_id):
    return yaml.safe_load((config.REPO / "wires" / f"{wire_id}.yaml").read_text())


def tool_params(agent, tool_name):
    for tool in json.loads((config.REPO / "agents" / agent / "tools.json").read_text()):
        if tool["name"] == tool_name:
            return tool["parameters"]
    raise AssertionError(f"{agent} has no tool {tool_name}")


def test_there_are_wires():
    assert len(all_wire_ids()) == 9


@pytest.mark.parametrize("wire_id", all_wire_ids())
def test_every_wire_schema_is_valid_json_schema(wire_id):
    Draft202012Validator.check_schema(wires.message_schema(wire_id))


def test_example_keywords_are_stripped_but_property_named_example_survives():
    cleaned = wires._clean({"type": "object", "example": 1, "properties": {"example": {"type": "string", "example": "x"}}})
    assert "example" not in cleaned
    assert cleaned["properties"] == {"example": {"type": "string"}}


def test_validate_message_reports_missing_required():
    errors = wires.validate_message("ReviewAgent_to_DispatchAgent", {})
    assert errors and "draft" in errors[0]


def test_validate_message_ok():
    assert wires.validate_message("ReviewAgent_to_DispatchAgent", {"draft": {"title": "t", "content": "c"}}) == []


def test_has_wire():
    assert wires.has_wire("IntakeAgent_to_DraftAgent")
    assert not wires.has_wire("client_to_IntakeAgent")


@pytest.mark.parametrize("wire_id,version", sorted(HARNESS_WIRES.items()))
def test_harness_wires_are_versioned_and_closed(wire_id, version):
    doc = wire_doc(wire_id)
    assert doc["wire"]["version"] == version
    assert doc["message_schema"]["additionalProperties"] is False
    assert any("undocumented" in e for e in wires.validate_message(wire_id, {"undocumented": 1}))


@pytest.mark.parametrize("wire_id", sorted(HARNESS_WIRES))
def test_both_agents_tool_definitions_mirror_the_wire(wire_id):
    """Project rule: a wire change updates BOTH agents' tools.json."""
    doc = wire_doc(wire_id)
    schema = doc["message_schema"]
    sender, receiver = doc["sender"]["agent"], doc["receiver"]["agent"]
    for agent, tool_name in [(sender, f"send_to_{receiver}"), (receiver, f"receive_from_{sender}")]:
        params = tool_params(agent, tool_name)
        if wire_id == "ResearchAgent_to_DraftAgent":  # these tools wrap the message in a `dossier` object
            params = params["properties"]["dossier"]
        assert set(params["properties"]) == set(schema["properties"]), (agent, tool_name)
        assert set(params.get("required", [])) == set(schema.get("required", [])), (agent, tool_name)
        assert params.get("additionalProperties") is False, (agent, tool_name)
