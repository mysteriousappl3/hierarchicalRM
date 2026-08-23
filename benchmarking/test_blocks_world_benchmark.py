from __future__ import annotations

import json
import unittest
from pathlib import Path

from blocks_world_benchmark import MODES, run_mode
from blocks_world_structured import (
    compile_hierarchy_output,
    parse_decision_output,
    parse_json_object,
)
from blocks_world_task import build_paper_task
from models import ModelClient, empty_usage


MOVES = [
    ("B", "0", "1"),
    ("A", "0", "2"),
    ("B", "1", "2"),
    ("D", "1", "0"),
    ("B", "2", "0"),
    ("C", "1", "0"),
    ("A", "2", "0"),
]

DIRECT = "```start_all_functions\n" + "\n".join(
    f"MoveBlock({block}, {source}, {target})" for block, source, target in MOVES
) + "\n```end_all_functions"

DESCRIPTOR = """start_flag
{"stack_order":"bottom_to_top","current":{"0":["A","B"],"1":["C","D"],"2":[]},"goal":{"0":["D","B","C","A"],"1":[],"2":[]},"constraints":["top blocks only"]}
end_flag"""

YES = """```start_result
RESULT: YES
REASON: N/A
```end_result"""

ROUTER_YES = """```start_result
RESULT: YES
OWNER: NA
REASON: N/A
```end_result"""

OUTER_SUCCESS = """```start_error_type
Error: TASK SUCCESS
Reason: N/A
```end_error_type"""

H1 = """```start_mapping
MoveTopBlock(block, source_stack, target_stack) = [MoveBlock(block, source_stack, target_stack)]
```end_mapping"""

H2 = "```start_mapping\nSolveFour() = [" + ", ".join(
    f"MoveTopBlock({block}, {source}, {target})" for block, source, target in MOVES
) + "]\n```end_mapping"

FIXED_DECISION = """```start_subtask_funcs_1
SolveFour()
```end_subtask_funcs_1"""

PLAN_ONLY = json.dumps(
    {
        "subtasks": [
            {
                "id": 1,
                "objective": "Rearrange all four blocks into the exact goal stack.",
                "goal_state": {"0": ["D", "B", "C", "A"], "1": [], "2": []},
            }
        ]
    }
)

DYNAMIC_PAYLOAD = {
    "functions": [
        {
            "name": "MoveTopBlock",
            "level": 1,
            "parameters": ["block", "source_stack", "target_stack"],
            "body": [
                {
                    "function": "MoveBlock",
                    "arguments": ["block", "source_stack", "target_stack"],
                }
            ],
        },
        {
            "name": "SolveFour",
            "level": 2,
            "parameters": [],
            "body": [
                {
                    "function": "MoveTopBlock",
                    "arguments": [block, source, target],
                }
                for block, source, target in MOVES
            ],
        },
    ],
    "dispatch": [{"subtask_id": 1, "function": "SolveFour", "arguments": []}],
}
DYNAMIC = json.dumps(DYNAMIC_PAYLOAD)


class ScriptedBlocksClient(ModelClient):
    provider = "scripted"

    def __init__(self) -> None:
        super().__init__("scripted-blocks-world")

    def generate(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        response_schema=None,
        schema_name=None,
    ) -> str:
        lowered = system.lower()
        if "outerbot" in lowered:
            output = OUTER_SUCCESS
        elif "router" in lowered:
            output = ROUTER_YES
        elif "innerbot" in lowered:
            output = YES
        elif "statedescriptor" in lowered:
            output = DESCRIPTOR
        elif "hierarchyplanner" in lowered:
            output = DYNAMIC
        elif "plan-only" in lowered:
            output = PLAN_ONLY
        elif "h2" in lowered:
            output = H2
        elif "h1" in lowered:
            output = H1
        elif "decisionbot" in lowered:
            output = FIXED_DECISION
        elif "direct" in lowered:
            output = DIRECT
        else:
            raise AssertionError(f"Unexpected system prompt: {system}")
        return self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            response_schema_name=schema_name if response_schema else None,
            usage=empty_usage("scripted"),
        )


