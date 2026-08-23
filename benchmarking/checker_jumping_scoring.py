from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from checker_jumping_task import CheckerJumpingTask


PRIMITIVE = "MoveChecker"
H1_NAME = "MoveCheckerForward"
CALL_PATTERN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)")
MAPPING_PATTERN = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\))\s*=\s*\[(.*?)\]",
    re.DOTALL,
)


@dataclass(frozen=True)
class FunctionCall:
    name: str
    args: Tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.name}({', '.join(self.args)})"


@dataclass(frozen=True)
class FunctionMapping:
    name: str
    params: Tuple[str, ...]
    calls: Tuple[FunctionCall, ...]


@dataclass
class CheckerJumpingScore:
    task_id: str
    solved: bool
    legal: bool
    optimal: bool
    move_count: int
    optimal_move_count: int
    optimality_gap: Optional[int]
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
    final_state: List[str] = field(default_factory=list)
    high_level_plan: List[str] = field(default_factory=list)
    expanded_h0_plan: List[str] = field(default_factory=list)
    moves: List[List[object]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def clean_arg(value: object) -> str:
    return str(value).strip().strip('"').strip("'").strip("<>")


def parse_call(expression: str) -> Optional[FunctionCall]:
    match = CALL_PATTERN.fullmatch(expression.strip())
    if not match:
        return None
    args = tuple(clean_arg(arg) for arg in match.group(2).split(",") if arg.strip())
    return FunctionCall(match.group(1), args)


def parse_calls(text: str) -> List[FunctionCall]:
    return [
        FunctionCall(
            match.group(1),
            tuple(clean_arg(arg) for arg in match.group(2).split(",") if arg.strip()),
        )
        for match in CALL_PATTERN.finditer(text)
    ]


def parse_direct_plan(text: str) -> Tuple[List[FunctionCall], List[str]]:
    block = _extract_flag(text, "start_all_functions", "end_all_functions")
    calls = parse_calls(block if block is not None else text)
    move_calls = [call for call in calls if call.name == PRIMITIVE]
    if move_calls:
        return move_calls, []

    literal = _extract_moves_literal(text)
    if literal is None:
        return [], ["No MoveChecker calls or moves array found"]
    try:
        raw_moves = ast.literal_eval(literal)
    except (SyntaxError, ValueError) as exc:
        return [], [f"Could not parse moves array: {exc}"]
    if not isinstance(raw_moves, list):
        return [], ["moves must be a list"]

    errors: List[str] = []
    parsed: List[FunctionCall] = []
    for index, raw in enumerate(raw_moves, start=1):
        if not isinstance(raw, (list, tuple)) or len(raw) != 3:
            errors.append(f"Move {index} must be [color, source, target]")
            continue
        parsed.append(FunctionCall(PRIMITIVE, tuple(clean_arg(value) for value in raw)))
    if not parsed and not errors:
        errors.append("moves array is empty")
    return parsed, errors


def parse_mappings(text: str) -> Tuple[Dict[str, FunctionMapping], List[str]]:
    blocks = re.findall(
        r"```start_mapping\s*(.*?)\s*```end_mapping", text, flags=re.DOTALL
    )
    source = "\n".join(blocks)
    if not blocks:
        return {}, ["No start_mapping/end_mapping block found"]
    mappings: Dict[str, FunctionMapping] = {}
    errors: List[str] = []
    for match in MAPPING_PATTERN.finditer(source):
        header = parse_call(match.group(1))
        if header is None:
            errors.append(f"Could not parse mapping header: {match.group(1)}")
            continue
        calls = tuple(parse_calls(match.group(2)))
        if not calls:
            errors.append(f"Mapping for {header.name} has no calls")
            continue
        if header.name in mappings:
            errors.append(f"Duplicate mapping {header.name}")
            continue
        mappings[header.name] = FunctionMapping(header.name, header.args, calls)
    if not mappings:
        errors.append("No valid mappings parsed")
    return mappings, errors


def parse_subtask_plans(text: str) -> Tuple[List[List[FunctionCall]], List[str]]:
    matches = re.findall(
        r"```start_subtask_funcs_(\d+)\s*(.*?)\s*```end_subtask_funcs_\1",
        text,
        flags=re.DOTALL,
    )
    if not matches:
        return [], ["No numbered subtask function blocks found"]
    ids = [int(index) for index, _ in matches]
    errors: List[str] = []
    if ids != list(range(1, len(ids) + 1)):
        errors.append(f"Subtask ids must be consecutive from 1; got {ids}")
    subtasks: List[List[FunctionCall]] = []
    for index, body in matches:
        calls = parse_calls(body)
        if not calls:
            errors.append(f"Subtask {index} contains no calls")
        subtasks.append(calls)
    return subtasks, errors


def validate_h1(mappings: Dict[str, FunctionMapping]) -> Tuple[bool, str]:
    if set(mappings) != {H1_NAME}:
        return False, f"H1 must define exactly {H1_NAME}"
    mapping = mappings[H1_NAME]
    expected_params = ("color", "source_position", "target_position")
    expected_call = FunctionCall(PRIMITIVE, expected_params)
    if mapping.params != expected_params or mapping.calls != (expected_call,):
        return False, (
            f"{H1_NAME} must map (color, source_position, target_position) "
            f"to exactly one matching {PRIMITIVE} call"
        )
    return True, "N/A"


def validate_fixed_h2(
    h2_mappings: Dict[str, FunctionMapping],
    h1_mappings: Dict[str, FunctionMapping],
) -> Tuple[bool, str]:
    if not h2_mappings:
        return False, "At least one H2 mapping is required"
    errors: List[str] = []
    for mapping in h2_mappings.values():
        for call in mapping.calls:
            if call.name not in h1_mappings:
                errors.append(f"{mapping.name} calls {call.name}; H2 may call only exact H1 functions")
            elif len(call.args) != len(h1_mappings[call.name].params):
                errors.append(f"{mapping.name} calls {call.name} with the wrong arity")
    return (not errors, "; ".join(errors) if errors else "N/A")


def expand_calls(
    calls: Sequence[FunctionCall],
    mappings: Dict[str, FunctionMapping],
    max_depth: int = 64,
) -> Tuple[List[FunctionCall], List[str]]:
    expanded: List[FunctionCall] = []
    errors: List[str] = []

    def expand_one(call: FunctionCall, depth: int, active: Tuple[str, ...]) -> None:
        if depth > max_depth:
            errors.append(f"Expansion exceeded maximum depth at {call}")
            return
        if call.name == PRIMITIVE:
            if len(call.args) != 3:
                errors.append(f"{PRIMITIVE} requires exactly three arguments")
            else:
                expanded.append(call)
            return
        mapping = mappings.get(call.name)
        if mapping is None:
            errors.append(f"Unknown function {call.name}")
            return
        if call.name in active:
            errors.append(f"Hierarchy cycle detected at {call.name}")
            return
        if len(call.args) != len(mapping.params):
            errors.append(
                f"{call.name} received {len(call.args)} arguments; expected {len(mapping.params)}"
            )
            return
        bindings = dict(zip(mapping.params, call.args))
        for child in mapping.calls:
            resolved = FunctionCall(
                child.name, tuple(bindings.get(argument, argument) for argument in child.args)
            )
            expand_one(resolved, depth + 1, active + (call.name,))

    for call in calls:
        expand_one(call, 0, ())
    return expanded, _unique(errors)


def infer_levels(
    mappings: Dict[str, FunctionMapping],
) -> Tuple[Dict[str, int], List[str], int]:
    levels: Dict[str, int] = {}
    errors: List[str] = []

    def visit(name: str, active: Tuple[str, ...]) -> int:
        if name in levels:
            return levels[name]
        if name in active:
            errors.append(f"Hierarchy cycle detected at {name}")
            return 0
        mapping = mappings[name]
        child_levels: List[int] = []
        for call in mapping.calls:
            if call.name == PRIMITIVE:
                child_levels.append(0)
            elif call.name in mappings:
                child_levels.append(visit(call.name, active + (name,)))
            else:
                errors.append(f"{name} calls unknown function {call.name}")
        level = 1 + max(child_levels, default=-1)
        levels[name] = level
        return level

    for name in mappings:
        visit(name, ())
    return levels, _unique(errors), max(levels.values(), default=0)


def hierarchy_histogram(
    calls: Sequence[FunctionCall],
    mappings: Dict[str, FunctionMapping],
    levels: Dict[str, int],
) -> Dict[int, int]:
    histogram: Dict[int, int] = {}

    def count(call: FunctionCall, depth: int = 0) -> None:
        if depth > 64 or call.name == PRIMITIVE:
            return
        mapping = mappings.get(call.name)
        if mapping is None:
            return
        level = levels.get(call.name, 0)
        histogram[level] = histogram.get(level, 0) + 1
        if len(call.args) != len(mapping.params):
            return
        bindings = dict(zip(mapping.params, call.args))
        for child in mapping.calls:
            count(
                FunctionCall(
                    child.name,
                    tuple(bindings.get(argument, argument) for argument in child.args),
                ),
                depth + 1,
            )

    for call in calls:
        count(call)
    return histogram


def apply_move(
    board: List[str], call: FunctionCall, move_index: int
) -> Tuple[bool, Optional[str]]:
    prefix = f"Move {move_index}"
    if call.name != PRIMITIVE:
        return False, f"{prefix}: expected {PRIMITIVE}, got {call.name}"
    if len(call.args) != 3:
        return False, f"{prefix}: {PRIMITIVE} requires color, source, and target"
    color, source_text, target_text = call.args
    if color not in {"R", "B"}:
        return False, f"{prefix}: checker color must be R or B, got {color}"
    try:
        source = int(source_text)
        target = int(target_text)
    except ValueError:
        return False, f"{prefix}: source and target positions must be integers"
    if not 0 <= source < len(board):
        return False, f"{prefix}: source position {source} is out of range"
    if not 0 <= target < len(board):
        return False, f"{prefix}: target position {target} is out of range"
    if board[source] != color:
        return False, f"{prefix}: source {source} contains {board[source]}, not {color}"
    if board[target] != "_":
        return False, f"{prefix}: target position {target} is not empty"
    displacement = target - source
    direction = 1 if color == "R" else -1
    if displacement * direction <= 0:
        return False, f"{prefix}: {color} checker cannot move backward"
    distance = abs(displacement)
    if distance not in {1, 2}:
        return False, f"{prefix}: checker must slide one or jump two positions"
    if distance == 2:
        middle = (source + target) // 2
        opposite = "B" if color == "R" else "R"
        if board[middle] != opposite:
            return False, (
                f"{prefix}: {color} jump must cross exactly one {opposite} checker; "
                f"position {middle} contains {board[middle]}"
            )
    board[target] = color
    board[source] = "_"
    return True, None


def simulate_calls(
    task: CheckerJumpingTask,
    calls: Sequence[FunctionCall],
    initial: Optional[Sequence[str]] = None,
) -> Tuple[bool, Optional[str], Optional[int], List[str], List[List[object]]]:
    board = list(initial if initial is not None else task.initial)
    moves: List[List[object]] = []
    for index, call in enumerate(calls, start=1):
        ok, reason = apply_move(board, call, index)
        if not ok:
            return False, reason, index, board, moves
        color, source, target = call.args
        moves.append([color, int(source), int(target)])
    return True, None, None, board, moves


def score_execution(
    task: CheckerJumpingTask,
    final_state: Sequence[str],
    moves: Sequence[Sequence[object]],
    *,
    legal: bool,
    h1_valid: bool = False,
    h2_valid: bool = False,
    h1_count: int = 0,
    h2_count: int = 0,
    h0_count: Optional[int] = None,
    top_level_count: int = 0,
    max_hierarchy_level: int = 0,
    level_call_counts: Optional[Dict[int, int]] = None,
    parse_errors: Optional[Iterable[str]] = None,
    illegal_reason: Optional[str] = None,
    first_failure_move: Optional[int] = None,
    high_level_plan: Optional[Sequence[str]] = None,
    expanded_h0_plan: Optional[Sequence[str]] = None,
) -> CheckerJumpingScore:
    move_list = [list(move) for move in moves]
    solved = legal and list(final_state) == task.goal
    return CheckerJumpingScore(
        task_id=task.id,
        solved=solved,
        legal=legal,
        optimal=solved and len(move_list) == task.optimal_move_count,
        move_count=len(move_list),
        optimal_move_count=task.optimal_move_count,
        optimality_gap=len(move_list) - task.optimal_move_count if solved else None,
        h1_valid=h1_valid,
        h2_valid=h2_valid,
        h1_call_count=h1_count,
        h2_call_count=h2_count,
        h0_call_count=len(move_list) if h0_count is None else h0_count,
        top_level_call_count=top_level_count,
        max_hierarchy_level=max_hierarchy_level,
        level_call_counts={str(k): v for k, v in sorted((level_call_counts or {}).items())},
        parse_errors=_unique(list(parse_errors or [])),
        illegal_reason=illegal_reason,
        first_failure_move=first_failure_move,
        final_state=list(final_state),
        high_level_plan=list(high_level_plan or []),
        expanded_h0_plan=list(expanded_h0_plan or []),
        moves=move_list,
    )


def score_calls(
    task: CheckerJumpingTask,
    calls: Sequence[FunctionCall],
    parse_errors: Optional[Sequence[str]] = None,
) -> CheckerJumpingScore:
    legal, reason, failure, final_state, moves = simulate_calls(task, calls)
    errors = list(parse_errors or [])
    if errors:
        legal = False
        reason = "; ".join(errors)
    return score_execution(
        task,
        final_state,
        moves,
        legal=legal,
        top_level_count=len(calls),
        parse_errors=errors,
        illegal_reason=reason,
        first_failure_move=failure,
        high_level_plan=[str(call) for call in calls],
        expanded_h0_plan=[str(call) for call in calls],
    )


def _extract_flag(text: str, start: str, end: str) -> Optional[str]:
    match = re.search(
        rf"`{{0,3}}{re.escape(start)}\s*(.*?)\s*`{{0,3}}{re.escape(end)}",
        text,
        flags=re.DOTALL,
    )
    return match.group(1).strip() if match else None


def _extract_moves_literal(text: str) -> Optional[str]:
    match = re.search(r"\bmoves\s*=\s*", text, flags=re.IGNORECASE)
    if not match:
        stripped = text.strip()
        return stripped if stripped.startswith("[") else None
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


def _unique(values: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "CheckerJumpingScore",
    "FunctionCall",
    "FunctionMapping",
    "H1_NAME",
    "PRIMITIVE",
    "apply_move",
    "expand_calls",
    "hierarchy_histogram",
    "infer_levels",
    "parse_direct_plan",
    "parse_mappings",
    "parse_subtask_plans",
    "score_calls",
    "score_execution",
    "simulate_calls",
    "validate_fixed_h2",
    "validate_h1",
]
