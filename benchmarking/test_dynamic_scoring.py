"""Tests for dynamic_scoring, including replay against committed baseline runs.

Run:
    python benchmarking/test_dynamic_scoring.py
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import List

from dynamic_scoring import (
    DEFAULT_MAX_DEPTH,
    analyze_hierarchy,
    count_calls_by_level,
    expand_hierarchy,
    hierarchy_metrics,
    infer_levels,
    legacy_call_counts,
    legacy_validity,
)
from scoring import (
    FunctionCall,
    FunctionMapping,
    all_h2_calls_known,
    count_hierarchy_calls,
    extract_moves_from_h0,
    has_valid_h1_move_mapping,
    parse_mappings,
    parse_plan,
    parse_subtask_plans,
    simulate_hanoi,
)
from task_loader import load_task
from test_unrolled_tower import (
    H1_MAPPING_TEXT,
    build_plan_text,
    build_tower_mapping_text,
)


RESULTS_DIR = Path(__file__).resolve().parent / "results"


def tower_mappings(level: int):
    h1_mappings, _ = parse_mappings(H1_MAPPING_TEXT)
    composed, _ = parse_mappings(build_tower_mapping_text(level))
    return h1_mappings, composed, {**h1_mappings, **composed}


class InferLevelsTest(unittest.TestCase):
    def test_unrolled_tower_levels(self) -> None:
        _, _, mappings = tower_mappings(12)
        levels, errors = infer_levels(mappings)
        self.assertEqual(errors, [])
        self.assertEqual(levels["MoveSingleRing"], 1)
        self.assertEqual(levels["MoveTower1"], 2)
        self.assertEqual(levels["MoveTower6"], 7)
        self.assertEqual(levels["MoveTower12"], 13)

    def test_flat_two_level_hierarchy_matches_h1_h2_naming(self) -> None:
        text = """```start_mapping
Shuffle(a, b, c) = [MoveSingleRing(a, b), MoveSingleRing(b, c)]
```end_mapping"""
        h1_mappings, _ = parse_mappings(H1_MAPPING_TEXT)
        composed, _ = parse_mappings(text)
        levels, errors = infer_levels({**h1_mappings, **composed})
        self.assertEqual(errors, [])
        self.assertEqual(levels["MoveSingleRing"], 1)
        self.assertEqual(levels["Shuffle"], 2)

    def test_cycle_is_reported(self) -> None:
        text = """```start_mapping
LoopA(x, y) = [LoopB(x, y)],
LoopB(x, y) = [LoopA(x, y)]
```end_mapping"""
        mappings, _ = parse_mappings(text)
        _, errors = infer_levels(mappings)
        self.assertTrue(any("cycle" in err for err in errors), errors)

    def test_self_recursion_is_reported(self) -> None:
        text = """```start_mapping
MoveTower(src, aux, dst) = [MoveTower(src, dst, aux), MoveSingleRing(src, dst)]
```end_mapping"""
        mappings, _ = parse_mappings(text)
        _, errors = infer_levels(mappings)
        self.assertTrue(any("cycle" in err for err in errors), errors)

    def test_unresolvable_callee_is_reported(self) -> None:
        text = """```start_mapping
Compose(a, b) = [NotDefinedAnywhere(a, b)]
```end_mapping"""
        mappings, _ = parse_mappings(text)
        _, errors = infer_levels(mappings)
        self.assertTrue(any("unresolvable callee" in err for err in errors), errors)

    def test_empty_body_is_reported(self) -> None:
        # parse_mappings rejects empty bodies, so build the mapping directly.
        mappings = {"Empty": FunctionMapping("Empty", ["a"], [])}
        _, errors = infer_levels(mappings)
        self.assertTrue(any("empty body" in err for err in errors), errors)

    def test_errors_are_deduplicated_and_deterministic(self) -> None:
        text = """```start_mapping
A(x) = [Missing(x)],
B(x) = [Missing(x)]
```end_mapping"""
        mappings, _ = parse_mappings(text)
        _, first = infer_levels(mappings)
        _, second = infer_levels(mappings)
        self.assertEqual(first, second)
        self.assertEqual(len([e for e in first if "Missing" in e]), 1)


class AnalyzeHierarchyTest(unittest.TestCase):
    def test_deep_nesting_is_valid(self) -> None:
        _, _, mappings = tower_mappings(12)
        analysis = analyze_hierarchy(mappings)
        self.assertTrue(analysis.valid)
        self.assertEqual(analysis.max_level, 13)
        self.assertTrue(analysis.base_pattern_valid)
        # One MoveSingleRing at level 1, one MoveTowerK at each level 2..13.
        self.assertEqual(analysis.mapping_count_by_level[1], 1)
        self.assertEqual(analysis.mapping_count_by_level[13], 1)

    def test_this_is_what_the_old_check_rejected(self) -> None:
        h1_mappings, composed, mappings = tower_mappings(12)
        self.assertFalse(all_h2_calls_known(composed, h1_mappings))
        self.assertTrue(analyze_hierarchy(mappings).valid)

    def test_cycles_make_the_hierarchy_invalid(self) -> None:
        text = """```start_mapping
LoopA(x, y) = [LoopB(x, y)],
LoopB(x, y) = [LoopA(x, y)]
```end_mapping"""
        mappings, _ = parse_mappings(text)
        self.assertFalse(analyze_hierarchy(mappings).valid)


class CountCallsByLevelTest(unittest.TestCase):
    def test_hanoi_12_histogram(self) -> None:
        task = load_task("hanoi_12")
        _, _, mappings = tower_mappings(12)
        levels, _ = infer_levels(mappings)
        subtasks, _ = parse_subtask_plans(build_plan_text(task, 12))

        histogram = count_calls_by_level(subtasks[0], mappings, levels)
        # One MoveTower12, two MoveTower11, ... 2048 MoveTower1, 4095 base calls.
        self.assertEqual(histogram[13], 1)
        self.assertEqual(histogram[12], 2)
        self.assertEqual(histogram[2], 2048)
        self.assertEqual(histogram[1], 4095)

        base, composed = legacy_call_counts(histogram)
        self.assertEqual(base, 4095)
        self.assertEqual(composed, 4095)

    def test_matches_count_hierarchy_calls_on_two_level_input(self) -> None:
        text = """```start_mapping
MoveTwo(a, b, c) = [MoveSingleRing(a, b), MoveSingleRing(b, c)],
MoveThree(a, b, c) = [MoveSingleRing(a, b), MoveSingleRing(b, c), MoveSingleRing(a, c)]
```end_mapping"""
        plan_text = """```start_all_functions
MoveTwo(peg_a, peg_b, peg_c)
MoveThree(peg_a, peg_b, peg_c)
MoveSingleRing(peg_a, peg_c)
```end_all_functions"""
        h1_mappings, _ = parse_mappings(H1_MAPPING_TEXT)
        composed, _ = parse_mappings(text)
        mappings = {**h1_mappings, **composed}
        calls, _ = parse_plan(plan_text)

        old_h1, old_h2 = count_hierarchy_calls(calls, h1_mappings, composed)
        levels, _ = infer_levels(mappings)
        new_h1, new_h2 = legacy_call_counts(count_calls_by_level(calls, mappings, levels))
        self.assertEqual((new_h1, new_h2), (old_h1, old_h2))


class ExpansionDepthTest(unittest.TestCase):
    def test_raised_default_depth_expands_deep_towers(self) -> None:
        task = load_task("hanoi_12")
        _, _, mappings = tower_mappings(12)
        subtasks, _ = parse_subtask_plans(build_plan_text(task, 12))

        h0_calls, errors = expand_hierarchy(subtasks[0], mappings)
        self.assertEqual(errors, [])
        moves, move_errors = extract_moves_from_h0(h0_calls)
        self.assertEqual(move_errors, [])
        legal, illegal_reason, final_state = simulate_hanoi(task, moves)
        self.assertTrue(legal, illegal_reason)
        self.assertEqual(final_state, task.goal)
        self.assertEqual(len(moves), task.optimal_move_count)

    def test_default_depth_is_higher_than_scoring_default(self) -> None:
        self.assertGreater(DEFAULT_MAX_DEPTH, 20)


class MetricsPayloadTest(unittest.TestCase):
    def test_legacy_fields_and_superset_are_both_present(self) -> None:
        task = load_task("hanoi_5")
        _, _, mappings = tower_mappings(5)
        levels, _ = infer_levels(mappings)
        subtasks, _ = parse_subtask_plans(build_plan_text(task, 5))
        analysis = analyze_hierarchy(mappings)
        histogram = count_calls_by_level(subtasks[0], mappings, levels)

        payload = hierarchy_metrics(analysis, histogram)
        self.assertTrue(payload["h1_valid"])
        self.assertTrue(payload["h2_valid"])
        self.assertEqual(payload["h1_call_count"], 31)
        self.assertEqual(payload["max_hierarchy_level"], 6)
        self.assertEqual(payload["level_call_counts"]["1"], 31)
        self.assertEqual(payload["hierarchy_errors"], [])
        # Must survive a JSON round trip to land in metrics.json.
        self.assertEqual(json.loads(json.dumps(payload)), payload)


def baseline_hierarchy_runs() -> List[Path]:
    if not RESULTS_DIR.exists():
        return []
    return sorted(RESULTS_DIR.glob("*/hierarchy/*/steps.json"))


class BaselineReplayTest(unittest.TestCase):
    """Replay committed hierarchy runs through the new functions.

    Counting is a pure generalization, so it must agree exactly. Validity is
    intentionally more permissive: the new check accepts hierarchies deeper
    than two levels, which the old one rejected. So validity is asserted as an
    implication rather than an equality.
    """

    def test_replay_against_committed_runs(self) -> None:
        runs = baseline_hierarchy_runs()
        if not runs:
            self.skipTest("no baseline results on disk (results/ is gitignored)")

        checked = 0
        for steps_path in runs:
            with self.subTest(run=steps_path.parent.name):
                steps = json.loads(steps_path.read_text(encoding="utf-8"))
                h1_output = steps.get("h1_output")
                h2_output = steps.get("h2_output")
                decision_output = steps.get("decision_output")
                if not (h1_output and h2_output and decision_output):
                    continue

                h1_mappings, _ = parse_mappings(h1_output)
                h2_mappings, _ = parse_mappings(h2_output)
                if not h1_mappings or not h2_mappings:
                    continue
                mappings = {**h1_mappings, **h2_mappings}
                calls, _ = parse_plan(decision_output)

                old_h1, old_h2 = count_hierarchy_calls(calls, h1_mappings, h2_mappings)
                levels, _ = infer_levels(mappings)
                histogram = count_calls_by_level(calls, mappings, levels)
                new_h1, new_h2 = legacy_call_counts(histogram)
                self.assertEqual(
                    (new_h1, new_h2),
                    (old_h1, old_h2),
                    f"call-count drift in {steps_path.parent.name}",
                )

                analysis = analyze_hierarchy(mappings)
                new_h1_valid, new_h2_valid = legacy_validity(analysis)
                if has_valid_h1_move_mapping(h1_mappings):
                    self.assertTrue(new_h1_valid, f"h1_valid regressed in {steps_path.parent.name}")
                if all_h2_calls_known(h2_mappings, h1_mappings):
                    self.assertTrue(new_h2_valid, f"h2_valid regressed in {steps_path.parent.name}")
                checked += 1

        self.assertGreater(checked, 0, "found run folders but none carried usable outputs")
        print(f"\nreplayed {checked} committed hierarchy run(s) with no call-count drift")


if __name__ == "__main__":
    unittest.main()
