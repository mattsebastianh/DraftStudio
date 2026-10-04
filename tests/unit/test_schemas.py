import copy
import json

import pytest
from jsonschema import Draft202012Validator

from harness import config, messages, schemas, wires

AGENTS = ["IntakeAgent", "ResearchAgent", "DraftAgent", "ReviewAgent", "DispatchAgent"]
SAMPLES = json.loads((config.REPO / "tests" / "unit" / "fixtures" / "agent_outputs.json").read_text())


def errors(agent, output):
    return [e.message for e in Draft202012Validator(schemas.output_schema(agent)).iter_errors(output)]


def mutated(agent, change):
    sample = copy.deepcopy(SAMPLES[agent])
    change(sample)
    return sample


@pytest.mark.parametrize("agent", AGENTS)
def test_output_schema_is_valid_json_schema(agent):
    Draft202012Validator.check_schema(schemas.output_schema(agent))


@pytest.mark.parametrize("agent", AGENTS)
def test_sample_output_validates(agent):
    assert errors(agent, SAMPLES[agent]) == []


@pytest.mark.parametrize(
    "agent,change",
    [
        ("IntakeAgent", lambda s: s["brief"].update(length=500)),  # the wires carry length as a string
        ("IntakeAgent", lambda s: s.pop("needs_research")),
        ("ResearchAgent", lambda s: s["findings"][0].pop("sources")),
        ("DraftAgent", lambda s: s["draft"].update(content="")),
        ("ReviewAgent", lambda s: s.update(score=120)),
        ("ReviewAgent", lambda s: s["issues"][0].update(severity="blocker")),
        ("DispatchAgent", lambda s: s["package"].pop("delivery_note")),
    ],
)
def test_contract_violations_are_rejected(agent, change):
    assert errors(agent, mutated(agent, change))


def test_review_status_is_advisory_and_optional():
    assert errors("ReviewAgent", mutated("ReviewAgent", lambda s: s.pop("status"))) == []


def test_research_output_schema_mirrors_its_wire():
    wire = wires.message_schema("ResearchAgent_to_DraftAgent")
    out = schemas.output_schema("ResearchAgent")
    assert set(out["properties"]) == set(wire["properties"])
    assert set(out["required"]) == set(wire["required"])


def test_agent_outputs_satisfy_downstream_wires():
    """Each sample output, passed through the message builders, satisfies the next hop's wire."""
    brief = SAMPLES["IntakeAgent"]["brief"]
    dossier = SAMPLES["ResearchAgent"]
    draft = SAMPLES["DraftAgent"]["draft"]
    review = SAMPLES["ReviewAgent"]
    hops = [
        ("IntakeAgent_to_ResearchAgent", messages.intake_to_research(brief)),
        ("ResearchAgent_to_DraftAgent", dossier),
        ("IntakeAgent_to_DraftAgent", messages.intake_to_draft(brief, dossier)),
        ("DraftAgent_to_ReviewAgent", messages.draft_to_review(brief, draft, 0, [])),
        ("ReviewAgent_to_DraftAgent", messages.review_to_draft(brief, draft, review["issues"], 1)),
        ("ReviewAgent_to_DispatchAgent", messages.review_to_dispatch(draft, review, 0, dossier)),
    ]
    for wire_id, message in hops:
        assert wires.validate_message(wire_id, message) == [], wire_id
