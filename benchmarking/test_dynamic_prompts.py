"""Tests for the dynamic pipeline prompts and their parsers.

The important test here is the round trip: a response written in exactly the
format build_hierarchy_planner_prompt asks for must parse, infer levels, and
validate through to a legal simulated solution using only existing parsers.

Run:
    python benchmarking/test_dynamic_prompts.py
"""

from __future__ import annotations

import unittest

from dynamic_prompts import (
    build_hierarchy_planner_prompt,
    build_plan_prompt,
    build_router_prompt,
)
from dynamic_scoring import (
    OWNER_BOTH,
    OWNER_DECISION,
    OWNER_HIERARCHY,
    analyze_hierarchy,
    count_calls_by_level,
    expand_hierarchy,
    infer_levels,
    normalize_owner,
    parse_plan_subtasks,
    parse_router_verdict,
)
from prompts import build_scene_description, as_json, build_goal_description
from scoring import extract_moves_from_h0, parse_mappings, parse_subtask_plans, simulate_hanoi
from task_loader import load_task
from test_unrolled_tower import H1_MAPPING_TEXT


PLAN_RESPONSE = """```start_subtask_1
Move the two smallest rings from peg_a to peg_b so that ring_3 becomes free.
```end_subtask_1
```start_subtask_goalstate_1
{"peg_a": ["ring_3"], "peg_b": ["ring_2", "ring_1"], "peg_c": []}
```end_subtask_goalstate_1
```start_subtask_2
Move ring_3 from peg_a to peg_c and rebuild the tower on peg_c.
```end_subtask_2
```start_subtask_goalstate_2
{"peg_a": [], "peg_b": [], "peg_c": ["ring_3", "ring_2", "ring_1"]}
```end_subtask_goalstate_2"""

# A hierarchy-planner response in the documented format, nested three deep.
HIERARCHY_RESPONSE = """```start_mapping
MoveTower1(src, aux, dst) = [MoveSingleRing(src, dst)],
MoveTower2(src, aux, dst) = [MoveTower1(src, dst, aux), MoveSingleRing(src, dst), MoveTower1(aux, src, dst)],
MoveTower3(src, aux, dst) = [MoveTower2(src, dst, aux), MoveSingleRing(src, dst), MoveTower2(aux, src, dst)]
```end_mapping

```start_subtask_funcs_1
MoveTower2(peg_a, peg_c, peg_b)
```end_subtask_funcs_1
```start_subtask_funcs_2
MoveSingleRing(peg_a, peg_c)
MoveTower2(peg_b, peg_a, peg_c)
```end_subtask_funcs_2"""


def task_inputs(task_id: str = "hanoi_3"):
    task = load_task(task_id)
    scene_json = build_scene_description(task)
    state_output = as_json(build_goal_description(task))
    return task, scene_json, state_output


class PlanPromptTest(unittest.TestCase):
    def test_asks_for_subtasks_and_goal_states(self) -> None:
        task, scene_json, state_output = task_inputs()
        prompt = build_plan_prompt(task, scene_json, state_output, H1_MAPPING_TEXT)
        self.assertIn("start_subtask_{num}", prompt)
        self.assertIn("start_subtask_goalstate_{num}", prompt)

    def test_never_asks_for_function_calls(self) -> None:
        """The structural guarantee: with no H2 shown and no call format
        requested, the planner cannot emit an action sequence."""
        task, scene_json, state_output = task_inputs()
        prompt = build_plan_prompt(task, scene_json, state_output, H1_MAPPING_TEXT)
        self.assertNotIn("start_subtask_funcs", prompt)
        self.assertNotIn("start_all_functions", prompt)
        self.assertIn("Do NOT output any function calls", prompt)

    def test_h1_is_framed_as_a_boundary_not_a_building_block(self) -> None:
        task, scene_json, state_output = task_inputs()
        prompt = build_plan_prompt(task, scene_json, state_output, H1_MAPPING_TEXT)
        self.assertIn("validity boundary", prompt)
        self.assertIn(H1_MAPPING_TEXT, prompt)

    def test_feedback_is_carried(self) -> None:
        task, scene_json, state_output = task_inputs()
        prompt = build_plan_prompt(
            task, scene_json, state_output, H1_MAPPING_TEXT, feedback="subtask 2 skipped ring_3"
        )
        self.assertIn("subtask 2 skipped ring_3", prompt)


