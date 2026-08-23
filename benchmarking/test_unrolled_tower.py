"""Phase 0 feasibility check for n-level hierarchies.

This does not call a model. It hand-writes the hierarchy a model would have to
emit for an n-level solution, in the exact text format the existing prompts ask
for, and runs it through the unmodified parsing, expansion, validation, and
simulation path used by hanoi_benchmark.py.

The question being answered: can the current machinery already expand an
arbitrarily deep hierarchy, and does the depth limit in expand_calls leave
enough headroom for hanoi_12?

Run the tests:
    python benchmarking/test_unrolled_tower.py

Run the report:
    python benchmarking/test_unrolled_tower.py --report
"""

from __future__ import annotations

import sys
import unittest
from typing import Dict, List, Tuple

from hanoi_benchmark import validate_symbolic_plan
from scoring import (
    all_h2_calls_known,
    count_hierarchy_calls,
    expand_calls,
    extract_moves_from_h0,
    has_valid_h1_move_mapping,
    parse_mappings,
    parse_subtask_plans,
    simulate_hanoi,
    PRIMITIVES,
)
from task_loader import available_tasks, load_task


# The single H1 function the H1 prompt pins down, in the mapping format that
# build_h1_prompt asks for. This is what h1_output carries in a real run.
H1_MAPPING_TEXT = """```start_mapping
MoveSingleRing(source_peg, target_peg) = [MoveCoroutine(source_peg), GrabCoroutine(), MoveCoroutine(target_peg), DropCoroutine()]
```end_mapping"""


def build_tower_mapping_text(max_level: int) -> str:
    """Unrolled tower hierarchy: MoveTowerK is defined in terms of MoveTower(K-1).

    This is the composition the current H2 prompt forbids ("Do not call other H2
    functions from H2") and that an n-level planner would be free to emit.
    """
    lines = ["MoveTower1(src, aux, dst) = [MoveSingleRing(src, dst)]"]
    for level in range(2, max_level + 1):
        below = level - 1
        lines.append(
            f"MoveTower{level}(src, aux, dst) = ["
            f"MoveTower{below}(src, dst, aux), "
            f"MoveSingleRing(src, dst), "
            f"MoveTower{below}(aux, src, dst)]"
        )
    return "```start_mapping\n" + ",\n".join(lines) + "\n```end_mapping"


def build_plan_text(task, level: int) -> str:
    """The whole task as one top-level call, in the DecisionBot subtask format."""
    return (
        "```start_subtask_funcs_1\n"
        f"MoveTower{level}({task.source_peg}, {task.auxiliary_peg}, {task.target_peg})\n"
        "```end_subtask_funcs_1"
    )


def build_flat_mapping_text(moves: List[Tuple[str, str]]) -> str:
    """The flat two-level equivalent: every move enumerated in one mapping body.

    This approximates what the current pipeline must emit as h2_output, and is
    used only to compare emission size against the nested form.
    """
    calls = ", ".join(f"MoveSingleRing({source}, {target})" for source, target in moves)
    return "```start_mapping\nSolveHanoi(src, aux, dst) = [" + calls + "]\n```end_mapping"


def reference_infer_levels(mappings) -> Tuple[Dict[str, int], List[str]]:
    """Specification for the level-generic validity check Phase 1 will implement.

    level(primitive) = 0, level(f) = 1 + max(level of callees). Unresolvable
    callees and cycles are reported as errors rather than silently accepted.
    """
    levels: Dict[str, int] = {}
    errors: List[str] = []
    visiting: set = set()

    def level_of(name: str) -> int:
        if name in PRIMITIVES:
            return 0
        if name in levels:
            return levels[name]
        if name in visiting:
            errors.append(f"cycle detected at {name}")
            return 0
        mapping = mappings.get(name)
        if mapping is None:
            errors.append(f"unresolvable callee: {name}")
            return 0
        visiting.add(name)
        level = 1 + max((level_of(call.name) for call in mapping.calls), default=-1)
        visiting.discard(name)
        levels[name] = level
        return level

    for name in mappings:
        level_of(name)
    return levels, errors


