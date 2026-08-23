from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from checker_jumping_prompts import (
    direct_prompt,
    direct_system_prompt,
    dynamic_hierarchy_prompt,
    fixed_decision_prompt,
    h1_prompt,
    h2_prompt,
    inner_plan_prompt,
    inner_state_prompt,
    outer_prompt,
    plan_only_prompt,
    router_prompt,
    state_descriptor_prompt,
    state_descriptor_system_prompt,
)
from checker_jumping_scoring import (
    CheckerJumpingScore,
    FunctionCall,
    FunctionMapping,
    expand_calls,
    hierarchy_histogram,
    infer_levels,
    parse_direct_plan,
    parse_mappings,
    parse_subtask_plans,
    score_calls,
    score_execution,
    simulate_calls,
    validate_fixed_h2,
    validate_h1,
)
from checker_jumping_structured import (
    DECISION_SCHEMA,
    HIERARCHY_SCHEMA,
    DecisionParseResult,
    HierarchyCompileResult,
    compile_hierarchy_output,
    parse_decision_output,
)
from checker_jumping_task import CheckerJumpingTask, available_tasks, load_task
from dynamic_scoring import OWNER_BOTH, OWNER_DECISION, OWNER_HIERARCHY, parse_router_verdict
from hanoi_benchmark import (
    aggregate_token_usage,
    parse_innerbot_verdict,
    parse_outerbot_verdict,
)
from models import create_client, load_env_file


BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = BENCHMARK_DIR / ".env"
RESULTS_DIR = BENCHMARK_DIR / "results"
MODES = ("no-framework", "inner-outer", "h1-h2", "complete-framework")


