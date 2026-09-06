"""Tests for the flat-to-flat Tower of Hanoi addition.

Covers the verification steps from the flat-to-flat plan:
1. BFS correctness against the known 2^n - 1 tower-to-tower closed form.
3. Flat task validity (every generated instance passes validate_task and BFS
   finds a finite optimum).
4. Mock end-to-end across all four modes, zero API spend.
5. No tower leakage in any flat prompt builder's rendered text.

Existing tower-to-tower tests (test_unrolled_tower.py, test_dynamic_scoring.py,
test_dynamic_prompts.py) are untouched by this work and are not duplicated
here; run them directly to confirm the tower-to-tower pipeline is unaffected.

Run:
    python benchmarking/test_flat_hanoi.py
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List

import flat_dynamic_prompts as fdp
import flat_prompts as fp
from flat_hanoi_task_loader import FlatHanoiTask, validate_task
from hanoi_solver import shortest_hanoi_move_count, shortest_hanoi_path
from scoring import simulate_hanoi
from task_loader import Ring, available_tasks as available_tower_tasks, load_task as load_tower_task


def make_flat_task(
    initial: Dict[str, List[str]],
    goal: Dict[str, List[str]],
    rings: List[Ring],
    optimal_move_count=None,
) -> FlatHanoiTask:
    return FlatHanoiTask(
        id="hanoi_flat_test",
        name="test",
        pegs=["peg_a", "peg_b", "peg_c"],
        rings=rings,
        initial=initial,
        goal=goal,
        instruction="Rearrange the rings so the scene matches the goal configuration.",
        optimal_move_count=optimal_move_count,
    )


THREE_RINGS = [Ring("ring_1", 1, "small"), Ring("ring_2", 2, "mid"), Ring("ring_3", 3, "large")]


class BFSCorrectnessTest(unittest.TestCase):
    """Verification step 1: BFS must reproduce 2^n - 1 on every tower task."""

    def test_matches_closed_form_on_every_tower_task(self) -> None:
        for task_id in available_tower_tasks():
            with self.subTest(task=task_id):
                task = load_tower_task(task_id)
                n = len(task.rings)
                expected = 2 ** n - 1
                got = shortest_hanoi_move_count(
                    task.initial, task.goal, task.ring_sizes, max_ring_count=12
                )
                self.assertEqual(got, expected)

    def test_zero_moves_when_already_at_goal(self) -> None:
        state = {"peg_a": ["ring_3", "ring_1"], "peg_b": ["ring_2"], "peg_c": []}
        sizes = {"ring_1": 1, "ring_2": 2, "ring_3": 3}
        self.assertEqual(shortest_hanoi_move_count(state, state, sizes), 0)

    def test_none_above_max_ring_count(self) -> None:
        sizes = {f"ring_{i}": i for i in range(1, 12)}
        initial = {"peg_a": [f"ring_{i}" for i in range(11, 0, -1)], "peg_b": [], "peg_c": []}
        goal = {"peg_a": [], "peg_b": [], "peg_c": [f"ring_{i}" for i in range(11, 0, -1)]}
        self.assertIsNone(
            shortest_hanoi_move_count(initial, goal, sizes, max_ring_count=5)
        )

    def test_path_is_legal_and_reaches_goal(self) -> None:
        initial = {"peg_a": ["ring_3", "ring_1"], "peg_b": ["ring_2"], "peg_c": []}
        goal = {"peg_a": [], "peg_b": ["ring_3", "ring_2"], "peg_c": ["ring_1"]}
        sizes = {"ring_1": 1, "ring_2": 2, "ring_3": 3}
        path = shortest_hanoi_path(initial, goal, sizes)
        self.assertIsNotNone(path)

        task = make_flat_task(initial, goal, THREE_RINGS)
        legal, reason, final_state = simulate_hanoi(task, path)
        self.assertTrue(legal, reason)
        self.assertEqual(final_state, goal)
        self.assertEqual(len(path), shortest_hanoi_move_count(initial, goal, sizes))


class FlatTaskValidityTest(unittest.TestCase):
    """Verification step 3: generated instances validate and BFS-solve."""

    def test_well_formed_flat_task_validates(self) -> None:
        initial = {"peg_a": ["ring_3", "ring_1"], "peg_b": ["ring_2"], "peg_c": []}
        goal = {"peg_a": [], "peg_b": ["ring_3", "ring_2"], "peg_c": ["ring_1"]}
        task = make_flat_task(initial, goal, THREE_RINGS, optimal_move_count=6)
        validate_task(task)  # must not raise

    def test_larger_on_smaller_is_rejected(self) -> None:
        initial = {"peg_a": ["ring_1", "ring_3"], "peg_b": ["ring_2"], "peg_c": []}
        goal = {"peg_a": [], "peg_b": ["ring_3", "ring_2"], "peg_c": ["ring_1"]}
        task = make_flat_task(initial, goal, THREE_RINGS)
        with self.assertRaises(ValueError):
            validate_task(task)

    def test_missing_ring_is_rejected(self) -> None:
        initial = {"peg_a": ["ring_3"], "peg_b": ["ring_2"], "peg_c": []}  # ring_1 missing
        goal = {"peg_a": [], "peg_b": ["ring_3", "ring_2"], "peg_c": ["ring_1"]}
        task = make_flat_task(initial, goal, THREE_RINGS)
        with self.assertRaises(ValueError):
            validate_task(task)

    def test_generated_grid_all_solve(self) -> None:
        """Generates a small grid via the real generator and BFS-solves every instance."""
        from generate_flat_hanoi_tasks import generate_instance
        import random

        for n in (3, 4, 5):
            for instance_index in range(3):
                rng = random.Random(f"test-seed:{n}:{instance_index}")
                initial, goal, optimal = generate_instance(rng, n, min_optimal_moves=n)
                sizes = {f"ring_{i}": i for i in range(1, n + 1)}
                with self.subTest(n=n, instance=instance_index):
                    got = shortest_hanoi_move_count(initial, goal, sizes)
                    self.assertEqual(got, optimal)
                    self.assertIsNotNone(got)
                    self.assertGreaterEqual(got, n)


class MockEndToEndTest(unittest.TestCase):
    """Verification step 4: all four modes solve a flat task via --provider mock."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp_dir = Path(tempfile.mkdtemp(prefix="flat_hanoi_test_"))
        cls.initial = {"peg_a": ["ring_3", "ring_1"], "peg_b": ["ring_2"], "peg_c": []}
        cls.goal = {"peg_a": [], "peg_b": ["ring_3", "ring_2"], "peg_c": ["ring_1"]}
        cls.task = make_flat_task(cls.initial, cls.goal, THREE_RINGS, optimal_move_count=6)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def _mock_client(self):
        from models import MockHanoiClient

        return MockHanoiClient("mock-hanoi")

    def test_hierarchy_mode_solves_via_run_task(self) -> None:
        import flat_hanoi_benchmark as fhb

        original_load_task = fhb.load_task
        fhb.load_task = lambda task_id: self.task
        try:
            row = fhb.run_task(
                self.task.id,
                self._mock_client(),
                fixed_goal=False,
                max_tokens=8192,
                use_framework=True,
                use_inner_outer=False,
                max_replans=15,
                reasoning_effort=None,
            )
        finally:
            fhb.load_task = original_load_task

        self.assertTrue(row["score"]["solved"])
        self.assertTrue(row["score"]["legal"])
        self.assertEqual(row["score"]["parse_errors"], [])

    def test_not_hierarchy_mode_solves_via_run_task(self) -> None:
        import flat_hanoi_benchmark as fhb

        original_load_task = fhb.load_task
        fhb.load_task = lambda task_id: self.task
        try:
            row = fhb.run_task(
                self.task.id,
                self._mock_client(),
                fixed_goal=False,
                max_tokens=8192,
                use_framework=False,
                use_inner_outer=False,
                max_replans=15,
                reasoning_effort=None,
            )
        finally:
            fhb.load_task = original_load_task

        self.assertTrue(row["score"]["solved"])
        self.assertTrue(row["score"]["legal"])

    def test_inner_outer_mode_solves_via_run_task(self) -> None:
        import flat_hanoi_benchmark as fhb

        original_load_task = fhb.load_task
        fhb.load_task = lambda task_id: self.task
        try:
            row = fhb.run_task(
                self.task.id,
                self._mock_client(),
                fixed_goal=False,
                max_tokens=8192,
                use_framework=False,
                use_inner_outer=True,
                max_replans=15,
                reasoning_effort=None,
            )
        finally:
            fhb.load_task = original_load_task

        self.assertTrue(row["score"]["solved"])
        self.assertTrue(row["score"]["legal"])

    def test_dynamic_hierarchy_mode_solves_via_run_task(self) -> None:
        import flat_dynamic_hierarchy_benchmark as fdhb

        original_load_task = fdhb.load_task
        fdhb.load_task = lambda task_id: self.task
        try:
            row = fdhb.run_task(
                self.task.id,
                self._mock_client(),
                fixed_goal=False,
                max_tokens=8192,
                max_replans=15,
                reasoning_effort=None,
                reuse_h1=False,
                include_code_block=True,
            )
        finally:
            fdhb.load_task = original_load_task

        self.assertTrue(row["score"]["solved"])
        self.assertTrue(row["score"]["legal"])
        self.assertEqual(row["score"]["parse_errors"], [])


