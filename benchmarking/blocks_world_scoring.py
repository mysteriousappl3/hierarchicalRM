from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from blocks_world_task import BlocksWorldTask
from dynamic_scoring import count_calls_by_level, infer_levels
from scoring import (
    FunctionCall,
    FunctionMapping,
    parse_mappings as _parse_mappings,
    parse_plan as _parse_plan,
    parse_subtask_plans as _parse_subtask_plans,
)


PRIMITIVES = {"MoveBlock"}


@dataclass
class BlocksWorldScore:
    task_id: str
    solved: bool
    legal: bool
    optimal: Optional[bool]
    move_count: int
    optimal_move_count: Optional[int]
    h1_valid: bool = False
    h2_valid: bool = False
    h1_call_count: int = 0
    h2_call_count: int = 0
    h0_call_count: int = 0
    top_level_call_count: int = 0
    max_hierarchy_level: int = 0
    level_call_counts: Dict[str, int] = field(default_factory=dict)
    parse_errors: List[str] = field(default_factory=list)
    illegal_reason: Optional[str] = None
    first_failure_move: Optional[int] = None
    final_state: Dict[str, List[str]] = field(default_factory=dict)
    high_level_plan: List[str] = field(default_factory=list)
    expanded_h0_plan: List[str] = field(default_factory=list)
    moves: List[List[object]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def copy_state(state: Dict[str, List[str]]) -> Dict[str, List[str]]:
    return {stack: list(blocks) for stack, blocks in state.items()}


def parse_direct_plan(text: str) -> Tuple[List[FunctionCall], List[str]]:
    calls, errors = parse_plan(text)
    moves = [call for call in calls if call.name == "MoveBlock"]
    if moves:
        # Direct plans may use the paper's bare call format instead of the
        # hierarchy parser's fenced format. Parsed primitive calls are enough.
        return moves, []

    literal = extract_moves_literal(text)
    if literal:
        try:
            raw_moves = ast.literal_eval(literal)
            parsed = [
                FunctionCall("MoveBlock", [str(item[0]), str(item[1]), str(item[2])])
                for item in raw_moves
                if isinstance(item, (list, tuple)) and len(item) == 3
            ]
            if parsed and len(parsed) == len(raw_moves):
                return parsed, []
        except (SyntaxError, ValueError):
            pass
    return [], errors + ["No valid MoveBlock plan found"]


def normalize_model_fences(text: str) -> str:
    """Accept the plain start_flag form produced by some chat models."""
    flag = re.compile(
        r"(?m)^(?!```)(\s*)((?:start|end)_(?:mapping|all_functions|subtask_funcs_\d+|subtask_\d+|subtask_goalstate_\d+))\s*$"
    )
    return flag.sub(lambda match: f"{match.group(1)}```{match.group(2)}", text)


def parse_mappings(text: str) -> Tuple[Dict[str, FunctionMapping], List[str]]:
    normalized = normalize_model_fences(text)
    mappings, errors = _parse_mappings(normalized)
    if not mappings and "=" in normalized:
        mappings, errors = _parse_mappings(
            "```start_mapping\n" + normalized + "\n```end_mapping"
        )
    return mappings, errors


def parse_plan(text: str) -> Tuple[List[FunctionCall], List[str]]:
    calls, errors = _parse_plan(normalize_model_fences(text))
    if calls:
        errors = [
            error
            for error in errors
            if "No start_all_functions/end_all_functions" not in error
        ]
    return calls, errors


def parse_subtask_plans(text: str) -> Tuple[List[List[FunctionCall]], List[str]]:
    subtasks, errors = _parse_subtask_plans(normalize_model_fences(text))
    if subtasks and any(subtasks):
        errors = [
            error
            for error in errors
            if "No start_all_functions/end_all_functions" not in error
        ]
    return subtasks, errors


def extract_moves_literal(text: str) -> Optional[str]:
    match = re.search(r"moves\s*=\s*", text, flags=re.IGNORECASE)
    if not match:
        return None
    start = text.find("[", match.end())
    if start < 0:
        return None
    depth = 0
    quote: Optional[str] = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def move_tuple(call: FunctionCall) -> Tuple[Optional[Tuple[str, str, str]], Optional[str]]:
    if call.name != "MoveBlock":
        return None, f"Expected MoveBlock, got {call.name}"
    if len(call.args) != 3:
        return None, f"MoveBlock requires 3 arguments, got {len(call.args)}"
    return (call.args[0], str(call.args[1]), str(call.args[2])), None


def apply_move(
    task: BlocksWorldTask,
    state: Dict[str, List[str]],
    move: Tuple[str, str, str],
    move_index: int,
) -> Tuple[bool, Optional[str]]:
    block, source, target = move
    if source not in state:
        return False, f"Move {move_index}: unknown source stack {source}"
    if target not in state:
        return False, f"Move {move_index}: unknown target stack {target}"
    if source == target:
        return False, f"Move {move_index}: source and target are both stack {source}"
    if not state[source]:
        return False, f"Move {move_index}: source stack {source} is empty"
    actual = state[source][-1]
    if actual != block:
        return False, f"Move {move_index}: block {block} is not topmost on stack {source}; {actual} is"
    state[source].pop()
    state[target].append(block)
    return True, None


def simulate_calls(
    task: BlocksWorldTask,
    calls: Sequence[FunctionCall],
    initial_state: Optional[Dict[str, List[str]]] = None,
) -> Tuple[bool, Optional[str], Optional[int], Dict[str, List[str]], List[Tuple[str, str, str]]]:
    state = copy_state(initial_state or task.initial)
    moves: List[Tuple[str, str, str]] = []
    for index, call in enumerate(calls, start=1):
        move, error = move_tuple(call)
        if error or move is None:
            return False, error, index, state, moves
        ok, reason = apply_move(task, state, move, index)
        if not ok:
            return False, reason, index, state, moves
        moves.append(move)
    return True, None, None, state, moves


def expand_calls(
    calls: Sequence[FunctionCall],
    mappings: Dict[str, FunctionMapping],
    max_depth: int = 64,
) -> Tuple[List[FunctionCall], List[str]]:
    expanded: List[FunctionCall] = []
    errors: List[str] = []

    def expand_one(call: FunctionCall, depth: int, path: Tuple[str, ...]) -> None:
        if depth > max_depth:
            errors.append(f"Expansion exceeded max depth at {call}")
            return
        if call.name in PRIMITIVES:
            expanded.append(call)
            return
        if call.name in path:
            errors.append(f"Cycle detected while expanding {call.name}")
            return
        mapping = mappings.get(call.name)
        if mapping is None:
            errors.append(f"Unknown function {call.name}")
            return
        if len(call.args) != len(mapping.params):
            errors.append(
                f"{call.name} expects {len(mapping.params)} arguments, got {len(call.args)}"
            )
            return
        parameter_map = dict(zip(mapping.params, call.args))
        for child in mapping.calls:
            args = [parameter_map.get(argument, argument) for argument in child.args]
            expand_one(FunctionCall(child.name, args), depth + 1, path + (call.name,))

    for top_call in calls:
        expand_one(top_call, 0, ())
    return expanded, errors


def validate_h1(mappings: Dict[str, FunctionMapping]) -> Tuple[bool, str]:
    mapping = mappings.get("MoveTopBlock")
    if mapping is None:
        return False, "H1 must define MoveTopBlock(block, source_stack, target_stack)"
    if len(mapping.params) != 3 or len(mapping.calls) != 1:
        return False, "MoveTopBlock must have three parameters and exactly one body call"
    child = mapping.calls[0]
    if child.name != "MoveBlock" or child.args != mapping.params:
        return False, "MoveTopBlock must map its exact parameters to one MoveBlock call"
    return True, "N/A"


def validate_fixed_h2(
    h2_mappings: Dict[str, FunctionMapping], h1_mappings: Dict[str, FunctionMapping]
) -> Tuple[bool, str]:
    if not h2_mappings:
        return False, "No H2 mappings were generated"
    known_h1 = set(h1_mappings)
    for mapping in h2_mappings.values():
        for child in mapping.calls:
            if child.name not in known_h1:
                return False, f"H2 mapping {mapping.name} calls non-H1 function {child.name}"
    return True, "N/A"


def analyze_dynamic_hierarchy(
    mappings: Dict[str, FunctionMapping],
) -> Tuple[Dict[str, int], List[str], int]:
    levels, errors = infer_levels(mappings, primitives=PRIMITIVES)
    max_level = max(levels.values(), default=0)
    for name, level in levels.items():
        if level > 1:
            for child in mappings[name].calls:
                child_level = 0 if child.name in PRIMITIVES else levels.get(child.name, -1)
                if child_level < 1 or child_level >= level:
                    message = f"{name} at H{level} must call a known lower-level function"
                    if message not in errors:
                        errors.append(message)
    return levels, errors, max_level


def hierarchy_histogram(
    calls: Sequence[FunctionCall],
    mappings: Dict[str, FunctionMapping],
    levels: Dict[str, int],
) -> Dict[int, int]:
    return count_calls_by_level(calls, mappings, levels)


def fixed_call_counts(
    calls: Sequence[FunctionCall],
    h1_mappings: Dict[str, FunctionMapping],
    h2_mappings: Dict[str, FunctionMapping],
) -> Tuple[int, int]:
    h1_count = 0
    h2_count = 0

    def count(call: FunctionCall) -> None:
        nonlocal h1_count, h2_count
        if call.name in h1_mappings:
            h1_count += 1
            return
        mapping = h2_mappings.get(call.name)
        if mapping is None:
            return
        h2_count += 1
        parameter_map = dict(zip(mapping.params, call.args))
        for child in mapping.calls:
            count(FunctionCall(child.name, [parameter_map.get(arg, arg) for arg in child.args]))

    for top_call in calls:
        count(top_call)
    return h1_count, h2_count


def score_execution(
    task: BlocksWorldTask,
    final_state: Dict[str, List[str]],
    moves: Sequence[Tuple[str, str, str]],
    *,
    legal: bool,
    h1_valid: bool = False,
    h2_valid: bool = False,
    h1_count: int = 0,
    h2_count: int = 0,
    top_level_count: int = 0,
    max_hierarchy_level: int = 0,
    level_call_counts: Optional[Dict[int, int]] = None,
    parse_errors: Optional[List[str]] = None,
    illegal_reason: Optional[str] = None,
    first_failure_move: Optional[int] = None,
    high_level_plan: Optional[List[str]] = None,
    expanded_h0_plan: Optional[List[str]] = None,
) -> BlocksWorldScore:
    solved = legal and final_state == task.goal
    optimal = None
    if task.optimal_move_count is not None:
        optimal = solved and len(moves) == task.optimal_move_count
    return BlocksWorldScore(
        task_id=task.id,
        solved=solved,
        legal=legal,
        optimal=optimal,
        move_count=len(moves),
        optimal_move_count=task.optimal_move_count,
        h1_valid=h1_valid,
        h2_valid=h2_valid,
        h1_call_count=h1_count,
        h2_call_count=h2_count,
        h0_call_count=len(moves),
        top_level_call_count=top_level_count,
        max_hierarchy_level=max_hierarchy_level,
        level_call_counts={str(k): v for k, v in sorted((level_call_counts or {}).items())},
        parse_errors=list(parse_errors or []),
        illegal_reason=illegal_reason,
        first_failure_move=first_failure_move,
        final_state=copy_state(final_state),
        high_level_plan=list(high_level_plan or []),
        expanded_h0_plan=list(expanded_h0_plan or []),
        moves=[[block, source, target] for block, source, target in moves],
    )


__all__ = [
    "BlocksWorldScore",
    "FunctionCall",
    "FunctionMapping",
    "analyze_dynamic_hierarchy",
    "apply_move",
    "copy_state",
    "expand_calls",
    "fixed_call_counts",
    "hierarchy_histogram",
    "normalize_model_fences",
    "parse_direct_plan",
    "parse_mappings",
    "parse_plan",
    "parse_subtask_plans",
    "score_execution",
    "simulate_calls",
    "validate_fixed_h2",
    "validate_h1",
]