class RunTrace:
    def __init__(self, client, max_tokens: int):
        self.client = client
        self.max_tokens = max_tokens
        self.events: List[Dict[str, object]] = []
        self.attempts: List[Dict[str, object]] = []
        self.stage_counts: Counter[str] = Counter()
        self.current_attempt = 0

    def call(
        self,
        stage: str,
        system: str,
        prompt: str,
        *,
        response_schema: Optional[Dict[str, object]] = None,
        schema_name: Optional[str] = None,
    ) -> str:
        started = time.perf_counter()
        output = self.client.generate(
            system=system,
            prompt=prompt,
            max_tokens=self.max_tokens,
            response_schema=response_schema,
            schema_name=schema_name,
        )
        self.stage_counts[stage] += 1
        self.events.append(
            {
                "event": "model_call",
                "attempt": self.current_attempt,
                "stage": stage,
                "system": system,
                "prompt": prompt,
                "output": output,
                "response_schema_name": schema_name if response_schema else None,
                "runtime_seconds": round(time.perf_counter() - started, 6),
            }
        )
        return output

    def record_attempt(self, payload: Dict[str, object]) -> None:
        self.attempts.append(payload)
        self.events.append({"event": "attempt_result", **payload})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run paper-style symbolic Checker Jumping planning benchmarks."
    )
    parser.add_argument(
        "--task",
        default="checker_jumping_3",
        help="Task id, such as checker_jumping_3, or 'all'.",
    )
    parser.add_argument(
        "--mode",
        choices=[*MODES, "all"],
        default="all",
        help="Planning condition. 'all' runs the four benchmark conditions.",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "anthropic", "gemini", "local", "openai-compatible"],
        default=None,
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument(
        "--reasoning",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
        default=None,
    )
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument(
        "--max-replans",
        type=int,
        default=2,
        help="Additional attempts after the first verifier or framework rejection.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    provider = args.provider or os.environ.get("DEFAULT_PROVIDER") or "openai"
    model = args.model or os.environ.get("DEFAULT_MODEL") or "gpt-5.6-luna"
    reasoning = args.reasoning or os.environ.get("DEFAULT_REASONING_EFFORT")
    client = create_client(provider, model, args.base_url, reasoning)
    task_ids = available_tasks() if args.task == "all" else [args.task]
    modes = list(MODES) if args.mode == "all" else [args.mode]
    rows: List[Dict[str, object]] = []
    for task_id in task_ids:
        task = load_task(task_id)
        for mode in modes:
            row = run_mode(
                task=task,
                mode=mode,
                client=client,
                max_tokens=args.max_tokens,
                max_replans=args.max_replans,
                reasoning_effort=reasoning,
            )
            rows.append(row)
            print(
                f"{task.id} {mode}: solved={row['solved']} legal={row['legal']} "
                f"moves={row['move_count']} calls={row['model_call_count']} "
                f"result={row['result_dir']}"
            )
    return 0 if all(bool(row["solved"]) for row in rows) else 1


def run_mode(
    *,
    task: CheckerJumpingTask,
    mode: str,
    client,
    max_tokens: int = 8192,
    max_replans: int = 2,
    reasoning_effort: Optional[str] = None,
    results_dir: Path = RESULTS_DIR,
) -> Dict[str, object]:
    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode}")
    call_start = len(getattr(client, "call_history", []))
    started_at = datetime.now().astimezone()
    timer = time.perf_counter()
    trace = RunTrace(client, max_tokens)

    if mode == "no-framework":
        score, run_metrics = run_direct(task, trace)
    elif mode == "inner-outer":
        score, run_metrics = run_inner_outer(task, trace, max_replans)
    elif mode == "h1-h2":
        score, run_metrics = run_fixed_hierarchy(task, trace, max_replans)
    else:
        score, run_metrics = run_complete_framework(task, trace, max_replans)

    call_records = client.call_records_since(call_start)
    score_data = score.as_dict()
    model_name = str(getattr(client, "model", "unknown"))
    provider = str(getattr(client, "provider", "unknown"))
    output_dir = make_result_dir(results_dir, model_name, mode, task.id)
    run_metrics.setdefault("format_valid", not bool(score.parse_errors))
    run_metrics.setdefault("hierarchy_graph_valid", None)
    run_metrics.setdefault("parameter_binding_valid", None)
    run_metrics.setdefault("dispatch_valid", None)
    run_metrics.setdefault("hierarchy_useful", None)
    run_metrics.setdefault("verifier_accepted", None if mode == "no-framework" else score.solved)
    run_metrics["primitive_plan_legal"] = score.legal
    run_metrics["goal_reached"] = score.solved
    metrics: Dict[str, object] = {
        "benchmark": "checker_jumping",
        "benchmark_version": 1,
        "task_id": task.id,
        "checkers_per_color": task.checkers_per_color,
        "total_checkers": task.total_checkers,
        "board_length": task.board_length,
        "mode": mode,
        "provider": provider,
        "model": model_name,
        "reasoning_effort": reasoning_effort,
        "started_at": started_at.isoformat(),
        "runtime_seconds": round(time.perf_counter() - timer, 6),
        "attempt_count": len(trace.attempts),
        "replan_count": max(0, len(trace.attempts) - 1),
        "model_call_count": len(call_records),
        "model_calls_by_stage": dict(sorted(trace.stage_counts.items())),
        **score_data,
        **run_metrics,
        "token_usage": aggregate_token_usage(call_records),
    }
    steps = {
        "task_id": task.id,
        "mode": mode,
        "position_indexing": "zero_based_left_to_right",
        "initial_state": task.initial,
        "goal_state": task.goal,
        "attempts": trace.attempts,
        "high_level_plan": score.high_level_plan,
        "expanded_h0_plan": score.expanded_h0_plan,
        "checker_moves": score.moves,
        "final_state": score.final_state,
    }
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "steps.json", steps)
    with (output_dir / "raw_log.jsonl").open("w", encoding="utf-8") as handle:
        for event in trace.events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    metrics["result_dir"] = str(output_dir)
    return metrics


def run_direct(
    task: CheckerJumpingTask, trace: RunTrace
) -> Tuple[CheckerJumpingScore, Dict[str, object]]:
    trace.current_attempt = 1
    output = trace.call("direct", direct_system_prompt(), direct_prompt(task, task.initial))
    calls, errors = parse_direct_plan(output)
    score = score_calls(task, calls, errors)
    trace.record_attempt(attempt_payload(1, score, output=output))
    metrics = verifier_metrics()
    metrics.update({"format_valid": not errors, "verifier_accepted": None})
    return score, metrics