class NoTowerLeakageTest(unittest.TestCase):
    """Verification step 5: no source_peg/auxiliary_peg/target_peg JSON keys
    or "using X as the auxiliary peg"-style narration in any flat prompt.

    The generic action-signature parameter names MoveSingleRing(source_peg,
    target_peg) / MoveHoop(source_peg, target_peg) are not tower leakage --
    they are the primitive's own argument names and appear identically in the
    tower-to-tower prompts. The real signal is the JSON field emitted by
    task_spec_for_prompt, and narrative phrases naming a specific tower
    endpoint peg.
    """

    BANNED_JSON_KEYS = ['"source_peg"', '"auxiliary_peg"', '"target_peg"']
    BANNED_NARRATION = [
        "auxiliary peg",
        "using peg_",
        "Move all rings from peg_",
        "Move every ring from peg_",
    ]

    @classmethod
    def setUpClass(cls) -> None:
        cls.task = make_flat_task(
            {"peg_a": ["ring_3", "ring_1"], "peg_b": ["ring_2"], "peg_c": []},
            {"peg_a": [], "peg_b": ["ring_3", "ring_2"], "peg_c": ["ring_1"]},
            THREE_RINGS,
            optimal_move_count=6,
        )
        cls.scene_json = fp.build_scene_description(cls.task)
        cls.goal_desc = fp.build_goal_description(cls.task)

    def assert_clean(self, name: str, text: str) -> None:
        hits = [b for b in self.BANNED_JSON_KEYS + self.BANNED_NARRATION if b in text]
        self.assertEqual(hits, [], f"{name} leaked tower framing: {hits}")

    def test_all_flat_prompts_builder(self) -> None:
        task = self.task
        scene_json = self.scene_json
        goal_desc = self.goal_desc
        state_output = "dummy state output"
        h1_output = "dummy h1"
        h2_output = "dummy h2"
        plan_output = "dummy plan"

        self.assert_clean("build_state_prompt", fp.build_state_prompt(task, scene_json))
        self.assert_clean("build_h1_prompt", fp.build_h1_prompt(scene_json))
        self.assert_clean("build_h2_prompt", fp.build_h2_prompt(scene_json, h1_output))
        self.assert_clean(
            "build_decision_prompt",
            fp.build_decision_prompt(task, scene_json, state_output, h1_output, h2_output),
        )
        self.assert_clean(
            "build_innerbot_state_prompt",
            fp.build_innerbot_state_prompt(task, scene_json, state_output),
        )
        self.assert_clean(
            "build_innerbot_plan_prompt",
            fp.build_innerbot_plan_prompt(
                task, scene_json, state_output, h1_output, h2_output, "dummy decision"
            ),
        )
        self.assert_clean(
            "build_innerbot_direct_plan_prompt",
            fp.build_innerbot_direct_plan_prompt(task, scene_json, task.initial, "dummy direct"),
        )
        self.assert_clean(
            "build_outerbot_prompt",
            fp.build_outerbot_prompt(
                task,
                goal_desc["constraint_spatial_relations"],
                "dummy subtask",
                scene_json,
                scene_json,
                goal_desc,
                goal_desc,
            ),
        )
        self.assert_clean("build_direct_hanoi_prompt", fp.build_direct_hanoi_prompt(task))

    def test_all_flat_dynamic_prompts_builders(self) -> None:
        task = self.task
        scene_json = self.scene_json
        state_output = "dummy state output"
        h1_output = "dummy h1"
        plan_output = "dummy plan"

        self.assert_clean(
            "flat_dynamic.build_plan_prompt",
            fdp.build_plan_prompt(task, scene_json, state_output, h1_output),
        )
        self.assert_clean(
            "flat_dynamic.build_hierarchy_planner_prompt",
            fdp.build_hierarchy_planner_prompt(task, scene_json, state_output, h1_output, plan_output),
        )
        self.assert_clean(
            "flat_dynamic.build_router_prompt",
            fdp.build_router_prompt(task, scene_json, state_output, plan_output, "dummy hierarchy"),
        )

    def test_task_spec_for_prompt_has_no_tower_keys(self) -> None:
        spec = fp.task_spec_for_prompt(self.task)
        self.assert_clean("task_spec_for_prompt", spec)


if __name__ == "__main__":
    unittest.main()