def run_case(task_id: str) -> Dict[str, object]:
    """Parse, validate, expand, and simulate one unrolled-tower solution."""
    task = load_task(task_id)
    level = len(task.rings)

    hierarchy_text = build_tower_mapping_text(level)
    h1_mappings, h1_errors = parse_mappings(H1_MAPPING_TEXT)
    tower_mappings, tower_errors = parse_mappings(hierarchy_text)
    mappings = {**h1_mappings, **tower_mappings}

    subtasks, plan_errors = parse_subtask_plans(build_plan_text(task, level))

    # The same deterministic gate hanoi_benchmark.py applies before it will
    # execute anything.
    plan_valid, plan_reason, validated = validate_symbolic_plan(
        task=task,
        current_state={peg: list(stack) for peg, stack in task.initial.items()},
        subtasks=subtasks,
        mappings=mappings,
        h1_mappings=h1_mappings,
        h2_mappings=tower_mappings,
    )

    top_level_calls = subtasks[0] if subtasks else []
    h0_calls, expand_errors = expand_calls(top_level_calls, mappings)
    moves, move_errors = extract_moves_from_h0(h0_calls)
    legal, illegal_reason, final_state = simulate_hanoi(task, moves)
    h1_count, h2_count = count_hierarchy_calls(top_level_calls, h1_mappings, tower_mappings)

    flat_text = build_flat_mapping_text(moves) if moves else ""

    return {
        "task_id": task.id,
        "level": level,
        "mapping_count": len(mappings),
        "parse_errors": h1_errors + tower_errors + plan_errors,
        "expand_errors": expand_errors,
        "move_errors": move_errors,
        "plan_valid": plan_valid,
        "plan_reason": plan_reason,
        "validated_subtask_count": len(validated),
        "h1_valid": has_valid_h1_move_mapping(h1_mappings),
        "h2_valid": all_h2_calls_known(tower_mappings, h1_mappings),
        "top_level_call_count": len(top_level_calls),
        "h1_call_count": h1_count,
        "h2_call_count": h2_count,
        "h0_call_count": len(h0_calls),
        "move_count": len(moves),
        "optimal_move_count": task.optimal_move_count,
        "legal": legal,
        "illegal_reason": illegal_reason,
        "solved": legal and final_state == task.goal,
        "optimal": legal and final_state == task.goal and len(moves) == task.optimal_move_count,
        # Depth of the deepest expand_calls recursion: the MoveTowerK chain is
        # `level` nodes, then MoveSingleRing, then the H0 primitives.
        "required_expansion_depth": level + 1,
        "nested_chars": len(hierarchy_text),
        "flat_chars": len(flat_text),
    }