def run_inner_outer(
    task: CheckerJumpingTask, trace: RunTrace, max_replans: int
) -> Tuple[CheckerJumpingScore, Dict[str, object]]:
    counters = verifier_metrics()
    feedback: Optional[str] = None
    last_score = empty_failure_score(task, "No plan attempt was made")
    for attempt in range(1, max_replans + 2):
        trace.current_attempt = attempt
        output = trace.call(
            "direct", direct_system_prompt(), direct_prompt(task, task.initial, feedback)
        )
        calls, errors = parse_direct_plan(output)
        last_score = score_calls(task, calls, errors)
        counters["format_valid"] = not errors
        summary = validation_summary(last_score, task.goal)
        verdict = trace.call(
            "innerbot_plan",
            "Checker Jumping InnerBot plan verifier.",
            inner_plan_prompt(task, task.initial, output, summary),
        )
        inner_ok, inner_reason = parse_innerbot_verdict(verdict)
        counters["innerbot_check_count"] += 1
        if not inner_ok:
            counters["innerbot_rejection_count"] += 1
        payload = attempt_payload(
            attempt,
            last_score,
            output=output,
            innerbot_accepted=inner_ok,
            innerbot_reason=inner_reason,
        )
        if not last_score.legal or not inner_ok:
            feedback = last_score.illegal_reason if not last_score.legal else inner_reason
            payload["replan_reason"] = feedback
            trace.record_attempt(payload)
            continue
        outer_ok, outer_data = verify_outer(
            task,
            trace,
            task.initial,
            last_score.final_state,
            task.goal,
            "Solve the full task",
            final=True,
            counters=counters,
        )
        payload["outerbot"] = outer_data
        trace.record_attempt(payload)
        if last_score.solved:
            if not outer_ok:
                counters["verifier_disagreement_count"] += 1
            counters["verifier_accepted"] = inner_ok and outer_ok
            return last_score, counters
        feedback = outer_data["reason"] or "Final state did not equal the goal"
        if outer_data["status"] == "NON-RECOVERABLE":
            break
    return last_score, counters


