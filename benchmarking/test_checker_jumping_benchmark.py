from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from checker_jumping_benchmark import MODES, run_mode
from checker_jumping_scoring import (
    FunctionCall,
    apply_move,
    parse_direct_plan,
    simulate_calls,
)
from checker_jumping_structured import compile_hierarchy_output, parse_decision_output
from checker_jumping_task import build_paper_task
from models import ModelClient, empty_usage


MOVES = [
    ("R", 1, 2),
    ("B", 3, 1),
    ("B", 4, 3),
    ("R", 2, 4),
    ("R", 0, 2),
    ("B", 1, 0),
    ("B", 3, 1),
    ("R", 2, 3),
]

DIRECT = "moves = " + json.dumps([list(move) for move in MOVES])
DESCRIPTOR = """```start_flag
{"board":["R","R","_","B","B"],"goal":["B","B","_","R","R"],"empty_position":2,"directions":{"R":"right","B":"left"},"constraints":["slide","jump","no backward moves"]}
```end_flag"""
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
MoveCheckerForward(color, source_position, target_position) = [MoveChecker(color, source_position, target_position)]
```end_mapping"""
H2 = "```start_mapping\nSolveTwo() = [" + ", ".join(
    f"MoveCheckerForward({color}, {source}, {target})"
    for color, source, target in MOVES
) + "]\n```end_mapping"
FIXED_DECISION = """```start_subtask_funcs_1
SolveTwo()
```end_subtask_funcs_1"""
PLAN_ONLY = json.dumps(
    {
        "subtasks": [
            {
                "id": 1,
                "objective": "Swap both checker groups.",
                "goal_state": ["B", "B", "_", "R", "R"],
            }
        ]
    }
)
DYNAMIC_PAYLOAD = {
    "functions": [
        {
            "name": "MoveCheckerForward",
            "level": 1,
            "parameters": ["color", "source_position", "target_position"],
            "body": [
                {
                    "function": "MoveChecker",
                    "arguments": ["color", "source_position", "target_position"],
                }
            ],
        },
        {
            "name": "SolveTwo",
            "level": 2,
            "parameters": [],
            "body": [
                {
                    "function": "MoveCheckerForward",
                    "arguments": [color, str(source), str(target)],
                }
                for color, source, target in MOVES
            ],
        },
    ],
    "dispatch": [{"subtask_id": 1, "function": "SolveTwo", "arguments": []}],
}
DYNAMIC = json.dumps(DYNAMIC_PAYLOAD)


class ScriptedCheckerClient(ModelClient):
    provider = "scripted"

    def __init__(self) -> None:
        super().__init__("scripted-checker-jumping")

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


class RepairingHierarchyClient(ScriptedCheckerClient):
    def __init__(self) -> None:
        super().__init__()
        self.hierarchy_calls = 0

    def generate(self, system: str, prompt: str, max_tokens: int = 4096, response_schema=None, schema_name=None) -> str:
        if "dynamic hierarchyplanner" not in system.lower():
            return super().generate(system, prompt, max_tokens, response_schema, schema_name)
        self.hierarchy_calls += 1
        payload = json.loads(json.dumps(DYNAMIC_PAYLOAD))
        if self.hierarchy_calls == 1:
            payload["dispatch"][0]["arguments"] = ["source_position"]
        output = json.dumps(payload)
        return self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            response_schema_name=schema_name if response_schema else None,
            usage=empty_usage("scripted"),
        )