class UnrolledTowerTest(unittest.TestCase):
    def test_every_task_solves_optimally(self) -> None:
        for task_id in available_tasks():
            with self.subTest(task=task_id):
                result = run_case(task_id)
                self.assertEqual(result["parse_errors"], [])
                self.assertEqual(result["expand_errors"], [])
                self.assertEqual(result["move_errors"], [])
                self.assertTrue(result["plan_valid"], result["plan_reason"])
                self.assertTrue(result["solved"])
                self.assertTrue(result["optimal"])

    def test_hanoi_12_collapses_to_one_top_level_call(self) -> None:
        result = run_case("hanoi_12")
        self.assertEqual(result["top_level_call_count"], 1)
        self.assertEqual(result["move_count"], 4095)
        self.assertEqual(result["h0_call_count"], 4095 * 4)
        self.assertEqual(result["mapping_count"], 13)  # MoveSingleRing + MoveTower1..12

    def test_two_level_validity_check_rejects_deep_nesting(self) -> None:
        """Documents the exact gap Phase 1 has to close.

        Expansion and simulation both succeed on a nested hierarchy, but
        all_h2_calls_known only accepts callees that appear in h1_mappings, so
        MoveTower2 -> MoveTower1 is rejected. In run_hierarchy_loop that appends
        "H2: no valid H2 mapping composed only of H1 calls" to attempt_errors,
        which forces a replan. So the current pipeline would reject an n-level
        hierarchy even if a model emitted a correct one.
        """
        result = run_case("hanoi_12")
        self.assertTrue(result["h1_valid"])
        self.assertTrue(result["solved"])
        self.assertFalse(result["h2_valid"])

    def test_generalized_validity_check_accepts_deep_nesting(self) -> None:
        """Reference implementation of the Phase 1 replacement.

        A callee is valid if it is a primitive or any known mapping, and the
        call graph must be acyclic. That is the whole fix.
        """
        h1_mappings, _ = parse_mappings(H1_MAPPING_TEXT)
        tower_mappings, _ = parse_mappings(build_tower_mapping_text(12))
        mappings = {**h1_mappings, **tower_mappings}

        levels, errors = reference_infer_levels(mappings)
        self.assertEqual(errors, [])
        self.assertEqual(levels["MoveSingleRing"], 1)
        self.assertEqual(levels["MoveTower1"], 2)
        self.assertEqual(levels["MoveTower12"], 13)

    def test_generalized_validity_check_detects_cycles(self) -> None:
        text = """```start_mapping
LoopA(x, y) = [LoopB(x, y)],
LoopB(x, y) = [LoopA(x, y)]
```end_mapping"""
        mappings, _ = parse_mappings(text)
        _, errors = reference_infer_levels(mappings)
        self.assertTrue(any("cycle" in err for err in errors))

    def test_expansion_depth_limit_is_the_binding_constraint(self) -> None:
        """max_depth in expand_calls caps how deep a hierarchy may go."""
        task = load_task("hanoi_5")
        h1_mappings, _ = parse_mappings(H1_MAPPING_TEXT)
        tower_mappings, _ = parse_mappings(build_tower_mapping_text(5))
        mappings = {**h1_mappings, **tower_mappings}
        calls, _ = parse_subtask_plans(build_plan_text(task, 5))

        # hanoi_5 needs depth 6: MoveTower5..1 (5), MoveSingleRing (1), then H0.
        _, too_shallow = expand_calls(calls[0], mappings, max_depth=5)
        self.assertTrue(too_shallow)
        _, just_enough = expand_calls(calls[0], mappings, max_depth=6)
        self.assertEqual(just_enough, [])

    def test_nested_form_is_far_smaller_than_flat_form(self) -> None:
        result = run_case("hanoi_12")
        self.assertLess(result["nested_chars"] * 50, result["flat_chars"])


def run_report() -> int:
    rows = [run_case(task_id) for task_id in available_tasks()]

    print("")
    print("Unrolled n-level tower through the existing parser and expander")
    print("")
    header = (
        f"{'task':<9} {'lvl':>3} {'maps':>4} {'top':>4} {'h1':>6} {'h2':>6} "
        f"{'h0':>7} {'moves':>6} {'opt':>6} {'depth':>5} {'solved':>6} {'optimal':>7}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['task_id']:<9} {row['level']:>3} {row['mapping_count']:>4} "
            f"{row['top_level_call_count']:>4} {row['h1_call_count']:>6} {row['h2_call_count']:>6} "
            f"{row['h0_call_count']:>7} {row['move_count']:>6} {row['optimal_move_count']:>6} "
            f"{row['required_expansion_depth']:>5} {str(row['solved']):>6} {str(row['optimal']):>7}"
        )

    print("")
    print("Emission size the model must produce for the hierarchy definitions")
    print("")
    header = f"{'task':<9} {'nested chars':>13} {'flat chars':>11} {'ratio':>7} {'flat ~tokens':>13}"
    print(header)
    print("-" * len(header))
    for row in rows:
        ratio = row["flat_chars"] / row["nested_chars"] if row["nested_chars"] else 0.0
        print(
            f"{row['task_id']:<9} {row['nested_chars']:>13} {row['flat_chars']:>11} "
            f"{ratio:>6.1f}x {row['flat_chars'] // 4:>13}"
        )

    failures = [row for row in rows if not row["optimal"]]
    print("")
    print(f"Max expansion depth needed: {max(row['required_expansion_depth'] for row in rows)}")
    print("Default expand_calls max_depth: 20 (supports towers up to 19 levels)")
    print(f"Tasks solved optimally: {len(rows) - len(failures)}/{len(rows)}")
    for row in failures:
        print(f"  FAILED {row['task_id']}: {row['plan_reason']} {row['expand_errors']}")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--report" in sys.argv:
        sys.argv.remove("--report")
        raise SystemExit(run_report())
    unittest.main()
