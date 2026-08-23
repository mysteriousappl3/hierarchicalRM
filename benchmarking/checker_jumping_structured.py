from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from checker_jumping_scoring import (
    H1_NAME,
    PRIMITIVE,
    FunctionCall,
    FunctionMapping,
    expand_calls,
    infer_levels,
    validate_h1,
)
from checker_jumping_task import CheckerJumpingTask, validate_board


BOARD_SCHEMA: Dict[str, object] = {
    "type": "array",
    "items": {"type": "string", "enum": ["R", "B", "_"]},
}

DECISION_SCHEMA: Dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "subtasks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "integer"},
                    "objective": {"type": "string"},
                    "goal_state": BOARD_SCHEMA,
                },
                "required": ["id", "objective", "goal_state"],
            },
        }
    },
    "required": ["subtasks"],
}

CALL_SCHEMA: Dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "function": {"type": "string"},
        "arguments": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["function", "arguments"],
}

HIERARCHY_SCHEMA: Dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "functions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "level": {"type": "integer"},
                    "parameters": {"type": "array", "items": {"type": "string"}},
                    "body": {"type": "array", "items": CALL_SCHEMA},
                },
                "required": ["name", "level", "parameters", "body"],
            },
        },
        "dispatch": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "subtask_id": {"type": "integer"},
                    "function": {"type": "string"},
                    "arguments": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["subtask_id", "function", "arguments"],
            },
        },
    },
    "required": ["functions", "dispatch"],
}


@dataclass(frozen=True)
class DecisionSubtask:
    id: int
    objective: str
    goal_state: List[str]


@dataclass
class DecisionParseResult:
    format_valid: bool
    semantic_valid: bool
    subtasks: List[DecisionSubtask] = field(default_factory=list)
    format_errors: List[str] = field(default_factory=list)
    semantic_errors: List[str] = field(default_factory=list)
    payload: Optional[Dict[str, object]] = None

    @property
    def errors(self) -> List[str]:
        return _unique(self.format_errors + self.semantic_errors)

    @property
    def valid(self) -> bool:
        return self.format_valid and self.semantic_valid


@dataclass
class HierarchyCompileResult:
    format_valid: bool
    hierarchy_graph_valid: bool
    parameter_binding_valid: bool
    dispatch_valid: bool
    hierarchy_useful: bool
    mappings: Dict[str, FunctionMapping] = field(default_factory=dict)
    subtasks: List[List[FunctionCall]] = field(default_factory=list)
    levels: Dict[str, int] = field(default_factory=dict)
    max_level: int = 0
    mapping_count_by_level: Dict[int, int] = field(default_factory=dict)
    function_reuse_counts: Dict[str, int] = field(default_factory=dict)
    compression_ratio: Optional[float] = None
    format_errors: List[str] = field(default_factory=list)
    hierarchy_errors: List[str] = field(default_factory=list)
    binding_errors: List[str] = field(default_factory=list)
    dispatch_errors: List[str] = field(default_factory=list)
    usefulness_errors: List[str] = field(default_factory=list)
    payload: Optional[Dict[str, object]] = None

    @property
    def errors(self) -> List[str]:
        return _unique(
            self.format_errors
            + self.hierarchy_errors
            + self.binding_errors
            + self.dispatch_errors
            + self.usefulness_errors
        )

    @property
    def valid(self) -> bool:
        return all(
            (
                self.format_valid,
                self.hierarchy_graph_valid,
                self.parameter_binding_valid,
                self.dispatch_valid,
                self.hierarchy_useful,
            )
        )


def parse_json_object(text: str) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            stripped = "\n".join(lines[1:-1]).strip()
    decoder = json.JSONDecoder()
    try:
        payload, end = decoder.raw_decode(stripped)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc.msg} at character {exc.pos}"
    if stripped[end:].strip():
        return None, "Unexpected explanatory text after the JSON object"
    if not isinstance(payload, dict):
        return None, "Top-level JSON value must be an object"
    return payload, None


