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

from blocks_world_prompts import (
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
)
from blocks_world_scoring import (
    BlocksWorldScore,
    FunctionCall,
    FunctionMapping,
    copy_state,
    expand_calls,
    fixed_call_counts,
    hierarchy_histogram,
    parse_direct_plan,
    parse_mappings,
    parse_subtask_plans,
    score_execution,
    simulate_calls,
    validate_fixed_h2,
    validate_h1,
)
from blocks_world_structured import (
    DECISION_SCHEMA,
    HIERARCHY_SCHEMA,
    DecisionParseResult,
    HierarchyCompileResult,
    compile_hierarchy_output,
    parse_decision_output,
)
from blocks_world_task import BlocksWorldTask, available_tasks, load_task
from dynamic_scoring import (
    OWNER_BOTH,
    OWNER_DECISION,
    OWNER_HIERARCHY,
    parse_router_verdict,
)
from hanoi_benchmark import (
    aggregate_token_usage,
    parse_innerbot_verdict,
    parse_outerbot_verdict,
)
from models import create_client, load_env_file
from scoring import extract_between_flags


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
        elapsed = time.perf_counter() - started
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
                "runtime_seconds": round(elapsed, 6),
            }
        )
        return output

    def record_attempt(self, payload: Dict[str, object]) -> None:
        self.attempts.append(payload)
        self.events.append({"event": "attempt_result", **payload})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run paper-style symbolic Blocks World planning benchmarks."
    )
    parser.add_argument(
        "--task",
        default="blocks_world_4",
        help="Task id, such as blocks_world_4, or 'all'.",
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
        help="Model provider. Defaults to DEFAULT_PROVIDER, then openai.",
    )
    parser.add_argument("--model", default=None, help="Provider model id.")
    parser.add_argument("--base-url", default=None, help="Override the provider endpoint.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Path to the key file.")
    parser.add_argument(
        "--reasoning",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
        default=None,
        help="Provider reasoning effort. Explicitly recorded in every result.",
    )
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument(
        "--max-replans",
        type=int,
        default=2,
        help="Additional attempts after the first rejected plan.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Sampling temperature for local/openai-compatible providers. Defaults to 0 (or LOCAL_TEMPERATURE from .env).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    provider = args.provider or os.environ.get("DEFAULT_PROVIDER") or "openai"
    model = args.model or os.environ.get("DEFAULT_MODEL") or "gpt-5.6-luna"
    reasoning = args.reasoning or os.environ.get("DEFAULT_REASONING_EFFORT")
    client = create_client(provider, model, args.base_url, reasoning, temperature=args.temperature)

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
    task: BlocksWorldTask,
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

    elapsed = time.perf_counter() - timer
    call_records = client.call_records_since(call_start)
    token_usage = aggregate_token_usage(call_records)
    score_data = score.as_dict()
    model_name = str(getattr(client, "model", "unknown"))
    provider = str(getattr(client, "provider", "unknown"))
    output_dir = make_result_dir(results_dir, model_name, mode, task.id)
    if mode == "complete-framework":
        run_metrics["format_valid"] = bool(
            run_metrics.get("decision_format_valid")
            and run_metrics.get("hierarchy_format_valid")
        )
    else:
        run_metrics.setdefault("format_valid", not bool(score.parse_errors))
    run_metrics.setdefault("hierarchy_graph_valid", None)
    run_metrics.setdefault("parameter_binding_valid", None)
    run_metrics.setdefault("verifier_accepted", None if mode == "no-framework" else score.solved)
    run_metrics["primitive_plan_legal"] = score.legal
    run_metrics["goal_reached"] = score.solved

    metrics: Dict[str, object] = {
        "benchmark": "blocks_world",
        "benchmark_version": 2,
        "task_id": task.id,
        "block_count": task.block_count,
        "stack_count": len(task.stack_ids),
        "mode": mode,
        "provider": provider,
        "model": model_name,
        "reasoning_effort": reasoning_effort,
        "started_at": started_at.isoformat(),
        "runtime_seconds": round(elapsed, 6),
        "attempt_count": len(trace.attempts),
        "replan_count": max(0, len(trace.attempts) - 1),
        "model_call_count": len(call_records),
        "model_calls_by_stage": dict(sorted(trace.stage_counts.items())),
        **score_data,
        **run_metrics,
        "token_usage": token_usage,
    }
    steps = {
        "task_id": task.id,
        "mode": mode,
        "stack_order": "bottom_to_top",
        "initial_state": task.initial,
        "goal_state": task.goal,
        "attempts": trace.attempts,
        "high_level_plan": score.high_level_plan,
        "expanded_h0_plan": score.expanded_h0_plan,
        "blocks_world_moves": score.moves,
        "final_state": score.final_state,
    }
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "steps.json", steps)
    with (output_dir / "raw_log.jsonl").open("w", encoding="utf-8") as handle:
        for event in trace.events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    metrics["result_dir"] = str(output_dir)
    return metrics