def run_fixed_hierarchy(
    task: CheckerJumpingTask, trace: RunTrace, max_replans: int
) -> Tuple[CheckerJumpingScore, Dict[str, object]]:
    counters = verifier_metrics()
    feedback: Optional[str] = None
    last_score = empty_failure_score(task, "No hierarchy attempt was made")
    for attempt in range(1, max_replans + 2):
        trace.current_attempt = attempt
        descriptor, descriptor_ok, descriptor_reason = generate_and_verify_state(
            task, trace, feedback
        )
        counters["innerbot_check_count"] += 1
        if not descriptor_ok:
            counters["innerbot_rejection_count"] += 1
            feedback = descriptor_reason
            last_score = empty_failure_score(task, descriptor_reason)
            trace.record_attempt(
                attempt_payload(attempt, last_score, replan_reason=feedback)
            )
            continue
        h1_output = trace.call(
            "h1", "Checker Jumping H1 action generator.", h1_prompt(task, descriptor)
        )
        h1_mappings, h1_errors = parse_mappings(h1_output)
        h1_valid, h1_reason = validate_h1(h1_mappings)
        h2_output = trace.call(
            "h2",
            "Checker Jumping H2 action generator.",
            h2_prompt(task, task.initial, descriptor, h1_output, feedback),
        )
        h2_mappings, h2_errors = parse_mappings(h2_output)
        h2_valid, h2_reason = validate_fixed_h2(h2_mappings, h1_mappings)
        decision_output = trace.call(
            "decision",
            "Checker Jumping DecisionBot fixed hierarchy planner.",
            fixed_decision_prompt(
                task, task.initial, descriptor, h1_output, h2_output, feedback
            ),
        )
        subtasks, plan_errors = parse_subtask_plans(decision_output)
        mappings = {**h1_mappings, **h2_mappings}
        structure_errors = [*h1_errors, *h2_errors, *plan_errors]
        if not h1_valid:
            structure_errors.append(h1_reason)
        if not h2_valid:
            structure_errors.append(h2_reason)
        for call in [call for subtask in subtasks for call in subtask]:
            if call.name not in h2_mappings:
                structure_errors.append(f"DecisionBot called non-H2 function {call.name}")
        validated = validate_subtasks(task, subtasks, mappings, structure_errors)
        levels, _, _ = infer_levels(mappings)
        top_calls = [call for subtask in subtasks for call in subtask]
        histogram = hierarchy_histogram(top_calls, mappings, levels)
        last_score = score_execution(
            task,
            validated["final_state"],
            validated["moves"],
            legal=bool(validated["legal"]),
            h1_valid=h1_valid,
            h2_valid=h2_valid,
            h1_count=histogram.get(1, 0),
            h2_count=histogram.get(2, 0),
            h0_count=len(validated["expanded"]),
            top_level_count=len(top_calls),
            max_hierarchy_level=max(levels.values(), default=0),
            level_call_counts=histogram,
            parse_errors=validated["errors"],
            illegal_reason=validated["reason"],
            first_failure_move=validated["failure"],
            high_level_plan=[str(call) for call in top_calls],
            expanded_h0_plan=validated["expanded"],
        )
        counters.update(
            {
                "format_valid": not (h1_errors or h2_errors or plan_errors),
                "hierarchy_graph_valid": h1_valid and h2_valid,
                "parameter_binding_valid": h1_valid and h2_valid,
            }
        )
        summary = validation_summary(last_score, task.goal)
        inner_output = trace.call(
            "innerbot_plan",
            "Checker Jumping InnerBot plan verifier.",
            inner_plan_prompt(
                task,
                task.initial,
                decision_output,
                summary,
                hierarchy_output=h1_output + "\n" + h2_output,
            ),
        )
        inner_ok, inner_reason = parse_innerbot_verdict(inner_output)
        counters["innerbot_check_count"] += 1
        if not inner_ok:
            counters["innerbot_rejection_count"] += 1
        payload = attempt_payload(
            attempt,
            last_score,
            state_descriptor=descriptor,
            h1_output=h1_output,
            h2_output=h2_output,
            decision_output=decision_output,
            innerbot_accepted=inner_ok,
            innerbot_reason=inner_reason,
        )
        if not last_score.legal or not inner_ok:
            feedback = last_score.illegal_reason if not last_score.legal else inner_reason
            payload["replan_reason"] = feedback
            trace.record_attempt(payload)
            continue
        outer_ok, outer_data = verify_outer(
            task,
            trace,
            task.initial,
            last_score.final_state,
            task.goal,
            "Solve the full task",
            final=True,
            counters=counters,
        )
        payload["outerbot"] = outer_data
        trace.record_attempt(payload)
        if last_score.solved:
            if not outer_ok:
                counters["verifier_disagreement_count"] += 1
            counters["verifier_accepted"] = inner_ok and outer_ok
            return last_score, counters
        feedback = outer_data["reason"] or "Execution did not reach the exact goal"
    return last_score, counters