class HierarchyPlannerPromptTest(unittest.TestCase):
    def test_requests_both_output_blocks(self) -> None:
        task, scene_json, state_output = task_inputs()
        prompt = build_hierarchy_planner_prompt(
            task, scene_json, state_output, H1_MAPPING_TEXT, PLAN_RESPONSE
        )
        self.assertIn("start_mapping", prompt)
        self.assertIn("start_subtask_funcs_{num}", prompt)

    def test_shows_a_nested_example_without_giving_away_hanoi(self) -> None:
        task, scene_json, state_output = task_inputs()
        prompt = build_hierarchy_planner_prompt(
            task, scene_json, state_output, H1_MAPPING_TEXT, PLAN_RESPONSE
        )
        self.assertIn("Level3Action", prompt)
        self.assertNotIn("MoveTower", prompt)

    def test_forbids_recursion_with_a_reason(self) -> None:
        task, scene_json, state_output = task_inputs()
        prompt = build_hierarchy_planner_prompt(
            task, scene_json, state_output, H1_MAPPING_TEXT, PLAN_RESPONSE
        )
        self.assertIn("must never call itself", prompt)
        self.assertIn("no base case", prompt)

    def test_states_the_plan_may_be_wrong(self) -> None:
        task, scene_json, state_output = task_inputs()
        prompt = build_hierarchy_planner_prompt(
            task, scene_json, state_output, H1_MAPPING_TEXT, PLAN_RESPONSE
        )
        self.assertIn("The plan may be wrong", prompt)

    def test_code_block_requirement_can_be_switched_off(self) -> None:
        task, scene_json, state_output = task_inputs()
        with_code = build_hierarchy_planner_prompt(
            task, scene_json, state_output, H1_MAPPING_TEXT, PLAN_RESPONSE, include_code_block=True
        )
        without_code = build_hierarchy_planner_prompt(
            task, scene_json, state_output, H1_MAPPING_TEXT, PLAN_RESPONSE, include_code_block=False
        )
        self.assertIn("start_flag", with_code)
        self.assertNotIn("start_flag", without_code)

    def test_previous_hierarchies_are_optional(self) -> None:
        task, scene_json, state_output = task_inputs()
        without = build_hierarchy_planner_prompt(
            task, scene_json, state_output, H1_MAPPING_TEXT, PLAN_RESPONSE
        )
        self.assertNotIn("validated in an earlier round", without)
        with_prior = build_hierarchy_planner_prompt(
            task, scene_json, state_output, H1_MAPPING_TEXT, PLAN_RESPONSE,
            previous_hierarchies="MoveTower2(src, aux, dst) = [...]",
        )
        self.assertIn("validated in an earlier round", with_prior)


class RouterPromptTest(unittest.TestCase):
    def test_requests_all_three_fields(self) -> None:
        task, scene_json, state_output = task_inputs()
        prompt = build_router_prompt(
            task, scene_json, state_output, PLAN_RESPONSE, HIERARCHY_RESPONSE
        )
        self.assertIn("RESULT:", prompt)
        self.assertIn("OWNER:", prompt)
        self.assertIn("REASON:", prompt)
        self.assertIn("start_result", prompt)

    def test_carries_both_entry_points(self) -> None:
        task, scene_json, state_output = task_inputs()
        prompt = build_router_prompt(
            task,
            scene_json,
            state_output,
            PLAN_RESPONSE,
            HIERARCHY_RESPONSE,
            symbolic_reason="Move 4: cannot place ring_3 on smaller ring_1",
            execution_feedback="OuterBot reported RECOVERABLE after subtask 1",
        )
        self.assertIn("cannot place ring_3 on smaller ring_1", prompt)
        self.assertIn("RECOVERABLE after subtask 1", prompt)

    def test_states_what_is_already_machine_verified(self) -> None:
        """Without this the router reports false positives on valid hierarchies."""
        task, scene_json, state_output = task_inputs()
        prompt = build_router_prompt(
            task, scene_json, state_output, PLAN_RESPONSE, HIERARCHY_RESPONSE
        )
        self.assertIn("ALREADY verified", prompt)
        self.assertIn("bottoms out in an H1 function is fully executable", prompt)
        self.assertIn("Judge meaning, not mechanics", prompt)

    def test_warns_against_blaming_the_hierarchy_for_a_bad_plan(self) -> None:
        task, scene_json, state_output = task_inputs()
        prompt = build_router_prompt(
            task, scene_json, state_output, PLAN_RESPONSE, HIERARCHY_RESPONSE
        )
        self.assertIn("Do not blame the", prompt)


