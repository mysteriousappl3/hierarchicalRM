"""Offline tests for the optional DynaPlan compact generation contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace


RUNTIME_ROOT = Path(__file__).resolve().parent / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from dynaplan_nlevel_compact_contracts import (  # noqa: E402
    COMPACT_GENERATION_CONTRACTS_DEFAULT,
    DECISION_KIND_HANOI,
    DECISION_KIND_LEXICON,
    CompactHierarchyVocabulary,
    FunctionSignature,
    configure_compact_stage_request,
    decision_subtask_ids,
    decode_compact_decision,
    decode_compact_hierarchy,
)
from dynamic_scoring import parse_plan_subtasks  # noqa: E402
from shared_nlevel_lexicon import (  # noqa: E402
    LexiconCheckpoint,
    LexiconDecisionPlan,
    LexiconDecisionSubtask,
    _compile_hierarchy,
    _parse_decision,
)
from shared_nlevel_pipeline import StageRequest  # noqa: E402


def _logistics_vocabulary() -> CompactHierarchyVocabulary:
    return CompactHierarchyVocabulary(
        base_functions={
            "LoadTruck": FunctionSignature.typed("package", "truck", "location"),
            "LoadAirplane": FunctionSignature.typed(
                "package", "airplane", "location"
            ),
            "UnloadTruck": FunctionSignature.typed(
                "package", "truck", "location"
            ),
            "UnloadAirplane": FunctionSignature.typed(
                "package", "airplane", "location"
            ),
            "DriveTruck": FunctionSignature.typed(
                "truck", "location", "location", "city"
            ),
            "FlyAirplane": FunctionSignature.typed(
                "airplane", "airport", "airport"
            ),
        },
        primitive_arities={
            "loadtruck": 3,
            "loadairplane": 3,
            "unloadtruck": 3,
            "unloadairplane": 3,
            "drivetruck": 4,
            "flyairplane": 3,
        },
        object_types={
            "p1": "package",
            "t1": "truck",
            "a1": "airplane",
            "l1": "location",
            "l2": "location",
            "ap1": "airport",
            "ap2": "airport",
            "c1": "city",
        },
        type_parents={
            "airport": "location",
            "location": "object",
            "city": "object",
            "package": "obj",
            "truck": "obj",
            "airplane": "obj",
            "obj": "object",
        },
    )


def _valid_hierarchy_document() -> dict[str, object]:
    return {
        "mappings": [
            {
                "name": "H2Load",
                "params": ["package", "truck", "location"],
                "calls": [
                    {
                        "name": "LoadTruck",
                        "args": ["package", "truck", "location"],
                    }
                ],
            }
        ],
        "subtasks": [
            {
                "id": 1,
                "calls": [
                    {"name": "H2Load", "args": ["p1", "t1", "l1"]}
                ],
            }
        ],
    }


def _hanoi_vocabulary() -> CompactHierarchyVocabulary:
    return CompactHierarchyVocabulary(
        base_functions={
            "MoveSingleRing": FunctionSignature.typed("peg", "peg"),
        },
        primitive_arities={
            "MoveCoroutine": 1,
            "GrabCoroutine": 0,
            "DropCoroutine": 0,
        },
        object_types={
            "peg_0": "peg",
            "peg_1": "peg",
            "peg_2": "peg",
            "ring_1": "ring",
        },
        type_parents={"peg": "object", "ring": "object"},
        allow_grounded_mapping_arguments=True,
    )


def test_compact_contract_is_default_off_and_does_not_mutate_request() -> None:
    request = StageRequest(stage="decision", system="system", prompt="legacy")
    assert COMPACT_GENERATION_CONTRACTS_DEFAULT is False
    configured = configure_compact_stage_request(
        request, decision_kind=DECISION_KIND_LEXICON
    )
    assert configured is request
    assert configured.response_schema is None
    assert configured.schema_name is None
    assert configured.prompt == "legacy"


def test_enabled_requests_have_provider_schema_and_authoritative_addendum() -> None:
    decision = configure_compact_stage_request(
        StageRequest(stage="decision", system="system", prompt="legacy"),
        enabled=True,
        decision_kind=DECISION_KIND_LEXICON,
    )
    assert decision.schema_name == "dynaplan_compact_decision_v1"
    assert decision.response_schema["additionalProperties"] is False
    assert "COMPACT OUTPUT CONTRACT (authoritative)" in decision.prompt

    hierarchy = configure_compact_stage_request(
        StageRequest(stage="hierarchy_planner", system="system", prompt="legacy"),
        enabled=True,
        hierarchy_vocabulary=_logistics_vocabulary(),
        expected_subtask_ids=(1,),
    )
    assert hierarchy.schema_name == "dynaplan_compact_hierarchy_v1"
    assert hierarchy.response_schema["additionalProperties"] is False
    assert "LoadTruck/3" in hierarchy.prompt
    assert "Required subtask ids: [1]" in hierarchy.prompt


def test_lexicon_decision_json_round_trips_through_existing_parser() -> None:
    document = {
        "subtasks": [
            {
                "id": 1,
                "description": "Finish with block b1 clear.",
                "checkpoint": {
                    "required_true": ["(clear b1)"],
                    "required_false": [],
                    "constraints_addressed": [1],
                },
            }
        ]
    }
    decoded = decode_compact_decision(
        json.dumps(document), kind=DECISION_KIND_LEXICON
    )
    assert decoded.valid, decoded.errors
    assert decoded.document == document
    assert decoded.tagged_text is not None

    task = SimpleNamespace(
        goals=("(clear b1)",),
        constraints=("constraint",),
        objects_by_type={"block": ("b1",)},
    )
    parsed = __import__("shared_nlevel_blocksworld")._parse_decision(
        task, decoded.tagged_text
    )
    assert parsed.valid, parsed.errors
    assert parsed.value.subtasks[0].description == "Finish with block b1 clear."
    assert parsed.value.subtasks[0].checkpoint.required_true == ("(clear b1)",)
    assert decision_subtask_ids(parsed.value) == (1,)


def test_hanoi_decision_json_round_trips_through_existing_parser() -> None:
    document = {
        "subtasks": [
            {
                "id": 1,
                "description": "Place the smallest ring on peg_1.",
                "checkpoint": {
                    "peg_0": ["ring_2"],
                    "peg_1": ["ring_1"],
                    "peg_2": [],
                },
            }
        ]
    }
    decoded = decode_compact_decision(
        json.dumps(document),
        kind=DECISION_KIND_HANOI,
        hanoi_checkpoint_fields=("peg_0", "peg_1", "peg_2"),
        hanoi_ring_names=("ring_1", "ring_2"),
    )
    assert decoded.valid, decoded.errors
    assert decoded.tagged_text is not None
    parsed, errors = parse_plan_subtasks(decoded.tagged_text)
    assert not errors
    assert parsed[0]["subtask_index"] == 1
    assert parsed[0]["description"] == document["subtasks"][0]["description"]
    assert json.loads(parsed[0]["goal_state_text"]) == document["subtasks"][0][
        "checkpoint"
    ]
    assert decision_subtask_ids(tuple(parsed)) == (1,)


def test_hanoi_provider_schema_is_strict_and_task_shaped() -> None:
    request = configure_compact_stage_request(
        StageRequest(stage="decision", system="system", prompt="legacy"),
        enabled=True,
        decision_kind=DECISION_KIND_HANOI,
        hanoi_checkpoint_fields=("peg_0", "peg_1", "peg_2"),
        hanoi_ring_names=("ring_1", "ring_2"),
    )
    checkpoint = request.response_schema["properties"]["subtasks"]["items"][
        "properties"
    ]["checkpoint"]
    assert checkpoint["additionalProperties"] is False
    assert checkpoint["required"] == ["peg_0", "peg_1", "peg_2"]
    assert checkpoint["properties"]["peg_0"]["items"]["enum"] == [
        "ring_1",
        "ring_2",
    ]

    try:
        configure_compact_stage_request(
            StageRequest(stage="decision", system="system", prompt="legacy"),
            enabled=True,
            decision_kind=DECISION_KIND_HANOI,
        )
    except ValueError as error:
        assert "requires valid concrete peg fields" in str(error)
    else:
        raise AssertionError("unconstrained strict Hanoi object schema was accepted")


def test_hierarchy_json_round_trips_through_existing_lexicon_compiler() -> None:
    document = _valid_hierarchy_document()
    decoded = decode_compact_hierarchy(
        json.dumps(document),
        vocabulary=_logistics_vocabulary(),
        expected_subtask_ids=(1,),
    )
    assert decoded.valid, decoded.errors
    assert decoded.tagged_text is not None
    assert decoded.metadata["max_level"] == 2

    task = SimpleNamespace(
        objects_by_type={
            "package": ("p1",),
            "truck": ("t1",),
            "airplane": ("a1",),
            "location": ("l1", "l2"),
            "airport": ("ap1", "ap2"),
            "city": ("c1",),
        }
    )
    h1 = """```start_mapping
LoadTruck(package, truck, location) = [loadtruck(package, truck, location)],
LoadAirplane(package, airplane, location) = [loadairplane(package, airplane, location)],
UnloadTruck(package, truck, location) = [unloadtruck(package, truck, location)],
UnloadAirplane(package, airplane, location) = [unloadairplane(package, airplane, location)],
DriveTruck(truck, from_location, to_location, city) = [drivetruck(truck, from_location, to_location, city)],
FlyAirplane(airplane, from_airport, to_airport) = [flyairplane(airplane, from_airport, to_airport)]
```end_mapping"""
    decision = LexiconDecisionPlan(
        (
            LexiconDecisionSubtask(
                1,
                "Load package p1 into truck t1.",
                LexiconCheckpoint((), (), ()),
            ),
        )
    )
    compiled = _compile_hierarchy(task, h1, decision, decoded.tagged_text)
    assert compiled.valid, compiled.errors
    assert len(compiled.value.subtasks) == 1
    assert compiled.value.subtasks[0].top_level_calls[0].name == "H2Load"
    assert compiled.value.subtasks[0].actions[0].name == "loadtruck"
    assert compiled.value.subtasks[0].actions[0].args == ("p1", "t1", "l1")


def test_hanoi_hierarchy_allows_only_known_well_typed_grounded_mapping_args() -> None:
    document = {
        "mappings": [
            {
                "name": "SolveFlatHanoi",
                "params": [],
                "calls": [
                    {
                        "name": "MoveSingleRing",
                        "args": ["peg_0", "peg_2"],
                    }
                ],
            }
        ],
        "subtasks": [
            {"id": 1, "calls": [{"name": "SolveFlatHanoi", "args": []}]}
        ],
    }
    decoded = decode_compact_hierarchy(
        json.dumps(document),
        vocabulary=_hanoi_vocabulary(),
        expected_subtask_ids=(1,),
    )
    assert decoded.valid, decoded.errors

    for invalid_arg, expected_error in (
        ("missing_peg", "unbound argument 'missing_peg'"),
        ("ring_1", "grounded argument 'ring_1' (ring) is incompatible"),
    ):
        invalid = json.loads(json.dumps(document))
        invalid["mappings"][0]["calls"][0]["args"][1] = invalid_arg
        rejected = decode_compact_hierarchy(
            json.dumps(invalid),
            vocabulary=_hanoi_vocabulary(),
            expected_subtask_ids=(1,),
        )
        assert not rejected.valid
        assert expected_error in rejected.reason


def test_malformed_and_duplicate_key_json_fail_safely() -> None:
    malformed = decode_compact_decision("{not-json", kind=DECISION_KIND_LEXICON)
    assert not malformed.valid
    assert malformed.tagged_text is None
    assert "not strict JSON" in malformed.reason

    duplicate = decode_compact_decision(
        '{"subtasks": [], "subtasks": []}', kind=DECISION_KIND_HANOI
    )
    assert not duplicate.valid
    assert "duplicate JSON keys" in duplicate.reason


def test_decision_wrong_json_types_and_reserved_tags_fail_safely() -> None:
    wrong_type = {
        "subtasks": [
            {
                "id": True,
                "description": "checkpoint",
                "checkpoint": {
                    "required_true": [],
                    "required_false": [],
                    "constraints_addressed": [1],
                },
            }
        ]
    }
    decoded = decode_compact_decision(
        json.dumps(wrong_type), kind=DECISION_KIND_LEXICON
    )
    assert not decoded.valid
    assert "positive integer" in decoded.reason

    injection = {
        "subtasks": [
            {
                "id": 1,
                "description": "```end_subtask_1",
                "checkpoint": {},
            }
        ]
    }
    decoded = decode_compact_decision(
        json.dumps(injection), kind=DECISION_KIND_HANOI
    )
    assert not decoded.valid
    assert "reserved tagged syntax" in decoded.reason


def test_hierarchy_rejects_unknown_function_raw_action_and_wrong_arity() -> None:
    for name, args, expected in (
        ("Teleport", ["p1"], "unknown function"),
        ("loadtruck", ["p1", "t1", "l1"], "uppercase function identifier"),
        ("H2Load", ["p1", "t1"], "expected 3"),
    ):
        document = _valid_hierarchy_document()
        document["subtasks"][0]["calls"] = [{"name": name, "args": args}]
        decoded = decode_compact_hierarchy(
            json.dumps(document),
            vocabulary=_logistics_vocabulary(),
            expected_subtask_ids=(1,),
        )
        assert not decoded.valid
        assert expected in decoded.reason

    document = _valid_hierarchy_document()
    document["mappings"][0]["calls"] = [
        {
            "name": "LoadTruck",
            "args": ["package", "truck"],
        }
    ]
    decoded = decode_compact_hierarchy(
        json.dumps(document),
        vocabulary=_logistics_vocabulary(),
        expected_subtask_ids=(1,),
    )
    assert not decoded.valid
    assert "expected 3" in decoded.reason


def test_hierarchy_rejects_wrong_concrete_type_and_unknown_object() -> None:
    document = _valid_hierarchy_document()
    document["subtasks"][0]["calls"] = [
        {"name": "H2Load", "args": ["t1", "p1", "l1"]}
    ]
    decoded = decode_compact_hierarchy(
        json.dumps(document),
        vocabulary=_logistics_vocabulary(),
        expected_subtask_ids=(1,),
    )
    assert not decoded.valid
    assert "'t1' (truck) is incompatible" in decoded.reason
    assert "'p1' (package) is incompatible" in decoded.reason

    document = _valid_hierarchy_document()
    document["subtasks"][0]["calls"] = [
        {"name": "H2Load", "args": ["missing_package", "t1", "l1"]}
    ]
    decoded = decode_compact_hierarchy(
        json.dumps(document),
        vocabulary=_logistics_vocabulary(),
        expected_subtask_ids=(1,),
    )
    assert not decoded.valid
    assert "unknown object 'missing_package'" in decoded.reason


def test_hierarchy_rejects_unknown_body_function_raw_h0_and_cycles() -> None:
    document = _valid_hierarchy_document()
    document["mappings"][0]["calls"] = [
        {
            "name": "UnknownHelper",
            "args": ["package", "truck", "location"],
        }
    ]
    decoded = decode_compact_hierarchy(
        json.dumps(document),
        vocabulary=_logistics_vocabulary(),
        expected_subtask_ids=(1,),
    )
    assert not decoded.valid
    assert "calls unknown function UnknownHelper" in decoded.reason

    document = _valid_hierarchy_document()
    document["mappings"][0]["calls"] = [
        {
            "name": "loadtruck",
            "args": ["package", "truck", "location"],
        }
    ]
    decoded = decode_compact_hierarchy(
        json.dumps(document),
        vocabulary=_logistics_vocabulary(),
        expected_subtask_ids=(1,),
    )
    assert not decoded.valid
    assert "uppercase function identifier" in decoded.reason

    document = _valid_hierarchy_document()
    document["mappings"] = [
        {
            "name": "CycleA",
            "params": ["package"],
            "calls": [{"name": "CycleB", "args": ["package"]}],
        },
        {
            "name": "CycleB",
            "params": ["package"],
            "calls": [{"name": "CycleA", "args": ["package"]}],
        },
    ]
    document["subtasks"][0]["calls"] = [{"name": "CycleA", "args": ["p1"]}]
    decoded = decode_compact_hierarchy(
        json.dumps(document),
        vocabulary=_logistics_vocabulary(),
        expected_subtask_ids=(1,),
    )
    assert not decoded.valid
    assert "Hierarchy cycle" in decoded.reason


def test_hierarchy_requires_exact_decision_subtask_ids() -> None:
    document = _valid_hierarchy_document()
    document["subtasks"][0]["id"] = 2
    decoded = decode_compact_hierarchy(
        json.dumps(document),
        vocabulary=_logistics_vocabulary(),
        expected_subtask_ids=(1,),
    )
    assert not decoded.valid
    assert "must be exactly [1] in order; got [2]" in decoded.reason