def parse_decision_output(
    text: str, task: CheckerJumpingTask
) -> DecisionParseResult:
    payload, error = parse_json_object(text)
    if error or payload is None:
        return DecisionParseResult(False, False, format_errors=[error or "No JSON object"])
    format_errors: List[str] = []
    semantic_errors: List[str] = []
    if set(payload) != {"subtasks"}:
        format_errors.append("Decision output must contain exactly the subtasks field")
    raw_subtasks = payload.get("subtasks")
    if not isinstance(raw_subtasks, list) or not raw_subtasks:
        return DecisionParseResult(
            False,
            False,
            format_errors=["subtasks must be a non-empty array"],
            payload=payload,
        )

    subtasks: List[DecisionSubtask] = []
    for position, raw in enumerate(raw_subtasks, start=1):
        if not isinstance(raw, dict):
            format_errors.append(f"Subtask {position} must be an object")
            continue
        if set(raw) != {"id", "objective", "goal_state"}:
            format_errors.append(
                f"Subtask {position} must contain exactly id, objective, and goal_state"
            )
        subtask_id = raw.get("id")
        objective = raw.get("objective")
        goal_state = raw.get("goal_state")
        if not isinstance(subtask_id, int) or isinstance(subtask_id, bool):
            format_errors.append(f"Subtask {position} id must be an integer")
            continue
        if not isinstance(objective, str):
            format_errors.append(f"Subtask {subtask_id} objective must be a string")
            continue
        if not objective.strip():
            semantic_errors.append(f"Subtask {subtask_id} objective must not be empty")
        board_errors = validate_board(goal_state, task)
        semantic_errors.extend(
            f"Subtask {subtask_id} goal_state: {message}" for message in board_errors
        )
        if isinstance(goal_state, list) and not board_errors:
            subtasks.append(DecisionSubtask(subtask_id, objective.strip(), list(goal_state)))

    ids = [subtask.id for subtask in subtasks]
    expected_ids = list(range(1, len(raw_subtasks) + 1))
    if ids != expected_ids:
        semantic_errors.append(f"Subtask ids must be exactly {expected_ids}; got {ids}")
    if subtasks and subtasks[-1].goal_state != task.goal:
        semantic_errors.append("The final DecisionBot subtask goal must exactly equal the task goal")
    return DecisionParseResult(
        format_valid=not format_errors,
        semantic_valid=not format_errors and not semantic_errors,
        subtasks=subtasks,
        format_errors=_unique(format_errors),
        semantic_errors=_unique(semantic_errors),
        payload=payload,
    )


