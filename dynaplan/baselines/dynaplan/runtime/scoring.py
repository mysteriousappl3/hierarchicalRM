from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from task_loader import HanoiTask


PRIMITIVES = {"MoveCoroutine", "GrabCoroutine", "DropCoroutine"}
CALL_PATTERN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)")
MAPPING_PATTERN = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\))\s*=\s*\[(.*?)\]",
    re.DOTALL,
)


@dataclass
class FunctionCall:
    name: str
    args: List[str]

    def __str__(self) -> str:
        return f"{self.name}({', '.join(self.args)})"


@dataclass
class FunctionMapping:
    name: str
    params: List[str]
    calls: List[FunctionCall]


@dataclass
class ScoreResult:
    task_id: str
    solved: bool
    legal: bool
    optimal: bool
    move_count: int
    optimal_move_count: int
    h1_valid: bool
    h2_valid: bool
    h1_call_count: int = 0
    h2_call_count: int = 0
    h0_call_count: int = 0
    top_level_call_count: int = 0
    parse_errors: List[str] = field(default_factory=list)
    illegal_reason: Optional[str] = None
    final_state: Dict[str, List[str]] = field(default_factory=dict)
    high_level_plan: List[str] = field(default_factory=list)
    expanded_h0_plan: List[str] = field(default_factory=list)
    moves: List[Tuple[str, str]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "task_id": self.task_id,
            "solved": self.solved,
            "legal": self.legal,
            "optimal": self.optimal,
            "move_count": self.move_count,
            "optimal_move_count": self.optimal_move_count,
            "h1_valid": self.h1_valid,
            "h2_valid": self.h2_valid,
            "h1_call_count": self.h1_call_count,
            "h2_call_count": self.h2_call_count,
            "h0_call_count": self.h0_call_count,
            "top_level_call_count": self.top_level_call_count,
            "parse_errors": self.parse_errors,
            "illegal_reason": self.illegal_reason,
            "final_state": self.final_state,
            "high_level_plan": self.high_level_plan,
            "expanded_h0_plan": self.expanded_h0_plan,
            "moves": self.moves,
        }