class RepairingHierarchyClient(ScriptedBlocksClient):
    def __init__(self) -> None:
        super().__init__()
        self.hierarchy_calls = 0

    def generate(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        response_schema=None,
        schema_name=None,
    ) -> str:
        if "dynamic hierarchyplanner generator" not in system.lower():
            return super().generate(
                system,
                prompt,
                max_tokens,
                response_schema=response_schema,
                schema_name=schema_name,
            )
        self.hierarchy_calls += 1
        payload = json.loads(json.dumps(DYNAMIC_PAYLOAD))
        if self.hierarchy_calls == 1:
            payload["dispatch"][0]["arguments"] = ["source_stack"]
        output = json.dumps(payload)
        return self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            response_schema_name=schema_name if response_schema else None,
            usage=empty_usage("scripted"),
        )


class RepairingDecisionClient(ScriptedBlocksClient):
    def __init__(self) -> None:
        super().__init__()
        self.decision_calls = 0

    def generate(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        response_schema=None,
        schema_name=None,
    ) -> str:
        if "plan-only planner" not in system.lower():
            return super().generate(
                system,
                prompt,
                max_tokens,
                response_schema=response_schema,
                schema_name=schema_name,
            )
        self.decision_calls += 1
        output = PLAN_ONLY
        if self.decision_calls == 1:
            payload = json.loads(PLAN_ONLY)
            payload["subtasks"][0]["goal_state"] = {
                "0": ["A", "B"],
                "1": ["C", "D"],
                "2": [],
            }
            output = json.dumps(payload)
        return self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            response_schema_name=schema_name if response_schema else None,
            usage=empty_usage("scripted"),
        )