class ParsePlanSubtasksTest(unittest.TestCase):
    def test_reads_descriptions_and_goal_states(self) -> None:
        subtasks, errors = parse_plan_subtasks(PLAN_RESPONSE)
        self.assertEqual(errors, [])
        self.assertEqual(len(subtasks), 2)
        self.assertEqual(subtasks[0]["subtask_index"], 1)
        self.assertIn("ring_3 becomes free", subtasks[0]["description"])
        self.assertIn("peg_c", subtasks[1]["goal_state_text"])

    def test_missing_goal_state_is_reported(self) -> None:
        text = """```start_subtask_1
Do the thing.
```end_subtask_1"""
        subtasks, errors = parse_plan_subtasks(text)
        self.assertEqual(len(subtasks), 1)
        self.assertTrue(any("no goal state block" in err for err in errors), errors)

    def test_numbering_gap_is_reported(self) -> None:
        text = """```start_subtask_1
First.
```end_subtask_1
```start_subtask_goalstate_1
{}
```end_subtask_goalstate_1
```start_subtask_3
Third.
```end_subtask_3
```start_subtask_goalstate_3
{}
```end_subtask_goalstate_3"""
        _, errors = parse_plan_subtasks(text)
        self.assertTrue(any("without gaps" in err for err in errors), errors)

    def test_empty_output_is_reported(self) -> None:
        subtasks, errors = parse_plan_subtasks("no flags at all")
        self.assertEqual(subtasks, [])
        self.assertTrue(errors)

    def test_goalstate_blocks_do_not_match_the_description_pattern(self) -> None:
        """start_subtask_goalstate_1 must not be read as a description block."""
        subtasks, _ = parse_plan_subtasks(PLAN_RESPONSE)
        for subtask in subtasks:
            self.assertNotIn("start_subtask_goalstate", str(subtask["description"]))