def compile_hierarchy_output(
    text: str,
    task: CheckerJumpingTask,
    decision: DecisionParseResult,
) -> HierarchyCompileResult:
    payload, error = parse_json_object(text)
    if error or payload is None:
        return HierarchyCompileResult(
            False,
            False,
            False,
            False,
            False,
            format_errors=[error or "No JSON object"],
        )

    format_errors: List[str] = []
    graph_errors: List[str] = []
    binding_errors: List[str] = []
    dispatch_errors: List[str] = []
    usefulness_errors: List[str] = []
    if set(payload) != {"functions", "dispatch"}:
        format_errors.append("Hierarchy output must contain exactly functions and dispatch")
    raw_functions = payload.get("functions")
    raw_dispatch = payload.get("dispatch")
    if not isinstance(raw_functions, list) or not raw_functions:
        format_errors.append("functions must be a non-empty array")
        raw_functions = []
    if not isinstance(raw_dispatch, list) or not raw_dispatch:
        format_errors.append("dispatch must be a non-empty array")
        raw_dispatch = []

    mappings: Dict[str, FunctionMapping] = {}
    declared_levels: Dict[str, int] = {}
    for index, raw in enumerate(raw_functions, start=1):
        parsed = _parse_function(raw, index, format_errors)
        if parsed is None:
            continue
        mapping, declared = parsed
        if mapping.name in mappings:
            graph_errors.append(f"Duplicate function name {mapping.name}")
            continue
        mappings[mapping.name] = mapping
        declared_levels[mapping.name] = declared

    levels, inferred_errors, max_level = infer_levels(mappings)
    graph_errors.extend(inferred_errors)
    h1_valid, h1_reason = validate_h1(
        {name: mapping for name, mapping in mappings.items() if levels.get(name) == 1}
    )
    if not h1_valid:
        graph_errors.append(h1_reason)
    for name, mapping in mappings.items():
        inferred = levels.get(name, 0)
        if declared_levels.get(name) != inferred:
            graph_errors.append(
                f"{name} declares H{declared_levels.get(name)} but its graph infers H{inferred}"
            )
        if inferred == 1 and name != H1_NAME:
            graph_errors.append(f"Unexpected H1 function {name}; H1 is exactly {H1_NAME}")
        if name != H1_NAME and any(call.name == PRIMITIVE for call in mapping.calls):
            graph_errors.append(f"{name} calls H0 directly; only H1 may call {PRIMITIVE}")
        for call in mapping.calls:
            callee_level = 0 if call.name == PRIMITIVE else levels.get(call.name)
            if callee_level is not None and callee_level >= inferred:
                graph_errors.append(f"{name} may call only lower-level functions")
    if max_level < 2:
        graph_errors.append("Complete framework requires at least H1 and H2")

    concrete = {"R", "B"} | {str(index) for index in range(task.board_length)}
    for mapping in mappings.values():
        if len(set(mapping.params)) != len(mapping.params):
            binding_errors.append(f"{mapping.name} has duplicate parameter names")
        allowed = set(mapping.params) | concrete
        for call in mapping.calls:
            target = mappings.get(call.name)
            expected_arity = 3 if call.name == PRIMITIVE else (
                len(target.params) if target is not None else None
            )
            if expected_arity is not None and len(call.args) != expected_arity:
                binding_errors.append(
                    f"{mapping.name} calls {call.name} with {len(call.args)} arguments; expected {expected_arity}"
                )
            for argument in call.args:
                if argument not in allowed:
                    binding_errors.append(
                        f"{mapping.name} uses unbound argument {argument} in call to {call.name}"
                    )

    dispatch_by_id: Dict[int, FunctionCall] = {}
    for index, raw in enumerate(raw_dispatch, start=1):
        parsed = _parse_dispatch(raw, index, format_errors)
        if parsed is None:
            continue
        subtask_id, call = parsed
        if subtask_id in dispatch_by_id:
            dispatch_errors.append(f"Duplicate dispatch for subtask {subtask_id}")
            continue
        dispatch_by_id[subtask_id] = call
        mapping = mappings.get(call.name)
        if mapping is None:
            dispatch_errors.append(f"Subtask {subtask_id} dispatches unknown function {call.name}")
            continue
        if levels.get(call.name, 0) < 2:
            dispatch_errors.append(f"Subtask {subtask_id} top-level call must be H2 or higher")
        if len(call.args) != len(mapping.params):
            binding_errors.append(
                f"Dispatch {call.name} has {len(call.args)} arguments; expected {len(mapping.params)}"
            )
        for argument in call.args:
            if argument not in concrete:
                binding_errors.append(
                    f"Dispatch for subtask {subtask_id} uses non-concrete argument {argument}"
                )

    expected_ids = [subtask.id for subtask in decision.subtasks]
    actual_ids = sorted(dispatch_by_id)
    if actual_ids != expected_ids:
        dispatch_errors.append(
            f"Dispatch must cover DecisionBot subtask ids exactly once; expected {expected_ids}, got {actual_ids}"
        )
    subtasks = [[dispatch_by_id[index]] for index in expected_ids if index in dispatch_by_id]
    expanded_count = 0
    for subtask_id, calls in zip(expected_ids, subtasks):
        expanded, expansion_errors = expand_calls(calls, mappings)
        expanded_count += len(expanded)
        dispatch_errors.extend(
            f"Subtask {subtask_id} expansion: {message}" for message in expansion_errors
        )

    reuse_counts = {name: 0 for name in mappings}
    for mapping in mappings.values():
        for call in mapping.calls:
            if call.name in reuse_counts:
                reuse_counts[call.name] += 1
    for call in dispatch_by_id.values():
        if call.name in reuse_counts:
            reuse_counts[call.name] += 1
    composed = [name for name, level in levels.items() if level >= 2]
    for name in composed:
        if reuse_counts.get(name, 0) < 2 and len(mappings[name].calls) <= 1:
            usefulness_errors.append(
                f"{name} is a one-call wrapper used once; it adds depth without reuse or compression"
            )
    if not composed:
        usefulness_errors.append("No H2-or-higher function was defined")

    counts: Dict[int, int] = {}
    for level in levels.values():
        counts[level] = counts.get(level, 0) + 1
    return HierarchyCompileResult(
        format_valid=not format_errors,
        hierarchy_graph_valid=not graph_errors,
        parameter_binding_valid=not binding_errors,
        dispatch_valid=not dispatch_errors,
        hierarchy_useful=not usefulness_errors,
        mappings=mappings,
        subtasks=subtasks,
        levels=levels,
        max_level=max_level,
        mapping_count_by_level=counts,
        function_reuse_counts=reuse_counts,
        compression_ratio=(expanded_count / len(subtasks)) if subtasks else None,
        format_errors=_unique(format_errors),
        hierarchy_errors=_unique(graph_errors),
        binding_errors=_unique(binding_errors),
        dispatch_errors=_unique(dispatch_errors),
        usefulness_errors=_unique(usefulness_errors),
        payload=payload,
    )