class BlocksWorldBenchmarkTest(unittest.TestCase):
    def test_paper_four_task_has_exact_oracle(self) -> None:
        task = build_paper_task(4)
        self.assertEqual(task.optimal_move_count, 7)
        self.assertEqual(task.initial, {"0": ["A", "B"], "1": ["C", "D"], "2": []})
        self.assertEqual(task.goal, {"0": ["D", "B", "C", "A"], "1": [], "2": []})

    def test_paper_moves_parser_ignores_following_explanation(self) -> None:
        from blocks_world_scoring import parse_direct_plan, simulate_calls

        # Use the exact multiline shape returned by the live model.
        output = "moves = [\n" + ",\n".join(
            f'  ["{block}", {source}, {target}]' for block, source, target in MOVES
        ) + '\n]\nThis results in Stack 0 being ["D", "B", "C", "A"].'
        calls, errors = parse_direct_plan(output)
        self.assertFalse(errors)
        self.assertEqual(len(calls), 7)
        self.assertTrue(simulate_calls(build_paper_task(4), calls)[0])

    def test_mapping_parser_accepts_semantic_mapping_without_flag_wrapper(self) -> None:
        from blocks_world_scoring import parse_mappings, parse_subtask_plans

        mappings, mapping_errors = parse_mappings(
            "```text\nMoveTopBlock(block, source, target) = [MoveBlock(block, source, target)]\n```"
        )
        subtasks, plan_errors = parse_subtask_plans("1.\n```text\nMoveTopBlock(B, 0, 1)\n```")
        self.assertFalse(mapping_errors)
        self.assertIn("MoveTopBlock", mappings)
        self.assertFalse(plan_errors)
        self.assertEqual(str(subtasks[0][0]), "MoveTopBlock(B, 0, 1)")

    def test_structured_hierarchy_compiler_separates_binding_from_graph_errors(self) -> None:
        task = build_paper_task(4)
        decision = parse_decision_output(PLAN_ONLY, task)
        payload = json.loads(json.dumps(DYNAMIC_PAYLOAD))
        payload["functions"][1]["body"][0]["arguments"][1] = "undeclared_stack"
        compiled = compile_hierarchy_output(json.dumps(payload), task, decision)
        self.assertTrue(compiled.format_valid)
        self.assertTrue(compiled.hierarchy_graph_valid)
        self.assertFalse(compiled.parameter_binding_valid)
        self.assertIn("unbound argument undeclared_stack", "; ".join(compiled.binding_errors))

    def test_structured_parser_rejects_explanatory_text(self) -> None:
        payload, error = parse_json_object('Here is the plan: {"subtasks": []}')
        self.assertIsNone(payload)
        self.assertIn("before the JSON object", error or "")

    def test_structured_hierarchy_compiler_rejects_fake_depth(self) -> None:
        task = build_paper_task(4)
        decision = parse_decision_output(PLAN_ONLY, task)
        payload = json.loads(json.dumps(DYNAMIC_PAYLOAD))
        payload["functions"].append(
            {
                "name": "DecorativeH3",
                "level": 3,
                "parameters": [],
                "body": [{"function": "SolveFour", "arguments": []}],
            }
        )
        payload["dispatch"][0]["function"] = "DecorativeH3"
        compiled = compile_hierarchy_output(json.dumps(payload), task, decision)
        self.assertTrue(compiled.hierarchy_graph_valid)
        self.assertFalse(compiled.hierarchy_useful)
        self.assertIn("adds depth without reuse or compression", "; ".join(compiled.usefulness_errors))

    def test_all_four_modes_solve_and_write_consistent_artifacts(self) -> None:
        task = build_paper_task(4)
        expected_calls = {
            "no-framework": 1,
            "inner-outer": 3,
            "h1-h2": 7,
            "complete-framework": 6,
        }
        root = Path(__file__).resolve().parent / "results"
        for mode in MODES:
            with self.subTest(mode=mode):
                row = run_mode(
                    task=task,
                    mode=mode,
                    client=ScriptedBlocksClient(),
                    max_replans=0,
                    results_dir=root,
                )
                self.assertTrue(row["solved"])
                self.assertTrue(row["legal"])
                self.assertTrue(row["optimal"])
                self.assertEqual(row["move_count"], 7)
                self.assertEqual(row["model_call_count"], expected_calls[mode])
                result_dir = Path(str(row["result_dir"]))
                self.assertTrue((result_dir / "metrics.json").is_file())
                self.assertTrue((result_dir / "steps.json").is_file())
                self.assertTrue((result_dir / "raw_log.jsonl").is_file())

    def test_complete_framework_reuses_decision_when_hierarchy_binding_fails(self) -> None:
        row = run_mode(
            task=build_paper_task(4),
            mode="complete-framework",
            client=RepairingHierarchyClient(),
            max_replans=1,
            results_dir=Path(__file__).resolve().parent / "results",
        )
        self.assertTrue(row["solved"])
        self.assertEqual(row["model_calls_by_stage"]["decision"], 1)
        self.assertEqual(row["model_calls_by_stage"]["hierarchy_planner"], 2)
        self.assertEqual(row["stage_replan_counts"]["hierarchy"], 1)
        self.assertEqual(row["artifact_reuse_counts"]["decision"], 1)
        self.assertEqual(row["binding_failure_count"], 1)
        self.assertTrue(row["parameter_binding_valid"])

    def test_complete_framework_regenerates_decision_but_reuses_state(self) -> None:
        row = run_mode(
            task=build_paper_task(4),
            mode="complete-framework",
            client=RepairingDecisionClient(),
            max_replans=1,
            results_dir=Path(__file__).resolve().parent / "results",
        )
        self.assertTrue(row["solved"])
        self.assertEqual(row["model_calls_by_stage"]["decision"], 2)
        self.assertEqual(row["model_calls_by_stage"]["hierarchy_planner"], 1)
        self.assertEqual(row["stage_replan_counts"]["decision"], 1)
        self.assertEqual(row["artifact_reuse_counts"]["state_descriptor"], 1)
        self.assertEqual(row["artifact_reuse_counts"]["decision"], 0)
        self.assertEqual(row["decision_failure_count"], 1)
        self.assertEqual(row["decision_semantic_failure_count"], 1)
        self.assertEqual(row["format_failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
