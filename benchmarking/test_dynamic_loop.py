"""Tests for the dynamic-hierarchy loop, driven by a scripted client.

The behaviour under test is routing: whether the plan survives a correction
round depends entirely on who the router blames, and a symbolic failure must be
attributed without spending a model call.

Run:
    python benchmarking/test_dynamic_loop.py
"""

from __future__ import annotations

import unittest
from typing import Dict, List, Optional

from dynamic_hierarchy_benchmark import run_dynamic_hierarchy_loop, validate_dynamic_plan
from dynamic_scoring import OWNER_BOTH, OWNER_DECISION, OWNER_HIERARCHY, infer_levels
from models import MockHanoiClient, ModelClient, empty_usage
from scoring import parse_mappings, parse_subtask_plans
from task_loader import load_task
from test_unrolled_tower import H1_MAPPING_TEXT, build_tower_mapping_text


def stage_of(system: str) -> str:
    lowered = system.lower()
    for name in ("outerbot", "router", "hierarchyplanner", "plan only", "innerbot", "state", "h1"):
        if name in lowered:
            return "plan" if name == "plan only" else name
    return "other"


class ScriptedClient(ModelClient):
    """Returns queued responses per stage and records the stage call order."""

    provider = "scripted"

    def __init__(self, responses: Dict[str, List[str]], fallback: Optional[MockHanoiClient] = None):
        super().__init__("scripted-model")
        self.responses = {key: list(value) for key, value in responses.items()}
        self.fallback = fallback or MockHanoiClient("mock-hanoi")
        self.stage_calls: List[str] = []

    def generate(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        stage = stage_of(system)
        self.stage_calls.append(stage)
        queued = self.responses.get(stage)
        if queued:
            output = queued.pop(0)
        else:
            output = self.fallback.generate(system=system, prompt=prompt, max_tokens=max_tokens)
        return self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            usage=empty_usage("scripted"),
        )

    def count(self, stage: str) -> int:
        return self.stage_calls.count(stage)


def router_verdict(result: str, owner: str = "NA", reason: str = "N/A") -> str:
    return f"""```start_result
RESULT: {result}
OWNER: {owner}
REASON: {reason}
```end_result"""


def outerbot_verdict(error: str, reason: str = "N/A") -> str:
    return f"""```start_error_type
Error : {error}
Reason : {reason}
```end_error_type"""


BROKEN_HIERARCHY = """```start_mapping
Nonsense(a, b) = [UndefinedFunction(a, b)]
```end_mapping

```start_subtask_funcs_1
Nonsense(peg_a, peg_c)
```end_subtask_funcs_1"""

# Parses and expands cleanly, but the moves are illegal for hanoi_3.
ILLEGAL_HIERARCHY = """```start_mapping
BadMove(src, dst) = [MoveSingleRing(src, dst)]
```end_mapping

```start_subtask_funcs_1
BadMove(peg_a, peg_c)
BadMove(peg_a, peg_c)
```end_subtask_funcs_1"""


def run_loop(client, task_id: str = "hanoi_3", max_replans: int = 3):
    return run_dynamic_hierarchy_loop(
        task=load_task(task_id),
        client=client,
        fixed_goal=True,
        max_tokens=4096,
        max_replans=max_replans,
        reuse_h1=False,
        include_code_block=True,
    )


class HappyPathTest(unittest.TestCase):
    def test_solves_without_any_correction(self) -> None:
        client = ScriptedClient({})
        result = run_loop(client)
        self.assertTrue(result["score"].solved)
        self.assertTrue(result["score"].optimal)
        self.assertEqual(result["termination_reason"], "task_success")
        self.assertEqual(result["replan_count"], 0)
        self.assertEqual(client.count("plan"), 1)
        self.assertEqual(client.count("hierarchyplanner"), 1)
        self.assertEqual(client.count("router"), 1)

    def test_reuse_h1_skips_regeneration(self) -> None:
        client = ScriptedClient({"router": [router_verdict("NO", "HierarchyPlanner", "bad")]})
        run_dynamic_hierarchy_loop(
            task=load_task("hanoi_3"),
            client=client,
            fixed_goal=True,
            max_tokens=4096,
            max_replans=2,
            reuse_h1=True,
            include_code_block=True,
        )
        self.assertEqual(client.count("h1"), 1)