def run_complete_framework(
    task: CheckerJumpingTask, trace: RunTrace, max_replans: int
) -> Tuple[CheckerJumpingScore, Dict[str, object]]:
    counters: Dict[str, object] = {
        **verifier_metrics(),
        "architecture_version": "checker_jumping_nlevel_v1",
        "decision_format_valid": False,
        "decision_semantic_valid": False,
        "hierarchy_format_valid": False,
        "hierarchy_graph_valid": False,
        "parameter_binding_valid": False,
        "dispatch_valid": False,
        "hierarchy_useful": False,
        "format_failure_count": 0,
        "decision_failure_count": 0,
        "decision_semantic_failure_count": 0,
        "hierarchy_failure_count": 0,
        "binding_failure_count": 0,
        "planning_failure_count": 0,
        "deterministic_router_count": 0,
        "stage_replan_counts": {"state_descriptor": 0, "decision": 0, "hierarchy": 0},
        "artifact_reuse_counts": {"state_descriptor": 0, "decision": 0},
        "router_attribution_counts": {
            OWNER_DECISION: 0,
            OWNER_HIERARCHY: 0,
            OWNER_BOTH: 0,
        },
        "mapping_count_by_level": {},
        "function_reuse_counts": {},
        "compression_ratio": None,
        "verifier_accepted": False,
    }
    feedback: Optional[str] = None
    descriptor: Optional[str] = None
    plan_output: Optional[str] = None
    decision: Optional[DecisionParseResult] = None
    hierarchy_output: Optional[str] = None
    compiled: Optional[HierarchyCompileResult] = None
    last_score = empty_failure_score(task, "No complete-framework attempt was made")

    def increment(group: str, key: str) -> None:
        values = counters[group]
        assert isinstance(values, dict)
        values[key] = int(values.get(key, 0)) + 1

    def reset_from(owner: str, can_retry: bool) -> None:
        nonlocal plan_output, decision, hierarchy_output, compiled
        canonical = owner if owner in {OWNER_DECISION, OWNER_HIERARCHY, OWNER_BOTH} else OWNER_BOTH
        increment("router_attribution_counts", canonical)
        if can_retry:
            increment("stage_replan_counts", "hierarchy" if canonical == OWNER_HIERARCHY else "decision")
        hierarchy_output = None
        compiled = None
        if canonical != OWNER_HIERARCHY:
            plan_output = None
            decision = None

    for attempt in range(1, max_replans + 2):
        trace.current_attempt = attempt
        can_retry = attempt <= max_replans
        regenerated = {
            "state_descriptor": descriptor is None,
            "decision": decision is None,
            "hierarchy": compiled is None,
        }
        if descriptor is not None:
            increment("artifact_reuse_counts", "state_descriptor")
        if decision is not None:
            increment("artifact_reuse_counts", "decision")

        if descriptor is None:
            descriptor, descriptor_ok, reason = generate_and_verify_state(task, trace, feedback)
            counters["innerbot_check_count"] = int(counters["innerbot_check_count"]) + 1
            if not descriptor_ok:
                counters["innerbot_rejection_count"] = int(counters["innerbot_rejection_count"]) + 1
                if can_retry:
                    increment("stage_replan_counts", "state_descriptor")
                feedback = reason
                last_score = empty_failure_score(task, reason)
                trace.record_attempt(
                    attempt_payload(
                        attempt,
                        last_score,
                        artifacts_regenerated=regenerated,
                        validation_stage="state_descriptor",
                        replan_owner="state_descriptor",
                        replan_reason=reason,
                    )
                )
                descriptor = None
                plan_output = None
                decision = None
                hierarchy_output = None
                compiled = None
                continue

        if decision is None:
            plan_output = trace.call(
                "decision",
                "Checker Jumping DecisionBot plan-only planner.",
                plan_only_prompt(task, task.initial, descriptor, feedback),
                response_schema=DECISION_SCHEMA,
                schema_name="checker_jumping_decision",
            )
            decision = parse_decision_output(plan_output, task)
        counters["decision_format_valid"] = decision.format_valid
        counters["decision_semantic_valid"] = decision.semantic_valid
        if not decision.valid:
            counters["decision_failure_count"] = int(counters["decision_failure_count"]) + 1
            counters["decision_semantic_failure_count"] = int(
                counters["decision_semantic_failure_count"]
            ) + int(decision.format_valid and not decision.semantic_valid)
            counters["format_failure_count"] = int(counters["format_failure_count"]) + int(
                not decision.format_valid
            )
            reason = "; ".join(decision.errors) or "DecisionBot output was invalid"
            last_score = empty_failure_score(task, reason)
            counters["deterministic_router_count"] = int(counters["deterministic_router_count"]) + 1
            payload = attempt_payload(
                attempt,
                last_score,
                state_descriptor=descriptor,
                decision_output=plan_output,
                artifacts_regenerated=regenerated,
                validation_stage="decision",
                replan_owner=OWNER_DECISION,
                replan_reason=reason,
            )
            reset_from(OWNER_DECISION, can_retry)
            feedback = reason
            trace.record_attempt(payload)
            continue

        if compiled is None:
            hierarchy_output = trace.call(
                "hierarchy_planner",
                "Checker Jumping dynamic HierarchyPlanner generator.",
                dynamic_hierarchy_prompt(
                    task, task.initial, descriptor, plan_output or "", feedback
                ),
                response_schema=HIERARCHY_SCHEMA,
                schema_name="checker_jumping_hierarchy",
            )
            compiled = compile_hierarchy_output(hierarchy_output, task, decision)
        counters.update(
            {
                "hierarchy_format_valid": compiled.format_valid,
                "hierarchy_graph_valid": compiled.hierarchy_graph_valid,
                "parameter_binding_valid": compiled.parameter_binding_valid,
                "dispatch_valid": compiled.dispatch_valid,
                "hierarchy_useful": compiled.hierarchy_useful,
                "mapping_count_by_level": {
                    str(level): count
                    for level, count in sorted(compiled.mapping_count_by_level.items())
                },
                "function_reuse_counts": dict(sorted(compiled.function_reuse_counts.items())),
                "compression_ratio": compiled.compression_ratio,
            }
        )
        if not compiled.valid:
            counters["format_failure_count"] = int(counters["format_failure_count"]) + int(
                not compiled.format_valid
            )
            counters["hierarchy_failure_count"] = int(counters["hierarchy_failure_count"]) + int(
                not compiled.hierarchy_graph_valid
                or not compiled.dispatch_valid
                or not compiled.hierarchy_useful
            )
            counters["binding_failure_count"] = int(counters["binding_failure_count"]) + int(
                not compiled.parameter_binding_valid
            )
            reason = "; ".join(compiled.errors) or "Hierarchy compiler rejected the output"
            last_score = empty_failure_score(task, reason)
            counters["deterministic_router_count"] = int(counters["deterministic_router_count"]) + 1
            payload = attempt_payload(
                attempt,
                last_score,
                state_descriptor=descriptor,
                decision_output=plan_output,
                hierarchy_output=hierarchy_output,
                artifacts_regenerated=regenerated,
                validation_stage="hierarchy_compiler",
                replan_owner=OWNER_HIERARCHY,
                replan_reason=reason,
            )
            reset_from(OWNER_HIERARCHY, can_retry)
            feedback = reason
            trace.record_attempt(payload)
            continue

        validated = validate_subtasks(
            task,
            compiled.subtasks,
            compiled.mappings,
            [],
            expected_states=[subtask.goal_state for subtask in decision.subtasks],
        )
        top_calls = [call for subtask in compiled.subtasks for call in subtask]
        histogram = hierarchy_histogram(top_calls, compiled.mappings, compiled.levels)
        last_score = score_execution(
            task,
            validated["final_state"],
            validated["moves"],
            legal=bool(validated["legal"]),
            h1_valid=True,
            h2_valid=compiled.max_level >= 2,
            h1_count=histogram.get(1, 0),
            h2_count=histogram.get(2, 0),
            h0_count=len(validated["expanded"]),
            top_level_count=len(top_calls),
            max_hierarchy_level=compiled.max_level,
            level_call_counts=histogram,
            parse_errors=validated["errors"],
            illegal_reason=validated["reason"],
            first_failure_move=validated["failure"],
            high_level_plan=[str(call) for call in top_calls],
            expanded_h0_plan=validated["expanded"],
        )
        summary = validation_summary(last_score, task.goal)
        router_output = trace.call(
            "innerbot_router",
            "Checker Jumping InnerBot router.",
            router_prompt(task, task.initial, plan_output or "", hierarchy_output or "", summary),
        )
        router_ok, owner, router_reason = parse_router_verdict(router_output)
        counters["innerbot_check_count"] = int(counters["innerbot_check_count"]) + 1
        if not router_ok:
            counters["innerbot_rejection_count"] = int(counters["innerbot_rejection_count"]) + 1
        payload = attempt_payload(
            attempt,
            last_score,
            state_descriptor=descriptor,
            decision_output=plan_output,
            hierarchy_output=hierarchy_output,
            artifacts_regenerated=regenerated,
            router_accepted=router_ok,
            router_owner=owner,
            router_reason=router_reason,
        )
        if not last_score.legal or not router_ok:
            counters["planning_failure_count"] = int(counters["planning_failure_count"]) + 1
            if router_ok:
                owner = OWNER_BOTH
                router_reason = last_score.illegal_reason or "Primitive plan was invalid"
            payload.update(
                validation_stage="primitive_execution",
                replan_owner=owner,
                replan_reason=router_reason,
            )
            reset_from(owner, can_retry)
            feedback = router_reason
            trace.record_attempt(payload)
            continue

        outer_ok = True
        outer_results: List[Dict[str, object]] = []
        previous = list(task.initial)
        for index, projected in enumerate(validated["subtask_states"], start=1):
            expected = decision.subtasks[index - 1].goal_state
            accepted, data = verify_outer(
                task,
                trace,
                previous,
                projected,
                expected,
                decision.subtasks[index - 1].objective,
                final=index == len(validated["subtask_states"]),
                counters=counters,
            )
            outer_ok = outer_ok and accepted
            outer_results.append(data)
            previous = list(projected)
        payload["outerbot"] = outer_results
        trace.record_attempt(payload)
        if last_score.solved:
            if not outer_ok:
                counters["verifier_disagreement_count"] = int(
                    counters["verifier_disagreement_count"]
                ) + 1
            counters["verifier_accepted"] = router_ok and outer_ok
            return last_score, counters
        feedback = "Execution was legal but did not reach the exact goal"
        reset_from(OWNER_BOTH, can_retry)
    counters["format_valid"] = bool(
        counters["decision_format_valid"] and counters["hierarchy_format_valid"]
    )
    return last_score, counters