class CheckerJumpingBenchmarkTest(unittest.TestCase):
    def test_task_contract_and_optimal_formula(self) -> None:
        task = build_paper_task(2)
        self.assertEqual(task.initial, ["R", "R", "_", "B", "B"])
        self.assertEqual(task.goal, ["B", "B", "_", "R", "R"])
        self.assertEqual(task.optimal_move_count, 8)
        self.assertEqual(task.total_checkers, 4)

    def test_known_optimal_plan_solves(self) -> None:
        task = build_paper_task(2)
        calls = [FunctionCall("MoveChecker", tuple(map(str, move))) for move in MOVES]
        legal, reason, failure, final_state, moves = simulate_calls(task, calls)
        self.assertTrue(legal, reason)
        self.assertIsNone(failure)
        self.assertEqual(final_state, task.goal)
        self.assertEqual(len(moves), task.optimal_move_count)

    def test_move_constraints(self) -> None:
        cases = [
            (["R", "_", "B"], ("R", "0", "1"), True, None),
            (["R", "_", "B"], ("B", "2", "1"), True, None),
            (["R", "B", "_"], ("R", "0", "2"), True, None),
            (["_", "R", "B"], ("B", "2", "0"), True, None),
            (["_", "R", "B"], ("R", "1", "0"), False, "backward"),
            (["R", "R", "_"], ("R", "0", "2"), False, "must cross exactly one B"),
            (["R", "_", "B"], ("R", "0", "2"), False, "not empty"),
            (["R", "_", "B"], ("R", "0", "4"), False, "out of range"),
        ]
        for board, args, expected, fragment in cases:
            with self.subTest(board=board, args=args):
                ok, reason = apply_move(list(board), FunctionCall("MoveChecker", args), 1)
                self.assertEqual(ok, expected)
                if fragment:
                    self.assertIn(fragment, reason or "")

    def test_paper_moves_parser_ignores_following_text(self) -> None:
        calls, errors = parse_direct_plan(DIRECT + "\nDone.")
        self.assertFalse(errors)
        self.assertEqual(len(calls), 8)
        self.assertEqual(calls[0].args, ("R", "1", "2"))

    def test_structured_compiler_accepts_useful_hierarchy(self) -> None:
        task = build_paper_task(2)
        decision = parse_decision_output(PLAN_ONLY, task)
        compiled = compile_hierarchy_output(DYNAMIC, task, decision)
        self.assertTrue(decision.valid, decision.errors)
        self.assertTrue(compiled.valid, compiled.errors)
        self.assertEqual(compiled.max_level, 2)
        self.assertEqual(compiled.compression_ratio, 8.0)

    def test_structured_compiler_rejects_direct_h0_above_h1(self) -> None:
        task = build_paper_task(2)
        decision = parse_decision_output(PLAN_ONLY, task)
        payload = json.loads(json.dumps(DYNAMIC_PAYLOAD))
        payload["functions"][1]["body"][0]["function"] = "MoveChecker"
        compiled = compile_hierarchy_output(json.dumps(payload), task, decision)
        self.assertFalse(compiled.hierarchy_graph_valid)
        self.assertIn("calls H0 directly", "; ".join(compiled.hierarchy_errors))

    def test_all_four_modes_solve_and_write_artifacts(self) -> None:
        expected_calls = {
            "no-framework": 1,
            "inner-outer": 3,
            "h1-h2": 7,
            "complete-framework": 6,
        }
        with tempfile.TemporaryDirectory() as directory:
            for mode in MODES:
                with self.subTest(mode=mode):
                    row = run_mode(
                        task=build_paper_task(2),
                        mode=mode,
                        client=ScriptedCheckerClient(),
                        max_replans=0,
                        results_dir=Path(directory),
                    )
                    self.assertTrue(row["solved"])
                    self.assertTrue(row["legal"])
                    self.assertTrue(row["optimal"])
                    self.assertEqual(row["model_call_count"], expected_calls[mode])
                    result_dir = Path(str(row["result_dir"]))
                    self.assertTrue((result_dir / "metrics.json").is_file())
                    self.assertTrue((result_dir / "steps.json").is_file())
                    self.assertTrue((result_dir / "raw_log.jsonl").is_file())

    def test_complete_framework_reuses_decision_after_hierarchy_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            row = run_mode(
                task=build_paper_task(2),
                mode="complete-framework",
                client=RepairingHierarchyClient(),
                max_replans=1,
                results_dir=Path(directory),
            )
        self.assertTrue(row["solved"])
        self.assertEqual(row["model_calls_by_stage"]["decision"], 1)
        self.assertEqual(row["model_calls_by_stage"]["hierarchy_planner"], 2)
        self.assertEqual(row["stage_replan_counts"]["hierarchy"], 1)
        self.assertEqual(row["artifact_reuse_counts"]["decision"], 1)


if __name__ == "__main__":
    unittest.main()