class RoutingTest(unittest.TestCase):
    def test_hierarchy_owner_keeps_the_plan(self) -> None:
        client = ScriptedClient(
            {"router": [router_verdict("NO", "HierarchyPlanner", "wrong composition")]}
        )
        result = run_loop(client)
        # Two rounds ran, but the planner was only ever called once.
        self.assertEqual(client.count("hierarchyplanner"), 2)
        self.assertEqual(client.count("plan"), 1)
        self.assertEqual(result["extra_metrics"]["router_attribution_counts"][OWNER_HIERARCHY], 1)

    def test_decision_owner_regenerates_the_plan(self) -> None:
        client = ScriptedClient(
            {"router": [router_verdict("NO", "DecisionBot", "subtask skips a ring")]}
        )
        result = run_loop(client)
        self.assertEqual(client.count("plan"), 2)
        self.assertEqual(result["extra_metrics"]["router_attribution_counts"][OWNER_DECISION], 1)

    def test_both_takes_the_same_path_as_decision(self) -> None:
        client = ScriptedClient({"router": [router_verdict("NO", "both", "both are wrong")]})
        result = run_loop(client)
        self.assertEqual(client.count("plan"), 2)
        self.assertEqual(result["extra_metrics"]["router_attribution_counts"][OWNER_BOTH], 1)

    def test_unparseable_verdict_routes_to_both(self) -> None:
        client = ScriptedClient({"router": ["the model rambled"]})
        result = run_loop(client)
        self.assertEqual(client.count("plan"), 2)
        self.assertEqual(result["extra_metrics"]["router_attribution_counts"][OWNER_BOTH], 1)


class SymbolicAttributionTest(unittest.TestCase):
    def test_unparseable_hierarchy_is_attributed_without_a_model_call(self) -> None:
        client = ScriptedClient({"hierarchyplanner": [BROKEN_HIERARCHY]})
        result = run_loop(client)
        # Round 1 failed at parsing, so the router LLM was never consulted for it.
        self.assertEqual(client.count("router"), 1)
        self.assertEqual(client.count("hierarchyplanner"), 2)
        self.assertEqual(client.count("plan"), 1)
        self.assertTrue(result["score"].solved)
        self.assertTrue(
            any("unresolvable callee" in err for err in result["score"].parse_errors),
            result["score"].parse_errors,
        )

    def test_illegal_moves_are_caught_before_execution(self) -> None:
        client = ScriptedClient({"hierarchyplanner": [ILLEGAL_HIERARCHY]})
        result = run_loop(client)
        self.assertEqual(client.count("router"), 1)
        self.assertEqual(client.count("plan"), 1)
        self.assertTrue(
            any("Symbolic:" in err for err in result["score"].parse_errors),
            result["score"].parse_errors,
        )
        self.assertTrue(result["score"].solved)

    def test_symbolic_failure_blames_the_hierarchy_not_the_plan(self) -> None:
        """The plan carries no calls, so it cannot fail symbolic validation."""
        client = ScriptedClient({"hierarchyplanner": [ILLEGAL_HIERARCHY]})
        result = run_loop(client)
        counts = result["extra_metrics"]["router_attribution_counts"]
        self.assertEqual(counts[OWNER_HIERARCHY], 1)
        self.assertEqual(counts[OWNER_DECISION], 0)
        self.assertEqual(counts[OWNER_BOTH], 0)


class OuterBotReroutingTest(unittest.TestCase):
    def test_recoverable_goes_through_the_router(self) -> None:
        client = ScriptedClient(
            {
                "outerbot": [outerbot_verdict("RECOVERABLE", "state does not match")],
                "router": [
                    router_verdict("YES"),
                    router_verdict("NO", "DecisionBot", "checkpoint was wrong"),
                ],
            }
        )
        result = run_loop(client)
        # Pre-execution check passed, then the OuterBot finding was re-diagnosed.
        self.assertGreaterEqual(client.count("router"), 2)
        self.assertEqual(result["extra_metrics"]["router_attribution_counts"][OWNER_DECISION], 1)

    def test_non_recoverable_terminates(self) -> None:
        client = ScriptedClient(
            {
                "outerbot": [outerbot_verdict("NON-RECOVERABLE", "constraint violated")],
                "router": [router_verdict("YES"), router_verdict("NO", "both", "unrecoverable")],
            }
        )
        result = run_loop(client)
        self.assertEqual(result["termination_reason"], "non_recoverable")

    def test_execute_remaining_actions_is_not_sent_to_the_router(self) -> None:
        """Only RECOVERABLE and NON-RECOVERABLE are worth attributing.

        Exactly one router call happens here: the pre-execution check in round
        one. The OuterBot verdict produces no re-diagnosis call, unlike the
        RECOVERABLE case above which produces two or more.
        """
        client = ScriptedClient(
            {"outerbot": [outerbot_verdict("EXECUTE REMAINING ACTIONS")]}
        )
        result = run_loop(client)
        self.assertEqual(client.count("router"), 1)
        self.assertTrue(result["score"].solved)
        self.assertEqual(result["extra_metrics"]["router_attribution_counts"][OWNER_BOTH], 1)

    def test_subtask_success_is_not_sent_to_the_router(self) -> None:
        client = ScriptedClient({"outerbot": [outerbot_verdict("SUBTASK SUCCESS")]})
        result = run_loop(client)
        self.assertEqual(client.count("router"), 1)
        self.assertTrue(result["score"].solved)