def _parse_function(
    raw: object, index: int, errors: List[str]
) -> Optional[Tuple[FunctionMapping, int]]:
    if not isinstance(raw, dict):
        errors.append(f"Function {index} must be an object")
        return None
    if set(raw) != {"name", "level", "parameters", "body"}:
        errors.append(f"Function {index} must contain name, level, parameters, and body")
        return None
    name, level, parameters, body = (
        raw.get("name"),
        raw.get("level"),
        raw.get("parameters"),
        raw.get("body"),
    )
    if not isinstance(name, str) or not name:
        errors.append(f"Function {index} name must be a non-empty string")
        return None
    if not isinstance(level, int) or isinstance(level, bool) or level < 1:
        errors.append(f"Function {name} level must be a positive integer")
        return None
    if not isinstance(parameters, list) or not all(isinstance(x, str) for x in parameters):
        errors.append(f"Function {name} parameters must be strings")
        return None
    if not isinstance(body, list) or not body:
        errors.append(f"Function {name} body must be a non-empty array")
        return None
    calls: List[FunctionCall] = []
    for call_index, raw_call in enumerate(body, start=1):
        call = _parse_call_object(raw_call, f"Function {name} call {call_index}", errors)
        if call is not None:
            calls.append(call)
    if not calls:
        return None
    return FunctionMapping(name, tuple(parameters), tuple(calls)), level


def _parse_dispatch(
    raw: object, index: int, errors: List[str]
) -> Optional[Tuple[int, FunctionCall]]:
    if not isinstance(raw, dict):
        errors.append(f"Dispatch {index} must be an object")
        return None
    if set(raw) != {"subtask_id", "function", "arguments"}:
        errors.append(f"Dispatch {index} must contain subtask_id, function, and arguments")
        return None
    subtask_id = raw.get("subtask_id")
    if not isinstance(subtask_id, int) or isinstance(subtask_id, bool):
        errors.append(f"Dispatch {index} subtask_id must be an integer")
        return None
    call = _parse_call_object(
        {"function": raw.get("function"), "arguments": raw.get("arguments")},
        f"Dispatch {index}",
        errors,
    )
    return (subtask_id, call) if call is not None else None


def _parse_call_object(
    raw: object, context: str, errors: List[str]
) -> Optional[FunctionCall]:
    if not isinstance(raw, dict) or set(raw) != {"function", "arguments"}:
        errors.append(f"{context} must contain exactly function and arguments")
        return None
    name, arguments = raw.get("function"), raw.get("arguments")
    if not isinstance(name, str) or not name:
        errors.append(f"{context} function must be a non-empty string")
        return None
    if not isinstance(arguments, list) or not all(isinstance(x, str) for x in arguments):
        errors.append(f"{context} arguments must be an array of strings")
        return None
    return FunctionCall(name, tuple(arguments))


def _unique(values: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "DECISION_SCHEMA",
    "HIERARCHY_SCHEMA",
    "DecisionParseResult",
    "DecisionSubtask",
    "HierarchyCompileResult",
    "compile_hierarchy_output",
    "parse_decision_output",
    "parse_json_object",
]