def extract_between_flags(text: str, start_flag: str, end_flag: str) -> Optional[str]:
    start = re.escape(start_flag).replace("\\`\\`\\`", r"`{0,3}")
    end = re.escape(end_flag).replace("\\`\\`\\`", r"`{0,3}")
    match = re.search(start + r"\s*(.*?)\s*" + end, text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def parse_call(expr: str) -> Optional[FunctionCall]:
    match = CALL_PATTERN.search(expr.strip())
    if not match:
        return None
    args = [clean_arg(arg) for arg in match.group(2).split(",") if arg.strip()]
    return FunctionCall(match.group(1).strip(), args)


def clean_arg(arg: str) -> str:
    value = arg.strip().strip('"').strip("'")
    if "=" in value:
        value = value.split("=", 1)[1].strip().strip('"').strip("'")
    value = value.strip("<>").strip()
    # Remove C# type names if a model includes them in mapping signatures.
    parts = value.split()
    if len(parts) > 1:
        value = parts[-1]
    return value.strip()


def parse_calls(block: str) -> List[FunctionCall]:
    return [
        FunctionCall(match.group(1).strip(), [clean_arg(arg) for arg in match.group(2).split(",") if arg.strip()])
        for match in CALL_PATTERN.finditer(block)
    ]


def parse_mappings(text: str) -> Tuple[Dict[str, FunctionMapping], List[str]]:
    errors: List[str] = []
    mappings: Dict[str, FunctionMapping] = {}
    mapping_blocks = re.findall(
        r"```start_mapping\s*(.*?)\s*```end_mapping",
        text,
        flags=re.DOTALL,
    )
    if not mapping_blocks:
        errors.append("No start_mapping/end_mapping block found")
        return mappings, errors

    combined = "\n".join(mapping_blocks)
    for match in MAPPING_PATTERN.finditer(combined):
        header = parse_call(match.group(1))
        if header is None:
            errors.append(f"Could not parse mapping header: {match.group(1)}")
            continue
        calls = parse_calls(match.group(2))
        if not calls:
            errors.append(f"Mapping for {header.name} has no calls")
            continue
        mappings[header.name] = FunctionMapping(header.name, header.args, calls)

    if not mappings:
        errors.append("No valid mappings parsed")
    return mappings, errors


def parse_plan(decision_output: str) -> Tuple[List[FunctionCall], List[str]]:
    errors: List[str] = []
    subtask_blocks = re.findall(
        r"```start_subtask_funcs_\d+\s*(.*?)\s*```end_subtask_funcs_\d+",
        decision_output,
        flags=re.DOTALL,
    )
    if subtask_blocks:
        block = "\n".join(subtask_blocks)
    else:
        block = extract_between_flags(decision_output, "```start_all_functions", "```end_all_functions")
    if block is None:
        errors.append("No start_all_functions/end_all_functions block found")
        block = decision_output
    calls = parse_calls(block)
    if not calls:
        errors.append("No function calls parsed from plan")
    return calls, errors


def parse_subtask_plans(decision_output: str) -> Tuple[List[List[FunctionCall]], List[str]]:
    errors: List[str] = []
    subtask_blocks = re.findall(
        r"```start_subtask_funcs_\d+\s*(.*?)\s*```end_subtask_funcs_\d+",
        decision_output,
        flags=re.DOTALL,
    )
    if not subtask_blocks:
        plan, plan_errors = parse_plan(decision_output)
        return ([plan] if plan else []), plan_errors

    subtasks: List[List[FunctionCall]] = []
    for idx, block in enumerate(subtask_blocks, start=1):
        calls = parse_calls(block)
        if not calls:
            errors.append(f"Subtask {idx}: no function calls parsed")
        subtasks.append(calls)
    return subtasks, errors


def expand_calls(
    calls: List[FunctionCall],
    mappings: Dict[str, FunctionMapping],
    max_depth: int = 20,
) -> Tuple[List[FunctionCall], List[str]]:
    errors: List[str] = []
    expanded: List[FunctionCall] = []

    def expand_one(call: FunctionCall, depth: int) -> None:
        if depth > max_depth:
            errors.append(f"Expansion exceeded max depth at {call}")
            return
        if call.name in PRIMITIVES:
            expanded.append(call)
            return
        mapping = mappings.get(call.name)
        if mapping is None:
            errors.append(f"Unknown non-primitive function: {call.name}")
            return
        param_map = {
            param: call.args[idx]
            for idx, param in enumerate(mapping.params)
            if idx < len(call.args)
        }
        for child in mapping.calls:
            resolved_args = [param_map.get(arg, arg) for arg in child.args]
            expand_one(FunctionCall(child.name, resolved_args), depth + 1)

    for call in calls:
        expand_one(call, 0)
    return expanded, errors


def apply_hanoi_move(
    task: HanoiTask,
    stacks: Dict[str, List[str]],
    source: str,
    target: str,
    move_index: int,
) -> Tuple[bool, Optional[str]]:
    sizes = task.ring_sizes
    if source not in stacks:
        return False, f"Move {move_index}: unknown source peg {source}"
    if target not in stacks:
        return False, f"Move {move_index}: unknown target peg {target}"
    if not stacks[source]:
        return False, f"Move {move_index}: source peg {source} is empty"

    ring = stacks[source][-1]
    if stacks[target]:
        target_top = stacks[target][-1]
        if sizes[ring] > sizes[target_top]:
            return False, f"Move {move_index}: cannot place {ring} on smaller {target_top}"

    stacks[source].pop()
    stacks[target].append(ring)
    return True, None


def extract_moves_from_h0(h0_calls: List[FunctionCall]) -> Tuple[List[Tuple[str, str]], List[str]]:
    errors: List[str] = []
    moves: List[Tuple[str, str]] = []
    idx = 0
    while idx < len(h0_calls):
        window = h0_calls[idx:idx + 4]
        if len(window) < 4:
            errors.append(f"Incomplete H0 move at call {idx}: {[str(call) for call in window]}")
            break
        expected = ["MoveCoroutine", "GrabCoroutine", "MoveCoroutine", "DropCoroutine"]
        observed = [call.name for call in window]
        if observed != expected:
            errors.append(f"Invalid H0 pattern at call {idx}: expected {expected}, got {observed}")
            idx += 1
            continue
        if not window[0].args or not window[2].args:
            errors.append(f"MoveCoroutine missing peg argument at call {idx}")
            idx += 4
            continue
        moves.append((window[0].args[0], window[2].args[0]))
        idx += 4
    return moves, errors


def simulate_hanoi(task: HanoiTask, moves: List[Tuple[str, str]]) -> Tuple[bool, Optional[str], Dict[str, List[str]]]:
    stacks = {peg: list(stack) for peg, stack in task.initial.items()}
    sizes = task.ring_sizes
    for move_index, (source, target) in enumerate(moves, start=1):
        if source not in stacks:
            return False, f"Move {move_index}: unknown source peg {source}", stacks
        if target not in stacks:
            return False, f"Move {move_index}: unknown target peg {target}", stacks
        if not stacks[source]:
            return False, f"Move {move_index}: source peg {source} is empty", stacks

        ring = stacks[source].pop()
        if stacks[target]:
            target_top = stacks[target][-1]
            if sizes[ring] > sizes[target_top]:
                return (
                    False,
                    f"Move {move_index}: cannot place {ring} on smaller {target_top}",
                    stacks,
                )
        stacks[target].append(ring)

    return True, None, stacks


def score_outputs(
    task: HanoiTask,
    h1_output: str,
    h2_output: str,
    decision_output: str,
) -> ScoreResult:
    parse_errors: List[str] = []
    h1_mappings, h1_errors = parse_mappings(h1_output)
    h2_mappings, h2_errors = parse_mappings(h2_output)
    parse_errors.extend(f"H1: {err}" for err in h1_errors)
    parse_errors.extend(f"H2: {err}" for err in h2_errors)

    mappings = {**h1_mappings, **h2_mappings}
    plan, plan_errors = parse_plan(decision_output)
    parse_errors.extend(f"Plan: {err}" for err in plan_errors)
    expanded, expand_errors = expand_calls(plan, mappings)
    parse_errors.extend(f"Expand: {err}" for err in expand_errors)
    moves, move_errors = extract_moves_from_h0(expanded)
    parse_errors.extend(f"H0: {err}" for err in move_errors)
    h1_call_count, h2_call_count = count_hierarchy_calls(plan, h1_mappings, h2_mappings)

    legal, illegal_reason, final_state = simulate_hanoi(task, moves)
    solved = legal and final_state == task.goal
    optimal = solved and len(moves) == task.optimal_move_count

    return ScoreResult(
        task_id=task.id,
        solved=solved,
        legal=legal,
        optimal=optimal,
        move_count=len(moves),
        optimal_move_count=task.optimal_move_count,
        h1_valid=has_valid_h1_move_mapping(h1_mappings),
        h2_valid=all_h2_calls_known(h2_mappings, h1_mappings),
        h1_call_count=h1_call_count,
        h2_call_count=h2_call_count,
        h0_call_count=len(expanded),
        top_level_call_count=len(plan),
        parse_errors=parse_errors,
        illegal_reason=illegal_reason,
        final_state=final_state,
        high_level_plan=[str(call) for call in plan],
        expanded_h0_plan=[str(call) for call in expanded],
        moves=moves,
    )


def score_direct_output(task: HanoiTask, direct_output: str) -> ScoreResult:
    parse_errors: List[str] = []
    plan, plan_errors = parse_plan(direct_output)
    parse_errors.extend(f"Plan: {err}" for err in plan_errors)

    moves = direct_moves_from_calls(plan)
    expanded_h0: List[FunctionCall] = []
    if not moves:
        expanded_h0 = [call for call in plan if call.name in PRIMITIVES]
        moves, h0_errors = extract_moves_from_h0(expanded_h0)
        parse_errors.extend(f"H0: {err}" for err in h0_errors)

    if not moves:
        parse_errors.append("Direct plan did not contain MoveHoop-style calls or valid H0 primitive groups")

    legal, illegal_reason, final_state = simulate_hanoi(task, moves)
    solved = legal and final_state == task.goal
    optimal = solved and len(moves) == task.optimal_move_count

    return ScoreResult(
        task_id=task.id,
        solved=solved,
        legal=legal,
        optimal=optimal,
        move_count=len(moves),
        optimal_move_count=task.optimal_move_count,
        h1_valid=False,
        h2_valid=False,
        h1_call_count=0,
        h2_call_count=0,
        h0_call_count=len(expanded_h0),
        top_level_call_count=len(plan),
        parse_errors=parse_errors,
        illegal_reason=illegal_reason,
        final_state=final_state,
        high_level_plan=[str(call) for call in plan],
        expanded_h0_plan=[str(call) for call in expanded_h0],
        moves=moves,
    )


def score_from_execution(
    task: HanoiTask,
    final_state: Dict[str, List[str]],
    moves: List[Tuple[str, str]],
    high_level_plan: List[str],
    expanded_h0_plan: List[str],
    h1_valid: bool,
    h2_valid: bool,
    h1_call_count: int,
    h2_call_count: int,
    h0_call_count: int,
    top_level_call_count: int,
    parse_errors: List[str],
    illegal_reason: Optional[str],
) -> ScoreResult:
    solved = illegal_reason is None and final_state == task.goal
    legal = illegal_reason is None
    optimal = solved and len(moves) == task.optimal_move_count
    return ScoreResult(
        task_id=task.id,
        solved=solved,
        legal=legal,
        optimal=optimal,
        move_count=len(moves),
        optimal_move_count=task.optimal_move_count,
        h1_valid=h1_valid,
        h2_valid=h2_valid,
        h1_call_count=h1_call_count,
        h2_call_count=h2_call_count,
        h0_call_count=h0_call_count,
        top_level_call_count=top_level_call_count,
        parse_errors=parse_errors,
        illegal_reason=illegal_reason,
        final_state=final_state,
        high_level_plan=high_level_plan,
        expanded_h0_plan=expanded_h0_plan,
        moves=moves,
    )


def count_hierarchy_calls(
    calls: List[FunctionCall],
    h1_mappings: Dict[str, FunctionMapping],
    h2_mappings: Dict[str, FunctionMapping],
    max_depth: int = 20,
) -> Tuple[int, int]:
    h1_count = 0
    h2_count = 0

    def count_one(call: FunctionCall, depth: int) -> None:
        nonlocal h1_count, h2_count
        if depth > max_depth:
            return
        if call.name in h1_mappings:
            h1_count += 1
            return
        mapping = h2_mappings.get(call.name)
        if mapping is None:
            return
        h2_count += 1
        param_map = {
            param: call.args[idx]
            for idx, param in enumerate(mapping.params)
            if idx < len(call.args)
        }
        for child in mapping.calls:
            resolved_args = [param_map.get(arg, arg) for arg in child.args]
            count_one(FunctionCall(child.name, resolved_args), depth + 1)

    for call in calls:
        count_one(call, 0)
    return h1_count, h2_count


def direct_moves_from_calls(calls: List[FunctionCall]) -> List[Tuple[str, str]]:
    move_names = {
        "MoveHoop",
        "MoveRing",
        "MoveRingCoroutine",
        "TransferHoop",
        "TransferRing",
    }
    moves: List[Tuple[str, str]] = []
    for call in calls:
        if call.name not in move_names or len(call.args) < 2:
            continue
        moves.append((call.args[0], call.args[1]))
    return moves


def has_valid_h1_move_mapping(mappings: Dict[str, FunctionMapping]) -> bool:
    for mapping in mappings.values():
        names = [call.name for call in mapping.calls]
        if names == ["MoveCoroutine", "GrabCoroutine", "MoveCoroutine", "DropCoroutine"]:
            return True
    return False


def all_h2_calls_known(
    h2_mappings: Dict[str, FunctionMapping],
    h1_mappings: Dict[str, FunctionMapping],
) -> bool:
    if not h2_mappings:
        return False
    known = set(h1_mappings)
    for mapping in h2_mappings.values():
        for call in mapping.calls:
            if call.name not in known:
                return False
    return True