class MetricsTest(unittest.TestCase):
    def test_extra_metrics_shape(self) -> None:
        client = ScriptedClient({})
        result = run_loop(client, task_id="hanoi_5")
        extra = result["extra_metrics"]
        self.assertEqual(extra["max_hierarchy_level"], 6)
        self.assertEqual(extra["level_call_counts"]["1"], 31)
        self.assertEqual(extra["mapping_count_by_level"]["1"], 1)
        self.assertEqual(extra["hierarchy_errors"], [])
        self.assertIn("router_attributions", extra)
        for legacy in ("h1_valid", "h2_valid", "h1_call_count", "h2_call_count"):
            self.assertNotIn(legacy, extra, "legacy keys reach metrics through the score")

    def test_stage_counts_carry_back_compat_aliases(self) -> None:
        client = ScriptedClient({})
        result = run_loop(client)
        counts = result["stage_counts"]
        self.assertEqual(counts["decision_count"], counts["plan_generation_count"])
        self.assertEqual(counts["h2_generation_count"], counts["hierarchy_generation_count"])
        self.assertEqual(counts["innerbot_plan_check_count"], counts["router_check_count"])
        self.assertEqual(counts["innerbot_plan_llm_call_count"], counts["router_llm_call_count"])

    def test_deep_task_solves_through_the_full_loop(self) -> None:
        client = ScriptedClient({})
        result = run_loop(client, task_id="hanoi_12")
        self.assertTrue(result["score"].solved)
        self.assertTrue(result["score"].optimal)
        self.assertEqual(result["score"].move_count, 4095)
        self.assertEqual(result["score"].top_level_call_count, 1)
        self.assertEqual(result["extra_metrics"]["max_hierarchy_level"], 13)


class ValidateDynamicPlanTest(unittest.TestCase):
    def test_projected_states_advance_across_subtasks(self) -> None:
        task = load_task("hanoi_3")
        h1_mappings, _ = parse_mappings(H1_MAPPING_TEXT)
        composed, _ = parse_mappings(build_tower_mapping_text(3))
        mappings = {**h1_mappings, **composed}
        levels, _ = infer_levels(mappings)
        text = """```start_subtask_funcs_1
MoveTower2(peg_a, peg_c, peg_b)
```end_subtask_funcs_1
```start_subtask_funcs_2
MoveSingleRing(peg_a, peg_c)
MoveTower2(peg_b, peg_a, peg_c)
```end_subtask_funcs_2"""
        subtasks, _ = parse_subtask_plans(text)

        ok, reason, validated = validate_dynamic_plan(
            task=task,
            current_state={peg: list(stack) for peg, stack in task.initial.items()},
            subtasks=subtasks,
            mappings=mappings,
            levels=levels,
        )
        self.assertTrue(ok, reason)
        self.assertEqual(len(validated), 2)
        self.assertEqual(validated[0]["projected_state"]["peg_b"], ["ring_2", "ring_1"])
        self.assertEqual(validated[1]["projected_state"], task.goal)

    def test_illegal_move_is_rejected_with_a_reason(self) -> None:
        task = load_task("hanoi_3")
        h1_mappings, _ = parse_mappings(H1_MAPPING_TEXT)
        composed, _ = parse_mappings(ILLEGAL_HIERARCHY)
        mappings = {**h1_mappings, **composed}
        levels, _ = infer_levels(mappings)
        subtasks, _ = parse_subtask_plans(ILLEGAL_HIERARCHY)

        ok, reason, _ = validate_dynamic_plan(
            task=task,
            current_state={peg: list(stack) for peg, stack in task.initial.items()},
            subtasks=subtasks,
            mappings=mappings,
            levels=levels,
        )
        self.assertFalse(ok)
        self.assertIn("cannot place", reason)


if __name__ == "__main__":
    unittest.main()