def generate_and_verify_state(
    task: CheckerJumpingTask,
    trace: RunTrace,
    feedback: Optional[str],
) -> Tuple[str, bool, str]:
    descriptor = trace.call(
        "state_descriptor",
        state_descriptor_system_prompt(),
        state_descriptor_prompt(task, task.initial, feedback),
    )
    deterministic_ok, deterministic_reason = validate_descriptor(task, descriptor)
    verdict = trace.call(
        "innerbot_state",
        "Checker Jumping InnerBot state verifier.",
        inner_state_prompt(task, task.initial, descriptor),
    )
    llm_ok, llm_reason = parse_innerbot_verdict(verdict)
    if not deterministic_ok:
        return descriptor, False, deterministic_reason
    if not llm_ok:
        return descriptor, False, llm_reason
    return descriptor, True, "N/A"


def validate_descriptor(
    task: CheckerJumpingTask, descriptor: str
) -> Tuple[bool, str]:
    match = re.search(
        r"```start_flag\s*(.*?)\s*```end_flag", descriptor, flags=re.DOTALL
    )
    if not match:
        return False, "StateDescriptor is missing start_flag/end_flag"
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        return False, f"StateDescriptor JSON is invalid: {exc.msg}"
    if not isinstance(payload, dict):
        return False, "StateDescriptor must be a JSON object"
    if payload.get("board") != task.initial:
        return False, "StateDescriptor board does not match the authoritative board"
    if payload.get("goal") != task.goal:
        return False, "StateDescriptor goal does not match the authoritative goal"
    if payload.get("empty_position") != task.initial.index("_"):
        return False, "StateDescriptor empty_position is incorrect"
    if payload.get("directions") != {"R": "right", "B": "left"}:
        return False, "StateDescriptor movement directions are incorrect"
    constraints = payload.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        return False, "StateDescriptor constraints must be a non-empty array"
    return True, "N/A"


