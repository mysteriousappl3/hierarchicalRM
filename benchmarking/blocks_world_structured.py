from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from blocks_world_scoring import (
    FunctionCall,
    FunctionMapping,
    PRIMITIVES,
    analyze_dynamic_hierarchy,
    expand_calls,
    validate_h1,
)
from blocks_world_task import BlocksWorldTask


STATE_SCHEMA: Dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "0": {"type": "array", "items": {"type": "string"}},
        "1": {"type": "array", "items": {"type": "string"}},
        "2": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["0", "1", "2"],
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
                    "goal_state": STATE_SCHEMA,
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
    goal_state: Dict[str, List[str]]


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
        return (
            self.format_valid
            and self.hierarchy_graph_valid
            and self.parameter_binding_valid
            and self.dispatch_valid
            and self.hierarchy_useful
        )


def parse_decision_output(text: str, task: BlocksWorldTask) -> DecisionParseResult:
    payload, error = parse_json_object(text)
    if error or payload is None:
        return DecisionParseResult(
            False, False, format_errors=[error or "No JSON object found"]
        )

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
        unknown = set(raw) - {"id", "objective", "goal_state"}
        if unknown:
            format_errors.append(f"Subtask {position} has unknown fields: {sorted(unknown)}")
        missing = {"id", "objective", "goal_state"} - set(raw)
        if missing:
            format_errors.append(f"Subtask {position} is missing fields: {sorted(missing)}")
        subtask_id = raw.get("id")
        objective = raw.get("objective")
        state = raw.get("goal_state")
        if not isinstance(subtask_id, int) or isinstance(subtask_id, bool):
            format_errors.append(f"Subtask {position} id must be an integer")
            continue
        if not isinstance(objective, str):
            format_errors.append(f"Subtask {subtask_id} objective must be a string")
        elif not objective.strip():
            semantic_errors.append(f"Subtask {subtask_id} objective must not be empty")
        normalized_state, state_format_errors, state_semantic_errors = validate_complete_state(
            state, task, f"Subtask {subtask_id} goal_state"
        )
        format_errors.extend(state_format_errors)
        semantic_errors.extend(state_semantic_errors)
        if isinstance(objective, str) and normalized_state is not None:
            subtasks.append(DecisionSubtask(subtask_id, objective.strip(), normalized_state))

    ids = [subtask.id for subtask in subtasks]
    if ids != list(range(1, len(raw_subtasks) + 1)):
        semantic_errors.append(
            f"Subtask ids must be exactly 1..{len(raw_subtasks)} in order; got {ids}"
        )
    if subtasks and subtasks[-1].goal_state != task.goal:
        semantic_errors.append(
            "The final DecisionBot subtask goal must exactly equal the task goal"
        )
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
    task: BlocksWorldTask,
    decision: DecisionParseResult,
) -> HierarchyCompileResult:
    payload, parse_error = parse_json_object(text)
    if parse_error or payload is None:
        return HierarchyCompileResult(
            format_valid=False,
            hierarchy_graph_valid=False,
            parameter_binding_valid=False,
            dispatch_valid=False,
            hierarchy_useful=False,
            format_errors=[parse_error or "No JSON object found"],
        )

    format_errors: List[str] = []
    hierarchy_errors: List[str] = []
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
        mapping, declared_level = parsed
        if mapping.name in mappings:
            hierarchy_errors.append(f"Duplicate function name {mapping.name}")
            continue
        mappings[mapping.name] = mapping
        declared_levels[mapping.name] = declared_level

    levels, graph_errors, max_level = analyze_dynamic_hierarchy(mappings)
    hierarchy_errors.extend(graph_errors)
    h1_valid, h1_reason = validate_h1(mappings)
    if not h1_valid:
        hierarchy_errors.append(h1_reason)
    for name, level in levels.items():
        if declared_levels.get(name) != level:
            hierarchy_errors.append(
                f"{name} declares H{declared_levels.get(name)} but its call graph infers H{level}"
            )
        if level == 1 and name != "MoveTopBlock":
            hierarchy_errors.append(f"Unexpected H1 function {name}; H1 is exactly MoveTopBlock")
    if max_level < 2:
        hierarchy_errors.append("Complete framework requires at least H1 and H2")

    concrete_literals = set(task.stack_ids)
    concrete_literals.update(block for stack in task.initial.values() for block in stack)
    for mapping in mappings.values():
        if len(set(mapping.params)) != len(mapping.params):
            binding_errors.append(f"{mapping.name} has duplicate parameter names")
        allowed = set(mapping.params) | concrete_literals
        for call in mapping.calls:
            target = mappings.get(call.name)
            expected_arity = 3 if call.name in PRIMITIVES else (
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
            dispatch_errors.append(
                f"Subtask {subtask_id} top-level call {call.name} must be H2 or higher"
            )
        if len(call.args) != len(mapping.params):
            binding_errors.append(
                f"Dispatch {call.name} has {len(call.args)} arguments; expected {len(mapping.params)}"
            )
        for argument in call.args:
            if argument not in concrete_literals:
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
    for subtask_id in expected_ids:
        call = dispatch_by_id.get(subtask_id)
        if call is None:
            continue
        _, expansion_errors = expand_calls([call], mappings)
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

    composed_names = [name for name, level in levels.items() if level >= 2]
    useful_names = [
        name
        for name in composed_names
        if reuse_counts.get(name, 0) >= 2 or len(mappings[name].calls) > 1
    ]
    for name in composed_names:
        if name not in useful_names:
            usefulness_errors.append(
                f"{name} is a one-call wrapper used once; it adds depth without reuse or compression"
            )
    if not composed_names:
        usefulness_errors.append("No H2-or-higher function was defined")

    mapping_counts: Dict[int, int] = {}
    for level in levels.values():
        mapping_counts[level] = mapping_counts.get(level, 0) + 1
    top_level_count = len(dispatch_by_id)
    expanded_count = 0
    if not dispatch_errors:
        for calls in subtasks:
            expanded, _ = expand_calls(calls, mappings)
            expanded_count += len(expanded)
    compression_ratio = (
        round(expanded_count / top_level_count, 6) if top_level_count else None
    )

    return HierarchyCompileResult(
        format_valid=not format_errors,
        hierarchy_graph_valid=not hierarchy_errors,
        parameter_binding_valid=not binding_errors,
        dispatch_valid=not dispatch_errors,
        hierarchy_useful=not usefulness_errors,
        mappings=mappings,
        subtasks=subtasks,
        levels=levels,
        max_level=max_level,
        mapping_count_by_level=mapping_counts,
        function_reuse_counts=reuse_counts,
        compression_ratio=compression_ratio,
        format_errors=_unique(format_errors),
        hierarchy_errors=_unique(hierarchy_errors),
        binding_errors=_unique(binding_errors),
        dispatch_errors=_unique(dispatch_errors),
        usefulness_errors=_unique(usefulness_errors),
        payload=payload,
    )


def validate_complete_state(
    value: object, task: BlocksWorldTask, label: str
) -> Tuple[Optional[Dict[str, List[str]]], List[str], List[str]]:
    format_errors: List[str] = []
    semantic_errors: List[str] = []
    if not isinstance(value, dict):
        return None, [f"{label} must be an object"], []
    if set(value) != set(task.stack_ids):
        format_errors.append(f"{label} must contain exactly stacks {list(task.stack_ids)}")
    state: Dict[str, List[str]] = {}
    for stack in task.stack_ids:
        blocks = value.get(stack)
        if not isinstance(blocks, list) or any(not isinstance(block, str) for block in blocks):
            format_errors.append(f"{label}.{stack} must be an array of block names")
            continue
        state[stack] = list(blocks)
    expected_blocks = sorted(block for stack in task.initial.values() for block in stack)
    actual_blocks = sorted(block for blocks in state.values() for block in blocks)
    if actual_blocks != expected_blocks:
        semantic_errors.append(f"{label} must contain every task block exactly once")
    valid_state = state if not format_errors and not semantic_errors else None
    return valid_state, format_errors, semantic_errors


def parse_json_object(text: str) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
    start = candidate.find("{")
    if start < 0:
        return None, "Output does not contain a JSON object"
    if candidate[:start].strip():
        return None, "Output contains text before the JSON object"
    try:
        payload, end = json.JSONDecoder().raw_decode(candidate[start:])
    except json.JSONDecodeError as exc:
        return None, f"Output is not valid JSON: {exc.msg} at character {exc.pos}"
    trailing = candidate[start + end :].strip()
    if trailing:
        return None, "Output contains text after the JSON object"
    if not isinstance(payload, dict):
        return None, "Top-level JSON value must be an object"
    return payload, None


def _parse_function(
    raw: object, index: int, errors: List[str]
) -> Optional[Tuple[FunctionMapping, int]]:
    if not isinstance(raw, dict):
        errors.append(f"Function {index} must be an object")
        return None
    if set(raw) != {"name", "level", "parameters", "body"}:
        errors.append(
            f"Function {index} must contain exactly name, level, parameters, and body"
        )
    name = raw.get("name")
    level = raw.get("level")
    params = raw.get("parameters")
    body = raw.get("body")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        errors.append(f"Function {index} has an invalid name")
        return None
    if not isinstance(level, int) or isinstance(level, bool) or level < 1:
        errors.append(f"Function {name} level must be a positive integer")
        return None
    if not isinstance(params, list) or any(not isinstance(value, str) for value in params):
        errors.append(f"Function {name} parameters must be an array of strings")
        return None
    if not isinstance(body, list) or not body:
        errors.append(f"Function {name} body must be a non-empty array")
        return None
    calls: List[FunctionCall] = []
    for call_index, call in enumerate(body, start=1):
        parsed = _parse_call(call, f"Function {name} body call {call_index}", errors)
        if parsed is not None:
            calls.append(parsed)
    if len(calls) != len(body):
        return None
    return FunctionMapping(name, list(params), calls), level


def _parse_dispatch(
    raw: object, index: int, errors: List[str]
) -> Optional[Tuple[int, FunctionCall]]:
    if not isinstance(raw, dict):
        errors.append(f"Dispatch {index} must be an object")
        return None
    if set(raw) != {"subtask_id", "function", "arguments"}:
        errors.append(
            f"Dispatch {index} must contain exactly subtask_id, function, and arguments"
        )
    subtask_id = raw.get("subtask_id")
    if not isinstance(subtask_id, int) or isinstance(subtask_id, bool) or subtask_id < 1:
        errors.append(f"Dispatch {index} subtask_id must be a positive integer")
        return None
    call = _parse_call(raw, f"Dispatch {index}", errors, allowed={"subtask_id", "function", "arguments"})
    return (subtask_id, call) if call is not None else None


def _parse_call(
    raw: object,
    label: str,
    errors: List[str],
    allowed: Optional[set[str]] = None,
) -> Optional[FunctionCall]:
    if not isinstance(raw, dict):
        errors.append(f"{label} must be an object")
        return None
    expected = allowed or {"function", "arguments"}
    if set(raw) != expected:
        errors.append(f"{label} has missing or unknown fields")
    name = raw.get("function")
    args = raw.get("arguments")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        errors.append(f"{label} has an invalid function name")
        return None
    if not isinstance(args, list) or any(not isinstance(value, str) for value in args):
        errors.append(f"{label} arguments must be an array of strings")
        return None
    return FunctionCall(name, list(args))


def _unique(values: Sequence[str]) -> List[str]:
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