def run_direct(task: BlocksWorldTask, trace: RunTrace) -> Tuple[BlocksWorldScore, Dict[str, object]]:
    trace.current_attempt = 1
    output = trace.call(
        "direct",
        direct_system_prompt(),
        direct_prompt(task, task.initial),
    )
    calls, parse_errors = parse_direct_plan(output)
    legal, reason, failure, final_state, moves = simulate_calls(task, calls)
    if parse_errors:
        legal = False
        reason = "; ".join(parse_errors)
    score = score_execution(
        task,
        final_state,
        moves,
        legal=legal,
        top_level_count=len(calls),
        parse_errors=parse_errors,
        illegal_reason=reason,
        first_failure_move=failure,
        high_level_plan=[str(call) for call in calls],
        expanded_h0_plan=[str(call) for call in calls],
    )
    trace.record_attempt(attempt_payload(1, score, output=output))
    metrics: Dict[str, object] = verifier_metrics()
    metrics["format_valid"] = not parse_errors
    metrics["verifier_accepted"] = None
    return score, metrics


def run_inner_outer(
    task: BlocksWorldTask, trace: RunTrace, max_replans: int
) -> Tuple[BlocksWorldScore, Dict[str, object]]:
    counters = verifier_metrics()
    feedback: Optional[str] = None
    last_score = empty_failure_score(task, "No plan attempt was made")
    for attempt in range(1, max_replans + 2):
        trace.current_attempt = attempt
        output = trace.call(
            "direct",
            direct_system_prompt(),
            direct_prompt(task, task.initial, feedback),
        )
        calls, parse_errors = parse_direct_plan(output)
        counters["format_valid"] = not parse_errors
        legal, reason, failure, final_state, moves = simulate_calls(task, calls)
        if parse_errors:
            legal = False
            reason = "; ".join(parse_errors)
        summary = validation_summary(legal, reason, final_state, task.goal)
        verdict_output = trace.call(
            "innerbot_plan",
            "Blocks World InnerBot plan verifier.",
            inner_plan_prompt(task, task.initial, output, summary),
        )
        inner_ok, inner_reason = parse_innerbot_verdict(verdict_output)
        counters["innerbot_check_count"] += 1
        if not inner_ok:
            counters["innerbot_rejection_count"] += 1

        last_score = score_execution(
            task,
            final_state,
            moves,
            legal=legal,
            top_level_count=len(calls),
            parse_errors=parse_errors,
            illegal_reason=reason,
            first_failure_move=failure,
            high_level_plan=[str(call) for call in calls],
            expanded_h0_plan=[str(call) for call in calls],
        )
        attempt_data = attempt_payload(
            attempt,
            last_score,
            output=output,
            innerbot_accepted=inner_ok,
            innerbot_reason=inner_reason,
        )
        if not legal or not inner_ok:
            feedback = reason if not legal else inner_reason
            attempt_data["replan_reason"] = feedback
            trace.record_attempt(attempt_data)
            continue

        outer_output = trace.call(
            "outerbot",
            "Blocks World OuterBot execution-state verifier.",
            outer_prompt(task, task.initial, final_state, task.goal, "Solve the full task"),
        )
        outer_status, outer_reason = parse_outerbot_verdict(outer_output)
        counters["outerbot_check_count"] += 1
        attempt_data.update({"outerbot_status": outer_status, "outerbot_reason": outer_reason})
        if last_score.solved:
            if outer_status != "TASK SUCCESS":
                counters["verifier_disagreement_count"] += 1
            counters["verifier_accepted"] = inner_ok and outer_status == "TASK SUCCESS"
            trace.record_attempt(attempt_data)
            return last_score, counters
        feedback = outer_reason if outer_status in {"RECOVERABLE", "NON-RECOVERABLE"} else "Final state did not equal the goal"
        attempt_data["replan_reason"] = feedback
        trace.record_attempt(attempt_data)
        if outer_status == "NON-RECOVERABLE":
            break
    return last_score, counters