def validate_subtasks(
    task: CheckerJumpingTask,
    subtasks: Sequence[Sequence[FunctionCall]],
    mappings: Dict[str, FunctionMapping],
    initial_errors: Sequence[str],
    expected_states: Optional[Sequence[Sequence[str]]] = None,
) -> Dict[str, object]:
    board = list(task.initial)
    all_moves: List[List[object]] = []
    all_expanded: List[str] = []
    subtask_states: List[List[str]] = []
    errors = list(initial_errors)
    reason: Optional[str] = "; ".join(errors) if errors else None
    failure: Optional[int] = None
    if errors:
        return {
            "legal": False,
            "reason": reason,
            "failure": failure,
            "final_state": board,
            "moves": all_moves,
            "expanded": all_expanded,
            "subtask_states": subtask_states,
            "errors": errors,
        }
    for index, calls in enumerate(subtasks, start=1):
        expanded, expansion_errors = expand_calls(calls, mappings)
        if expansion_errors:
            errors.extend(f"Subtask {index}: {message}" for message in expansion_errors)
            reason = "; ".join(errors)
            break
        legal, local_reason, local_failure, next_board, moves = simulate_calls(
            task, expanded, board
        )
        all_expanded.extend(str(call) for call in expanded)
        if not legal:
            failure = len(all_moves) + int(local_failure or 1)
            reason = local_reason
            break
        all_moves.extend(moves)
        board = next_board
        subtask_states.append(list(board))
        if expected_states is not None and board != list(expected_states[index - 1]):
            reason = (
                f"Subtask {index} reached {board}, not declared goal "
                f"{list(expected_states[index - 1])}"
            )
            errors.append(reason)
            break
    legal = reason is None
    return {
        "legal": legal,
        "reason": reason,
        "failure": failure,
        "final_state": board,
        "moves": all_moves,
        "expanded": all_expanded,
        "subtask_states": subtask_states,
        "errors": errors,
    }