class ParseRouterVerdictTest(unittest.TestCase):
    def test_no_mistake(self) -> None:
        output = """```start_result
RESULT: YES
OWNER: NA
REASON: N/A
```end_result"""
        no_mistake, owner, _ = parse_router_verdict(output)
        self.assertTrue(no_mistake)
        self.assertEqual(owner, "NA")

    def test_hierarchy_owns_it(self) -> None:
        output = """```start_result
RESULT: NO
OWNER: HierarchyPlanner
REASON: MoveTower2 places the larger ring on the smaller one in subtask 1.
```end_result"""
        no_mistake, owner, reason = parse_router_verdict(output)
        self.assertFalse(no_mistake)
        self.assertEqual(owner, OWNER_HIERARCHY)
        self.assertIn("MoveTower2", reason)

    def test_decision_owns_it(self) -> None:
        output = """```start_result
RESULT: NO
OWNER: DecisionBot
REASON: Subtask 1 leaves ring_2 on peg_a, which blocks the final goal.
```end_result"""
        _, owner, _ = parse_router_verdict(output)
        self.assertEqual(owner, OWNER_DECISION)

    def test_both_owns_it(self) -> None:
        output = """```start_result
RESULT: NO
OWNER: both
REASON: The plan skips a checkpoint and the calls use the wrong pegs.
```end_result"""
        _, owner, _ = parse_router_verdict(output)
        self.assertEqual(owner, OWNER_BOTH)

    def test_unreadable_verdict_routes_to_both(self) -> None:
        no_mistake, owner, reason = parse_router_verdict("the model rambled and gave no fields")
        self.assertFalse(no_mistake)
        self.assertEqual(owner, OWNER_BOTH)
        self.assertIn("could not parse", reason)

    def test_missing_owner_on_a_no_routes_to_both(self) -> None:
        output = """```start_result
RESULT: NO
REASON: Something is wrong.
```end_result"""
        no_mistake, owner, reason = parse_router_verdict(output)
        self.assertFalse(no_mistake)
        self.assertEqual(owner, OWNER_BOTH)
        self.assertIn("no usable OWNER", reason)

    def test_owner_normalization_variants(self) -> None:
        self.assertEqual(normalize_owner("decision bot"), OWNER_DECISION)
        self.assertEqual(normalize_owner("DECISION_BOT"), OWNER_DECISION)
        self.assertEqual(normalize_owner("hierarchy-planner"), OWNER_HIERARCHY)
        self.assertEqual(normalize_owner("Hierarchy Planner"), OWNER_HIERARCHY)
        self.assertEqual(normalize_owner("DecisionBot and HierarchyPlanner"), OWNER_BOTH)
        self.assertEqual(normalize_owner("nonsense"), "")

    def test_verdict_without_flags_still_parses(self) -> None:
        output = "RESULT: NO\nOWNER: HierarchyPlanner\nREASON: wrong argument order"
        no_mistake, owner, _ = parse_router_verdict(output)
        self.assertFalse(no_mistake)
        self.assertEqual(owner, OWNER_HIERARCHY)


class FormatRoundTripTest(unittest.TestCase):
    """A response in the documented format must survive the whole pipeline."""

    def test_hierarchy_response_parses_validates_and_solves(self) -> None:
        task = load_task("hanoi_3")

        h1_mappings, h1_errors = parse_mappings(H1_MAPPING_TEXT)
        composed, composed_errors = parse_mappings(HIERARCHY_RESPONSE)
        self.assertEqual(h1_errors, [])
        self.assertEqual(composed_errors, [])
        mappings = {**h1_mappings, **composed}

        analysis = analyze_hierarchy(mappings)
        self.assertTrue(analysis.valid)
        self.assertEqual(analysis.max_level, 4)  # MoveSingleRing 1, Tower1 2, Tower2 3, Tower3 4

        subtasks, plan_errors = parse_subtask_plans(HIERARCHY_RESPONSE)
        self.assertEqual(plan_errors, [])
        self.assertEqual(len(subtasks), 2)

        all_calls = [call for subtask in subtasks for call in subtask]
        h0_calls, expand_errors = expand_hierarchy(all_calls, mappings)
        self.assertEqual(expand_errors, [])

        moves, move_errors = extract_moves_from_h0(h0_calls)
        self.assertEqual(move_errors, [])
        legal, illegal_reason, final_state = simulate_hanoi(task, moves)
        self.assertTrue(legal, illegal_reason)
        self.assertEqual(final_state, task.goal)
        self.assertEqual(len(moves), task.optimal_move_count)

    def test_plan_and_hierarchy_subtask_numbering_line_up(self) -> None:
        plan_subtasks, _ = parse_plan_subtasks(PLAN_RESPONSE)
        call_subtasks, _ = parse_subtask_plans(HIERARCHY_RESPONSE)
        self.assertEqual(len(plan_subtasks), len(call_subtasks))

    def test_level_histogram_over_the_round_trip(self) -> None:
        h1_mappings, _ = parse_mappings(H1_MAPPING_TEXT)
        composed, _ = parse_mappings(HIERARCHY_RESPONSE)
        mappings = {**h1_mappings, **composed}
        levels, _ = infer_levels(mappings)
        subtasks, _ = parse_subtask_plans(HIERARCHY_RESPONSE)
        all_calls = [call for subtask in subtasks for call in subtask]

        histogram = count_calls_by_level(all_calls, mappings, levels)
        self.assertEqual(histogram[1], 7)  # seven base moves for hanoi_3


if __name__ == "__main__":
    unittest.main()