def run_fixed_hierarchy(
    task: BlocksWorldTask, trace: RunTrace, max_replans: int
) -> Tuple[BlocksWorldScore, Dict[str, object]]:
    counters = verifier_metrics()
    feedback: Optional[str] = None
    last_score = empty_failure_score(task, "No hierarchy attempt was made")
    for attempt in range(1, max_replans + 2):
        trace.current_attempt = attempt
        descriptor, descriptor_ok, descriptor_reason = generate_and_verify_state(task, trace, feedback)
        counters["innerbot_check_count"] += 1
        if not descriptor_ok:
            counters["innerbot_rejection_count"] += 1
            feedback = descriptor_reason
            last_score = empty_failure_score(task, descriptor_reason)
            trace.record_attempt(attempt_payload(attempt, last_score, replan_reason=feedback))
            continue

        h1_output = trace.call(
            "h1",
            "Blocks World H1 action generator.",
            h1_prompt(task, descriptor),
        )
        h1_mappings, h1_errors = parse_mappings(h1_output)
        h1_valid, h1_reason = validate_h1(h1_mappings)
        h2_output = trace.call(
            "h2",
            "Blocks World H2 action generator.",
            h2_prompt(task, task.initial, descriptor, h1_output, feedback),
        )
        h2_mappings, h2_errors = parse_mappings(h2_output)
        h2_valid, h2_reason = validate_fixed_h2(h2_mappings, h1_mappings)
        decision_output = trace.call(
            "decision",
            "Blocks World DecisionBot fixed hierarchy planner.",
            fixed_decision_prompt(
                task, task.initial, descriptor, h1_output, h2_output, feedback
            ),
        )
        subtasks, plan_errors = parse_subtask_plans(decision_output)
        mappings = {**h1_mappings, **h2_mappings}
        all_calls = [call for subtask in subtasks for call in subtask]
        structure_errors = [*h1_errors, *h2_errors, *plan_errors]
        counters["format_valid"] = not (h1_errors or h2_errors or plan_errors)
        counters["hierarchy_graph_valid"] = h1_valid and h2_valid
        counters["parameter_binding_valid"] = h1_valid and h2_valid
        if not h1_valid:
            structure_errors.append(h1_reason)
        if not h2_valid:
            structure_errors.append(h2_reason)
        for call in all_calls:
            if call.name not in h2_mappings:
                structure_errors.append(f"DecisionBot called non-H2 function {call.name}")
        validated = validate_subtasks(task, task.initial, subtasks, mappings, structure_errors)
        h1_count, h2_count = fixed_call_counts(all_calls, h1_mappings, h2_mappings)
        last_score = score_execution(
            task,
            validated["final_state"],
            validated["moves"],
            legal=bool(validated["legal"]),
            h1_valid=h1_valid,
            h2_valid=h2_valid,
            h1_count=h1_count,
            h2_count=h2_count,
            top_level_count=len(all_calls),
            max_hierarchy_level=2 if h1_valid and h2_valid else 0,
            level_call_counts={1: h1_count, 2: h2_count},
            parse_errors=list(validated["errors"]),
            illegal_reason=validated["reason"],
            first_failure_move=validated["failure"],
            high_level_plan=[str(call) for call in all_calls],
            expanded_h0_plan=list(validated["expanded"]),
        )
        summary = validation_summary(
            bool(validated["legal"]), validated["reason"], validated["final_state"], task.goal
        )
        inner_output = trace.call(
            "innerbot_plan",
            "Blocks World InnerBot plan verifier.",
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
        attempt_data = attempt_payload(
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
            feedback = validated["reason"] if not last_score.legal else inner_reason
            attempt_data["replan_reason"] = feedback
            trace.record_attempt(attempt_data)
            continue
        outer_ok, outer_data = verify_execution(task, trace, validated, counters)
        attempt_data["outerbot"] = outer_data
        trace.record_attempt(attempt_data)
        if last_score.solved:
            if not outer_ok:
                counters["verifier_disagreement_count"] += 1
            counters["verifier_accepted"] = inner_ok and outer_ok
            return last_score, counters
        feedback = "Execution was legal but did not reach the exact goal"
    return last_score, counters


def run_complete_framework(
    task: BlocksWorldTask, trace: RunTrace, max_replans: int
) -> Tuple[BlocksWorldScore, Dict[str, object]]:
    counters: Dict[str, object] = {
        **verifier_metrics(),
        "architecture_version": "blocks_world_nlevel_v2",
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
        "stage_replan_counts": {
            "state_descriptor": 0,
            "decision": 0,
            "hierarchy": 0,
        },
        "artifact_reuse_counts": {
            "state_descriptor": 0,
            "decision": 0,
        },
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

    def increment_nested(group: str, key: str) -> None:
        values = counters[group]
        assert isinstance(values, dict)
        values[key] = int(values.get(key, 0)) + 1

    def route(owner: str, can_retry: bool) -> None:
        nonlocal plan_output, decision, hierarchy_output, compiled
        canonical = owner if owner in {OWNER_DECISION, OWNER_HIERARCHY, OWNER_BOTH} else OWNER_BOTH
        increment_nested("router_attribution_counts", canonical)
        if can_retry:
            stage = "hierarchy" if canonical == OWNER_HIERARCHY else "decision"
            increment_nested("stage_replan_counts", stage)
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
            increment_nested("artifact_reuse_counts", "state_descriptor")
        if decision is not None:
            increment_nested("artifact_reuse_counts", "decision")

        if descriptor is None:
            descriptor, descriptor_ok, descriptor_reason = generate_and_verify_state(
                task, trace, feedback
            )
            counters["innerbot_check_count"] = int(counters["innerbot_check_count"]) + 1
            if not descriptor_ok:
                counters["innerbot_rejection_count"] = int(counters["innerbot_rejection_count"]) + 1
                if can_retry:
                    increment_nested("stage_replan_counts", "state_descriptor")
                feedback = descriptor_reason
                last_score = empty_failure_score(task, descriptor_reason)
                trace.record_attempt(
                    attempt_payload(
                        attempt,
                        last_score,
                        artifacts_regenerated=regenerated,
                        validation_stage="state_descriptor",
                        replan_owner="state_descriptor",
                        replan_reason=feedback,
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
                "Blocks World DecisionBot plan-only planner.",
                plan_only_prompt(task, task.initial, descriptor, feedback),
                response_schema=DECISION_SCHEMA,
                schema_name="blocks_world_decision",
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
            attempt_data = attempt_payload(
                attempt,
                last_score,
                state_descriptor=descriptor,
                decision_output=plan_output,
                artifacts_regenerated=regenerated,
                decision_validation=decision_validation_payload(decision),
                validation_stage="decision",
                replan_owner=OWNER_DECISION,
                replan_reason=reason,
            )
            counters["deterministic_router_count"] = int(counters["deterministic_router_count"]) + 1
            route(OWNER_DECISION, can_retry)
            feedback = reason
            trace.record_attempt(attempt_data)
            continue

        if compiled is None:
            hierarchy_output = trace.call(
                "hierarchy_planner",
                "Blocks World dynamic HierarchyPlanner generator.",
                dynamic_hierarchy_prompt(
                    task, task.initial, descriptor, plan_output or "", feedback
                ),
                response_schema=HIERARCHY_SCHEMA,
                schema_name="blocks_world_hierarchy",
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
            attempt_data = attempt_payload(
                attempt,
                last_score,
                state_descriptor=descriptor,
                decision_output=plan_output,
                hierarchy_output=hierarchy_output,
                artifacts_regenerated=regenerated,
                decision_validation=decision_validation_payload(decision),
                hierarchy_validation=hierarchy_validation_payload(compiled),
                validation_stage="hierarchy_compiler",
                replan_owner=OWNER_HIERARCHY,
                replan_reason=reason,
            )
            counters["deterministic_router_count"] = int(counters["deterministic_router_count"]) + 1
            route(OWNER_HIERARCHY, can_retry)
            feedback = reason
            trace.record_attempt(attempt_data)
            continue

        expected_states = [subtask.goal_state for subtask in decision.subtasks]
        validated = validate_subtasks(
            task,
            task.initial,
            compiled.subtasks,
            compiled.mappings,
            [],
            expected_states=expected_states,
        )
        all_calls = [call for subtask in compiled.subtasks for call in subtask]
        histogram = hierarchy_histogram(all_calls, compiled.mappings, compiled.levels)
        h1_count = histogram.get(1, 0)
        h2_count = sum(count for level, count in histogram.items() if level >= 2)
        last_score = score_execution(
            task,
            validated["final_state"],
            validated["moves"],
            legal=bool(validated["legal"]),
            h1_valid=True,
            h2_valid=True,
            h1_count=h1_count,
            h2_count=h2_count,
            top_level_count=len(all_calls),
            max_hierarchy_level=compiled.max_level,
            level_call_counts=histogram,
            parse_errors=list(validated["errors"]),
            illegal_reason=validated["reason"],
            first_failure_move=validated["failure"],
            high_level_plan=[str(call) for call in all_calls],
            expanded_h0_plan=list(validated["expanded"]),
        )
        attempt_data = attempt_payload(
            attempt,
            last_score,
            state_descriptor=descriptor,
            decision_output=plan_output,
            hierarchy_output=hierarchy_output,
            artifacts_regenerated=regenerated,
            decision_validation=decision_validation_payload(decision),
            hierarchy_validation=hierarchy_validation_payload(compiled),
        )
        if not last_score.legal:
            counters["planning_failure_count"] = int(counters["planning_failure_count"]) + 1
            counters["deterministic_router_count"] = int(counters["deterministic_router_count"]) + 1
            reason = str(validated["reason"] or "Primitive plan was illegal")
            attempt_data.update(
                {
                    "validation_stage": "primitive_execution",
                    "replan_owner": OWNER_HIERARCHY,
                    "replan_reason": reason,
                }
            )
            route(OWNER_HIERARCHY, can_retry)
            feedback = reason
            trace.record_attempt(attempt_data)
            continue

        summary = validation_summary(True, None, validated["final_state"], task.goal)
        router_output = trace.call(
            "innerbot_router",
            "Blocks World InnerBot router for DecisionBot and HierarchyPlanner outputs.",
            router_prompt(task, task.initial, plan_output or "", hierarchy_output or "", summary),
        )
        router_ok, owner, router_reason = parse_router_verdict(router_output)
        counters["innerbot_check_count"] = int(counters["innerbot_check_count"]) + 1
        counters["router_check_count"] = int(counters["router_check_count"]) + 1
        counters["verifier_accepted"] = router_ok
        attempt_data.update(
            {
                "router_accepted": router_ok,
                "router_owner": owner,
                "router_reason": router_reason,
            }
        )
        if not router_ok:
            counters["innerbot_rejection_count"] = int(counters["innerbot_rejection_count"]) + 1
            counters["router_rejection_count"] = int(counters["router_rejection_count"]) + 1
            route(owner, can_retry)
            feedback = router_reason
            attempt_data["replan_reason"] = feedback
            trace.record_attempt(attempt_data)
            continue

        outer_plan = [
            {"description": subtask.objective, "goal_state": subtask.goal_state}
            for subtask in decision.subtasks
        ]
        outer_ok, outer_data = verify_execution(task, trace, validated, counters, outer_plan)
        counters["verifier_accepted"] = router_ok and outer_ok
        attempt_data["outerbot"] = outer_data
        trace.record_attempt(attempt_data)
        if last_score.solved:
            if not outer_ok:
                counters["verifier_disagreement_count"] = int(
                    counters["verifier_disagreement_count"]
                ) + 1
            return last_score, counters

        counters["planning_failure_count"] = int(counters["planning_failure_count"]) + 1
        feedback = "Execution was legal but did not reach the exact goal"
        route(OWNER_BOTH, can_retry)
    return last_score, counters


def generate_and_verify_state(
    task: BlocksWorldTask, trace: RunTrace, feedback: Optional[str]
) -> Tuple[str, bool, str]:
    descriptor = trace.call(
        "state_descriptor",
        "Blocks World StateDescriptor generator.",
        state_descriptor_prompt(task, task.initial, feedback),
    )
    descriptor_valid, deterministic_reason = validate_descriptor(task, descriptor)
    verifier_output = trace.call(
        "innerbot_state",
        "Blocks World InnerBot state verifier.",
        inner_state_prompt(task, task.initial, descriptor),
    )
    verifier_ok, verifier_reason = parse_innerbot_verdict(verifier_output)
    if not descriptor_valid:
        return descriptor, False, deterministic_reason
    if not verifier_ok:
        return descriptor, False, verifier_reason
    return descriptor, True, "N/A"


def validate_descriptor(task: BlocksWorldTask, output: str) -> Tuple[bool, str]:
    body = extract_between_flags(output, "```start_flag", "```end_flag")
    if body is None:
        match = re.search(
            r"(?:```)?start_flag\s*(.*?)\s*(?:```)?end_flag",
            output,
            flags=re.DOTALL | re.IGNORECASE,
        )
        body = match.group(1).strip() if match else output
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return False, f"StateDescriptor is not valid JSON: {exc.msg}"
    if payload.get("stack_order") != "bottom_to_top":
        return False, "StateDescriptor stack_order must be bottom_to_top"
    if payload.get("current") != task.initial:
        return False, "StateDescriptor current state does not match the environment"
    if payload.get("goal") != task.goal:
        return False, "StateDescriptor goal does not match the task"
    return True, "N/A"


def validate_subtasks(
    task: BlocksWorldTask,
    initial_state: Dict[str, List[str]],
    subtasks: Sequence[Sequence[FunctionCall]],
    mappings: Dict[str, FunctionMapping],
    initial_errors: Sequence[str],
    expected_states: Optional[Sequence[Dict[str, List[str]]]] = None,
) -> Dict[str, object]:
    errors = list(dict.fromkeys(error for error in initial_errors if error and error != "N/A"))
    state = copy_state(initial_state)
    all_moves: List[Tuple[str, str, str]] = []
    expanded_strings: List[str] = []
    projected_states: List[Dict[str, List[str]]] = []
    expanded_subtasks: List[List[FunctionCall]] = []
    failure: Optional[int] = None
    reason: Optional[str] = None

    for index, calls in enumerate(subtasks):
        expanded, expand_errors = expand_calls(calls, mappings)
        errors.extend(expand_errors)
        expanded_subtasks.append(expanded)
        expanded_strings.extend(str(call) for call in expanded)
        legal, move_reason, local_failure, projected, moves = simulate_calls(
            task, expanded, state
        )
        if not legal:
            reason = move_reason
            failure = len(all_moves) + (local_failure or 1)
            errors.append(move_reason or "Illegal primitive move")
            state = projected
            all_moves.extend(moves)
            break
        state = projected
        all_moves.extend(moves)
        projected_states.append(copy_state(state))
        if expected_states is not None and index < len(expected_states):
            if state != expected_states[index]:
                errors.append(
                    f"Subtask {index + 1} projected state does not match its declared goal state"
                )

    if errors and reason is None:
        reason = "; ".join(dict.fromkeys(errors))
    return {
        "legal": not errors,
        "reason": reason,
        "failure": failure,
        "final_state": state,
        "moves": all_moves,
        "expanded": expanded_strings,
        "expanded_subtasks": expanded_subtasks,
        "projected_states": projected_states,
        "errors": list(dict.fromkeys(errors)),
    }


def hierarchy_validation_payload(compiled: HierarchyCompileResult) -> Dict[str, object]:
    return {
        "format_valid": compiled.format_valid,
        "hierarchy_graph_valid": compiled.hierarchy_graph_valid,
        "parameter_binding_valid": compiled.parameter_binding_valid,
        "dispatch_valid": compiled.dispatch_valid,
        "hierarchy_useful": compiled.hierarchy_useful,
        "max_level": compiled.max_level,
        "mapping_count_by_level": {
            str(level): count
            for level, count in sorted(compiled.mapping_count_by_level.items())
        },
        "function_reuse_counts": dict(sorted(compiled.function_reuse_counts.items())),
        "compression_ratio": compiled.compression_ratio,
        "errors": compiled.errors,
    }


def decision_validation_payload(decision: DecisionParseResult) -> Dict[str, object]:
    return {
        "format_valid": decision.format_valid,
        "semantic_valid": decision.semantic_valid,
        "format_errors": decision.format_errors,
        "semantic_errors": decision.semantic_errors,
        "errors": decision.errors,
    }


def verify_execution(
    task: BlocksWorldTask,
    trace: RunTrace,
    validated: Dict[str, object],
    counters: Dict[str, object],
    plan_subtasks: Optional[Sequence[Dict[str, object]]] = None,
) -> Tuple[bool, List[Dict[str, str]]]:
    state = copy_state(task.initial)
    outcomes: List[Dict[str, str]] = []
    all_ok = True
    expanded_subtasks = validated["expanded_subtasks"]
    projected_states = validated["projected_states"]
    for index, calls in enumerate(expanded_subtasks):
        previous = copy_state(state)
        _, _, _, state, _ = simulate_calls(task, calls, state)
        expected = projected_states[index]
        requirement = (
            str(plan_subtasks[index].get("description") or f"Execute subtask {index + 1}")
            if plan_subtasks and index < len(plan_subtasks)
            else f"Execute hierarchy subtask {index + 1}"
        )
        output = trace.call(
            "outerbot",
            "Blocks World OuterBot execution-state verifier.",
            outer_prompt(task, previous, state, expected, requirement),
        )
        status, reason = parse_outerbot_verdict(output)
        counters["outerbot_check_count"] += 1
        expected_statuses = {"TASK SUCCESS"} if state == task.goal else {
            "SUBTASK SUCCESS",
            "EXECUTE REMAINING ACTIONS",
        }
        if status not in expected_statuses:
            all_ok = False
        outcomes.append({"status": status, "reason": reason})
    return all_ok, outcomes


def validation_summary(
    legal: bool,
    reason: Optional[str],
    final_state: Dict[str, List[str]],
    goal: Dict[str, List[str]],
) -> str:
    return json.dumps(
        {
            "legal": legal,
            "reason": reason or "N/A",
            "final_state": final_state,
            "exact_goal_reached": legal and final_state == goal,
        },
        indent=2,
        sort_keys=True,
    )


def verifier_metrics() -> Dict[str, object]:
    return {
        "innerbot_check_count": 0,
        "innerbot_rejection_count": 0,
        "outerbot_check_count": 0,
        "router_check_count": 0,
        "router_rejection_count": 0,
        "verifier_disagreement_count": 0,
    }


def empty_failure_score(task: BlocksWorldTask, reason: str) -> BlocksWorldScore:
    return score_execution(
        task,
        copy_state(task.initial),
        [],
        legal=False,
        parse_errors=[reason],
        illegal_reason=reason,
    )


def attempt_payload(
    attempt: int, score: BlocksWorldScore, **extra: object
) -> Dict[str, object]:
    return {
        "attempt": attempt,
        "solved": score.solved,
        "legal": score.legal,
        "move_count": score.move_count,
        "illegal_reason": score.illegal_reason,
        "moves": score.moves,
        **extra,
    }


def make_result_dir(root: Path, model: str, mode: str, task_id: str) -> Path:
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", model)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = root / safe_model / mode / f"{task_id}_{stamp}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