def verify_outer(
    task: CheckerJumpingTask,
    trace: RunTrace,
    before: List[str],
    after: List[str],
    expected: List[str],
    requirement: str,
    *,
    final: bool,
    counters: Dict[str, object],
) -> Tuple[bool, Dict[str, object]]:
    output = trace.call(
        "outerbot",
        "Checker Jumping OuterBot execution-state verifier.",
        outer_prompt(task, before, after, expected, requirement),
    )
    status, reason = parse_outerbot_verdict(output)
    counters["outerbot_check_count"] = int(counters["outerbot_check_count"]) + 1
    allowed = {"TASK SUCCESS"} if final else {"SUBTASK SUCCESS", "EXECUTE REMAINING ACTIONS"}
    return status in allowed, {"status": status, "reason": reason, "output": output}


def validation_summary(score: CheckerJumpingScore, expected: Sequence[str]) -> str:
    return json.dumps(
        {
            "format_valid": not bool(score.parse_errors),
            "primitive_plan_legal": score.legal,
            "illegal_reason": score.illegal_reason,
            "first_failure_move": score.first_failure_move,
            "final_state": score.final_state,
            "expected_state": list(expected),
            "goal_reached": score.solved,
        },
        sort_keys=True,
    )


def verifier_metrics() -> Dict[str, object]:
    return {
        "verifier_mode": "llm",
        "innerbot_check_count": 0,
        "innerbot_rejection_count": 0,
        "outerbot_check_count": 0,
        "verifier_disagreement_count": 0,
    }


def empty_failure_score(
    task: CheckerJumpingTask, reason: str
) -> CheckerJumpingScore:
    return score_execution(
        task,
        task.initial,
        [],
        legal=False,
        parse_errors=[reason],
        illegal_reason=reason,
    )


def attempt_payload(
    attempt: int, score: CheckerJumpingScore, **extra: object
) -> Dict[str, object]:
    return {
        "attempt": attempt,
        "solved": score.solved,
        "legal": score.legal,
        "move_count": score.move_count,
        "first_failure_move": score.first_failure_move,
        "illegal_reason": score.illegal_reason,
        "parse_errors": score.parse_errors,
        **extra,
    }


def make_result_dir(root: Path, model: str, mode: str, task_id: str) -> Path:
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", model)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = root / safe_model / mode / f"{task_id}_{stamp}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_json(path: Path, payload: Dict[str, object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
