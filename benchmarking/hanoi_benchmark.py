from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models import create_client, load_env_file
from prompts import (
    build_decision_prompt,
    build_direct_hanoi_prompt,
    build_goal_description,
    build_h1_prompt,
    build_h2_prompt,
    build_innerbot_direct_plan_prompt,
    build_innerbot_plan_prompt,
    build_innerbot_state_prompt,
    build_outerbot_prompt,
    build_scene_description,
    build_state_prompt,
    as_json,
)
from scoring import (
    all_h2_calls_known,
    apply_hanoi_move,
    count_hierarchy_calls,
    direct_moves_from_calls,
    expand_calls,
    extract_between_flags,
    extract_moves_from_h0,
    has_valid_h1_move_mapping,
    parse_mappings,
    parse_plan,
    parse_subtask_plans,
    PRIMITIVES,
    score_direct_output,
    score_from_execution,
)
from task_loader import available_tasks, load_task


BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = BENCHMARK_DIR / ".env"
RESULTS_DIR = BENCHMARK_DIR / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run JSON-based Tower of Hanoi planning benchmarks.")
    parser.add_argument(
        "--task",
        default="hanoi_3",
        help="Task id to run, or 'all'. Available: " + ", ".join(available_tasks()),
    )
    parser.add_argument(
        "--provider",
        default=None,
        choices=["mock", "openai", "anthropic", "gemini", "local", "openai-compatible"],
        help="Model provider. Defaults to DEFAULT_PROVIDER from .env, then mock.",
    )
    parser.add_argument("--model", default=None, help="Model name for the selected provider.")
    parser.add_argument("--base-url", default=None, help="Override provider base URL.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Path to .env file.")
    parser.add_argument(
        "--reasoning",
        choices=["low", "medium", "high"],
        default=None,
        help=(
            "Reasoning effort for supported providers. Currently sent as OpenAI reasoning_effort; "
            "recorded in metrics for other providers."
        ),
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Sampling temperature for local/openai-compatible providers. Defaults to 0 (or LOCAL_TEMPERATURE from .env).",
    )
    parser.add_argument(
        "--fixed-goal",
        action="store_true",
        help="Use deterministic goal JSON instead of asking the model to generate the StateDescriptor output.",
    )
    parser.add_argument(
        "--no-framework",
        action="store_true",
        help="Disable the HierarchicalRM-style State/H1/H2/Decision flow and ask the model for direct Hanoi moves.",
    )
    parser.add_argument(
        "--inner-outer",
        action="store_true",
        help=(
            "With --no-framework, run the direct MoveHoop planner inside InnerBot/OuterBot "
            "checks and replanning, but do not generate H1/H2 hierarchy."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional aggregate JSONL result path. By default, each run folder gets raw_log.jsonl and no root JSONL is written.",
    )
    parser.add_argument("--max-tokens", type=int, default=8192, help="Max output tokens per model call.")
    parser.add_argument(
        "--max-replans",
        type=int,
        default=15,
        help="Maximum symbolic replans in hierarchy mode. Matches the Unity default budget.",
    )
    args = parser.parse_args()
    if args.inner_outer and not args.no_framework:
        parser.error("--inner-outer is the middle condition and must be used with --no-framework. Full hierarchy mode already includes InnerBot/OuterBot checks.")
    return args


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))

    provider = args.provider or os.environ.get("DEFAULT_PROVIDER") or "mock"
    model = args.model or os.environ.get("DEFAULT_MODEL")
    reasoning_effort = args.reasoning or os.environ.get("DEFAULT_REASONING_EFFORT")
    client = create_client(
        provider=provider,
        model=model,
        base_url=args.base_url,
        reasoning_effort=reasoning_effort,
        temperature=args.temperature,
    )

    task_ids = available_tasks() if args.task == "all" else [args.task]
    output_path = Path(args.output) if args.output else None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, object]] = []
    aggregate_handle = output_path.open("w", encoding="utf-8") if output_path is not None else None
    try:
        for task_id in task_ids:
            row = run_task(
                task_id,
                client,
                fixed_goal=args.fixed_goal,
                max_tokens=args.max_tokens,
                use_framework=not args.no_framework,
                use_inner_outer=args.inner_outer,
                max_replans=args.max_replans,
                reasoning_effort=reasoning_effort,
            )
            rows.append(row)
            if aggregate_handle is not None:
                aggregate_handle.write(json.dumps(row, sort_keys=True) + "\n")
                aggregate_handle.flush()
    finally:
        if aggregate_handle is not None:
            aggregate_handle.close()

    print_summary(rows, output_path)
    return 0


def run_task(
    task_id: str,
    client,
    fixed_goal: bool,
    max_tokens: int,
    use_framework: bool,
    use_inner_outer: bool,
    max_replans: int,
    reasoning_effort: Optional[str],
) -> Dict[str, object]:
    call_start = len(getattr(client, "call_history", []))
    started_at = time.time()
    timer_start = time.perf_counter()
    model_call_count = 0
    task = load_task(task_id)
    scene_json = build_scene_description(task)

    if not use_framework and not use_inner_outer:
        model_call_count += 1
        direct_output = client.generate(
            system="DirectHanoiAgent: solve the task directly with raw MoveHoop calls.",
            prompt=build_direct_hanoi_prompt(task),
            max_tokens=max_tokens,
        )
        score = score_direct_output(task, direct_output)
        row = {
            "task": task.id,
            "provider": client.provider,
            "model": client.model,
            "mode": "not-hierarchy",
            "verifier_mode": "none",
            "reasoning_effort": reasoning_effort,
            "fixed_goal": fixed_goal,
            "replan_count": 0,
            "termination_reason": "single_direct_call",
            "stage_counts": {
                "direct_model_call_count": 1,
                "scene_descriptor_count": 1,
            },
            "score": score.as_dict(),
            "outputs": {
                "scene_json": scene_json,
                "direct_output": direct_output,
            },
        }
        return finalize_row(row, model_call_count, started_at, timer_start, client.call_records_since(call_start))

    if not use_framework and use_inner_outer:
        inner_outer_result = run_inner_outer_loop(
            task=task,
            client=client,
            max_tokens=max_tokens,
            max_replans=max_replans,
        )
        model_call_count += inner_outer_result["model_call_count"]
        row = {
            "task": task.id,
            "provider": client.provider,
            "model": client.model,
            "mode": "inner-outer",
            "verifier_mode": inner_outer_result["verifier_mode"],
            "reasoning_effort": reasoning_effort,
            "fixed_goal": fixed_goal,
            "replan_count": inner_outer_result["replan_count"],
            "termination_reason": inner_outer_result["termination_reason"],
            "stage_counts": inner_outer_result["stage_counts"],
            "score": inner_outer_result["score"].as_dict(),
            "outputs": inner_outer_result["outputs"],
            "attempts": inner_outer_result["attempts"],
        }
        return finalize_row(row, model_call_count, started_at, timer_start, client.call_records_since(call_start))

    framework_result = run_hierarchy_loop(
        task=task,
        client=client,
        fixed_goal=fixed_goal,
        max_tokens=max_tokens,
        max_replans=max_replans,
    )
    model_call_count += framework_result["model_call_count"]
    row = {
        "task": task.id,
        "provider": client.provider,
        "model": client.model,
        "mode": "hierarchy",
        "verifier_mode": framework_result["verifier_mode"],
        "reasoning_effort": reasoning_effort,
        "fixed_goal": fixed_goal,
        "replan_count": framework_result["replan_count"],
        "termination_reason": framework_result["termination_reason"],
        "stage_counts": framework_result["stage_counts"],
        "score": framework_result["score"].as_dict(),
        "outputs": framework_result["outputs"],
        "attempts": framework_result["attempts"],
    }
    return finalize_row(row, model_call_count, started_at, timer_start, client.call_records_since(call_start))


def run_inner_outer_loop(task, client, max_tokens: int, max_replans: int) -> Dict[str, object]:
    verifier_mode = "llm"
    current_state = {peg: list(stack) for peg, stack in task.initial.items()}
    executed_moves: List[tuple[str, str]] = []
    high_level_plan: List[str] = []
    parse_errors: List[str] = []
    attempts: List[Dict[str, object]] = []
    feedback = ""
    model_call_count = 0
    stage_counts = {
        "scene_descriptor_count": 0,
        "state_descriptor_count": 0,
        "h1_generation_count": 0,
        "h2_generation_count": 0,
        "decision_count": 0,
        "direct_model_call_count": 0,
        "innerbot_state_check_count": 0,
        "innerbot_plan_check_count": 0,
        "outerbot_check_count": 0,
        "innerbot_state_llm_call_count": 0,
        "innerbot_plan_llm_call_count": 0,
        "outerbot_llm_call_count": 0,
        "executed_subtask_count": 0,
    }
    total_top_level_count = 0
    last_illegal_reason = None
    last_outputs: Dict[str, object] = {"scene_json": build_scene_description(task, current_state)}
    termination_reason = "max_replans_exhausted"

    for attempt_index in range(max_replans + 1):
        feedback_in = feedback
        scene_json = build_scene_description(task, current_state)
        stage_counts["scene_descriptor_count"] += 1
        model_call_count += 1
        stage_counts["direct_model_call_count"] += 1
        direct_output = client.generate(
            system="DirectHanoiAgent: solve the current state with raw MoveHoop calls.",
            prompt=build_direct_hanoi_prompt(task, current_state=current_state, feedback=feedback),
            max_tokens=max_tokens,
        )
        last_outputs = {
            "scene_json": scene_json,
            "direct_output": direct_output,
        }
        attempt = {
            "attempt_index": attempt_index,
            "input_state": {peg: list(stack) for peg, stack in current_state.items()},
            "feedback_in": feedback_in,
            "events": [],
            "stage_outputs": {
                "scene_json": scene_json,
                "direct_output": direct_output,
            },
        }

        plan_valid, plan_reason, plan_strings, moves, direct_parse_errors = validate_direct_symbolic_plan(
            task=task,
            current_state=current_state,
            direct_output=direct_output,
        )
        parse_errors.extend(direct_parse_errors)
        stage_counts["innerbot_plan_check_count"] += 1
        if not direct_parse_errors:
            model_call_count += 1
            stage_counts["innerbot_plan_llm_call_count"] += 1
            innerbot_plan_output = client.generate(
                system="InnerBot plan verifier: verify direct MoveHoop plan correctness.",
                prompt=build_innerbot_direct_plan_prompt(task, scene_json, current_state, direct_output),
                max_tokens=max_tokens,
            )
            last_outputs["innerbot_plan_output"] = innerbot_plan_output
            attempt["stage_outputs"]["innerbot_plan_output"] = innerbot_plan_output
            llm_plan_valid, llm_plan_reason = parse_innerbot_verdict(innerbot_plan_output)
            if not llm_plan_valid:
                plan_valid = False
                plan_reason = llm_plan_reason
        if not plan_valid:
            feedback = f"InnerBot plan verifier rejected the direct plan: {plan_reason}"
            parse_errors.append(f"InnerBotPlan: {plan_reason}")
            attempt["innerbot_plan_check"] = {"result": "NO", "reason": plan_reason}
            attempt["verdict"] = "REPLAN"
            attempt["feedback_out"] = feedback
            attempts.append(attempt)
            continue

        attempt["innerbot_plan_check"] = {"result": "YES", "reason": plan_reason}
        high_level_plan.extend(plan_strings)
        total_top_level_count += len(plan_strings)
        executed_this_attempt: List[tuple[str, str]] = []
        replan_required = False

        for source, target in moves:
            move_number = len(executed_moves) + 1
            ok, reason = apply_hanoi_move(task, current_state, source, target, move_number)
            if not ok:
                last_illegal_reason = reason
                feedback = (
                    f"Recoverable execution error at move {move_number}: {reason}. "
                    f"Current state is {current_state}. Replan from this state."
                )
                attempt["events"].append(
                    {
                        "verdict": "RECOVERABLE",
                        "reason": reason,
                        "failed_move": [source, target],
                        "state": {peg: list(stack) for peg, stack in current_state.items()},
                    }
                )
                replan_required = True
                break

            executed_moves.append((source, target))
            executed_this_attempt.append((source, target))

        if replan_required:
            attempt["verdict"] = "REPLAN"
            attempt["feedback_out"] = feedback
            attempts.append(attempt)
            continue

        stage_counts["executed_subtask_count"] += 1
        stage_counts["scene_descriptor_count"] += 1
        stage_counts["outerbot_check_count"] += 1
        model_call_count += 1
        stage_counts["outerbot_llm_call_count"] += 1
        outerbot_output = client.generate(
            system=(
                "OuterBot execution error detector: compare JSON state representations and "
                "classify task completion or recoverable errors."
            ),
            prompt=build_outerbot_prompt(
                task=task,
                env_constraint=build_goal_description(task)["constraint_spatial_relations"],
                subtask_nl="Execute the direct MoveHoop plan from the current state to the final goal.",
                prev_state=scene_json,
                curr_state=build_scene_description(task, current_state),
                subtask_goal_state=build_goal_description(task)["goal_spatial_relations"],
                final_goal_state=build_goal_description(task)["goal_spatial_relations"],
            ),
            max_tokens=max_tokens,
        )
        last_outputs["outerbot_output"] = outerbot_output
        outer_verdict, outer_reason = parse_outerbot_verdict(outerbot_output)
        attempt["events"].append(
            {
                "verdict": outer_verdict,
                "outerbot_reason": outer_reason,
                "outerbot_output": outerbot_output,
                "high_level_calls": plan_strings,
                "executed_moves": executed_this_attempt,
                "state": {peg: list(stack) for peg, stack in current_state.items()},
            }
        )

        if outer_verdict == "TASK SUCCESS":
            feedback = ""
            attempt["verdict"] = "TASK SUCCESS"
            attempt["feedback_out"] = ""
            attempts.append(attempt)
            termination_reason = "task_success"
            break

        if outer_verdict in {"SUBTASK SUCCESS", "EXECUTE REMAINING ACTIONS"}:
            feedback = (
                f"OuterBot reported {outer_verdict} after direct plan: {outer_reason}. "
                f"Current state is {current_state}. Replan from this state."
            )
            attempt["verdict"] = "REPLAN"
            attempt["feedback_out"] = feedback
            attempts.append(attempt)
            continue

        if outer_verdict == "RECOVERABLE":
            feedback = (
                f"OuterBot reported RECOVERABLE after direct plan: {outer_reason}. "
                f"Current state is {current_state}. Replan from this state."
            )
            attempt["verdict"] = "REPLAN"
            attempt["feedback_out"] = feedback
            attempts.append(attempt)
            continue

        if outer_verdict == "NON-RECOVERABLE":
            last_illegal_reason = outer_reason
            feedback = f"OuterBot reported NON-RECOVERABLE after direct plan: {outer_reason}"
            attempt["verdict"] = "REPLAN"
            attempt["feedback_out"] = feedback
            attempts.append(attempt)
            termination_reason = "non_recoverable"
            break

    replan_count = sum(1 for attempt in attempts[:-1] if attempt.get("verdict") == "REPLAN")
    if current_state == task.goal:
        last_illegal_reason = None
    score = score_from_execution(
        task=task,
        final_state=current_state,
        moves=executed_moves,
        high_level_plan=high_level_plan,
        expanded_h0_plan=[],
        h1_valid=False,
        h2_valid=False,
        h1_call_count=0,
        h2_call_count=0,
        h0_call_count=0,
        top_level_call_count=total_top_level_count,
        parse_errors=parse_errors,
        illegal_reason=last_illegal_reason,
    )
    last_outputs["attempts"] = attempts
    return {
        "score": score,
        "outputs": last_outputs,
        "attempts": attempts,
        "model_call_count": model_call_count,
        "replan_count": replan_count,
        "stage_counts": stage_counts,
        "termination_reason": termination_reason,
        "verifier_mode": verifier_mode,
    }


def run_hierarchy_loop(task, client, fixed_goal: bool, max_tokens: int, max_replans: int) -> Dict[str, object]:
    verifier_mode = "llm"
    current_state = {peg: list(stack) for peg, stack in task.initial.items()}
    executed_moves: List[tuple[str, str]] = []
    high_level_plan: List[str] = []
    expanded_h0_plan: List[str] = []
    parse_errors: List[str] = []
    attempts: List[Dict[str, object]] = []
    feedback = ""
    model_call_count = 0
    stage_counts = {
        "scene_descriptor_count": 0,
        "state_descriptor_count": 0,
        "h1_generation_count": 0,
        "h2_generation_count": 0,
        "decision_count": 0,
        "innerbot_state_check_count": 0,
        "innerbot_plan_check_count": 0,
        "outerbot_check_count": 0,
        "innerbot_state_llm_call_count": 0,
        "innerbot_plan_llm_call_count": 0,
        "outerbot_llm_call_count": 0,
        "executed_subtask_count": 0,
    }
    total_h1_count = 0
    total_h2_count = 0
    total_h0_count = 0
    total_top_level_count = 0
    h1_valid_any = False
    h2_valid_any = False
    last_illegal_reason = None
    last_outputs: Dict[str, object] = {"scene_json": build_scene_description(task, current_state)}
    termination_reason = "max_replans_exhausted"
    previous_state_output = "N/A"

    for attempt_index in range(max_replans + 1):
        feedback_in = feedback
        scene_json = build_scene_description(task, current_state)
        stage_counts["scene_descriptor_count"] += 1

        if fixed_goal:
            state_output = "```start_flag\n" + as_json(build_goal_description(task)) + "\n```end_flag"
        else:
            model_call_count += 1
            stage_counts["state_descriptor_count"] += 1
            state_output = client.generate(
                system="StateDescriptor: generate goal_spatial_relations and constraint_spatial_relations.",
                prompt=build_state_prompt(
                    task,
                    scene_json,
                    previous_state_output=previous_state_output,
                    feedback=feedback or "N/A",
                ),
                max_tokens=max_tokens,
            )
            previous_state_output = state_output
        if fixed_goal:
            stage_counts["state_descriptor_count"] += 1

        stage_counts["innerbot_state_check_count"] += 1
        innerbot_state_output = None
        model_call_count += 1
        stage_counts["innerbot_state_llm_call_count"] += 1
        innerbot_state_output = client.generate(
            system="InnerBot state verifier: verify goal state and constraints against the user instruction.",
            prompt=build_innerbot_state_prompt(task, scene_json, state_output),
            max_tokens=max_tokens,
        )
        state_valid, state_reason = parse_innerbot_verdict(innerbot_state_output)
        if not state_valid:
            feedback = f"InnerBot state verifier rejected the state descriptor: {state_reason}"
            parse_errors.append(f"InnerBotState: {state_reason}")
            attempts.append(
                {
                    "attempt_index": attempt_index,
                    "input_state": {peg: list(stack) for peg, stack in current_state.items()},
                    "feedback_in": feedback_in,
                    "innerbot_state_check": {"result": "NO", "reason": state_reason},
                    "stage_outputs": {
                        "scene_json": scene_json,
                        "state_output": state_output,
                        "innerbot_state_output": innerbot_state_output,
                    },
                    "events": [],
                    "verdict": "REPLAN",
                    "feedback_out": feedback,
                }
            )
            continue

        model_call_count += 1
        stage_counts["h1_generation_count"] += 1
        h1_output = client.generate(
            system="H1ActionGenerator: create H1 functions from H0 primitives.",
            prompt=build_h1_prompt(scene_json),
            max_tokens=max_tokens,
        )
        model_call_count += 1
        stage_counts["h2_generation_count"] += 1
        h2_output = client.generate(
            system="H2ActionGenerator: create H2 functions from H1 functions.",
            prompt=build_h2_prompt(scene_json, h1_output),
            max_tokens=max_tokens,
        )
        model_call_count += 1
        stage_counts["decision_count"] += 1
        decision_output = client.generate(
            system="DecisionBot planner: create subtasks and function-call plan.",
            prompt=build_decision_prompt(task, scene_json, state_output, h1_output, h2_output, feedback=feedback),
            max_tokens=max_tokens,
        )

        last_outputs = {
            "scene_json": scene_json,
            "state_output": state_output,
            "innerbot_state_output": innerbot_state_output,
            "h1_output": h1_output,
            "h2_output": h2_output,
            "decision_output": decision_output,
        }

        attempt = {
            "attempt_index": attempt_index,
            "input_state": {peg: list(stack) for peg, stack in current_state.items()},
            "feedback_in": feedback_in,
            "innerbot_state_check": {"result": "YES", "reason": state_reason},
            "events": [],
            "stage_outputs": {
                "scene_json": scene_json,
                "state_output": state_output,
                "innerbot_state_output": innerbot_state_output,
                "h1_output": h1_output,
                "h2_output": h2_output,
                "decision_output": decision_output,
            },
        }

        h1_mappings, h1_errors = parse_mappings(h1_output)
        h2_mappings, h2_errors = parse_mappings(h2_output)
        attempt_errors = [f"H1: {err}" for err in h1_errors] + [f"H2: {err}" for err in h2_errors]

        h1_valid = not h1_errors and has_valid_h1_move_mapping(h1_mappings)
        h2_valid = not h2_errors and all_h2_calls_known(h2_mappings, h1_mappings)
        if not h1_errors and not h1_valid:
            attempt_errors.append("H1: no valid H1 mapping expands to MoveCoroutine, GrabCoroutine, MoveCoroutine, DropCoroutine")
        if not h2_errors and not h2_valid:
            attempt_errors.append("H2: no valid H2 mapping composed only of H1 calls")
        parse_errors.extend(attempt_errors)
        h1_valid_any = h1_valid_any or h1_valid
        h2_valid_any = h2_valid_any or h2_valid

        subtasks, subtask_errors = parse_subtask_plans(decision_output)
        attempt_errors.extend(f"Plan: {err}" for err in subtask_errors)
        parse_errors.extend(f"Plan: {err}" for err in subtask_errors)

        if attempt_errors or not subtasks:
            feedback = "Plan could not be parsed or mapped: " + "; ".join(attempt_errors)
            stage_counts["innerbot_plan_check_count"] += 1
            attempt["innerbot_plan_check"] = {"result": "NO", "reason": feedback}
            attempt["verdict"] = "REPLAN"
            attempt["feedback_out"] = feedback
            attempts.append(attempt)
            continue

        mappings = {**h1_mappings, **h2_mappings}
        plan_valid, plan_reason, validated_subtasks = validate_symbolic_plan(
            task=task,
            current_state=current_state,
            subtasks=subtasks,
            mappings=mappings,
            h1_mappings=h1_mappings,
            h2_mappings=h2_mappings,
        )
        stage_counts["innerbot_plan_check_count"] += 1
        innerbot_plan_output = None
        if plan_valid:
            model_call_count += 1
            stage_counts["innerbot_plan_llm_call_count"] += 1
            innerbot_plan_output = client.generate(
                system="InnerBot plan verifier: verify DecisionBot subtasks and hierarchy calls.",
                prompt=build_innerbot_plan_prompt(task, scene_json, state_output, h1_output, h2_output, decision_output),
                max_tokens=max_tokens,
            )
            last_outputs["innerbot_plan_output"] = innerbot_plan_output
            attempt["stage_outputs"]["innerbot_plan_output"] = innerbot_plan_output
            llm_plan_valid, llm_plan_reason = parse_innerbot_verdict(innerbot_plan_output)
            if not llm_plan_valid:
                plan_valid = False
                plan_reason = llm_plan_reason
        if not plan_valid:
            feedback = f"InnerBot plan verifier rejected the plan: {plan_reason}"
            parse_errors.append(f"InnerBotPlan: {plan_reason}")
            attempt["innerbot_plan_check"] = {"result": "NO", "reason": plan_reason}
            attempt["verdict"] = "REPLAN"
            attempt["feedback_out"] = feedback
            attempts.append(attempt)
            continue

        attempt["innerbot_plan_check"] = {"result": "YES", "reason": plan_reason}
        replan_required = False
        solved = False

        for validated in validated_subtasks:
            subtask_index = validated["subtask_index"]
            subtask_calls = validated["calls"]
            h0_calls = validated["h0_calls"]
            moves = validated["moves"]
            prev_state_for_outer = build_scene_description(task, current_state)
            total_h1_count += validated["h1_call_count"]
            total_h2_count += validated["h2_call_count"]
            total_top_level_count += len(subtask_calls)
            total_h0_count += len(h0_calls)
            high_level_plan.extend(str(call) for call in subtask_calls)
            expanded_h0_plan.extend(str(call) for call in h0_calls)
            executed_this_subtask: List[tuple[str, str]] = []
            for source, target in moves:
                move_number = len(executed_moves) + 1
                ok, reason = apply_hanoi_move(task, current_state, source, target, move_number)
                if not ok:
                    last_illegal_reason = reason
                    feedback = (
                        f"Recoverable execution error at move {move_number}: {reason}. "
                        f"Current state is {current_state}. Replan from this state."
                    )
                    attempt["events"].append(
                        {
                            "subtask_index": subtask_index,
                            "verdict": "RECOVERABLE",
                            "reason": reason,
                            "failed_move": [source, target],
                            "state": {peg: list(stack) for peg, stack in current_state.items()},
                        }
                    )
                    replan_required = True
                    break

                executed_moves.append((source, target))
                executed_this_subtask.append((source, target))

            if replan_required:
                break

            stage_counts["executed_subtask_count"] += 1
            stage_counts["scene_descriptor_count"] += 1
            stage_counts["outerbot_check_count"] += 1
            model_call_count += 1
            stage_counts["outerbot_llm_call_count"] += 1
            subtask_goal_state = (
                build_scene_description(task, task.goal)
                if subtask_index == len(validated_subtasks)
                else build_scene_description(task, validated["projected_state"])
            )
            outerbot_output = client.generate(
                system=(
                    "OuterBot execution error detector: compare JSON state representations and "
                    "classify task completion or recoverable errors."
                ),
                prompt=build_outerbot_prompt(
                    task=task,
                    env_constraint=build_goal_description(task)["constraint_spatial_relations"],
                    subtask_nl=f"Execute subtask {subtask_index} with calls: "
                    + ", ".join(str(call) for call in subtask_calls),
                    prev_state=prev_state_for_outer,
                    curr_state=build_scene_description(task, current_state),
                    subtask_goal_state=subtask_goal_state,
                    final_goal_state=build_scene_description(task, task.goal),
                ),
                max_tokens=max_tokens,
            )
            last_outputs["outerbot_output"] = outerbot_output
            outer_verdict, outer_reason = parse_outerbot_verdict(outerbot_output)
            attempt["events"].append(
                {
                    "subtask_index": subtask_index,
                    "verdict": outer_verdict,
                    "outerbot_reason": outer_reason,
                    "outerbot_output": outerbot_output,
                    "high_level_calls": [str(call) for call in subtask_calls],
                    "expanded_h0_calls": [str(call) for call in h0_calls],
                    "executed_moves": executed_this_subtask,
                    "state": {peg: list(stack) for peg, stack in current_state.items()},
                }
            )
            if outer_verdict == "TASK SUCCESS":
                feedback = ""
                solved = True
                break
            if outer_verdict == "EXECUTE REMAINING ACTIONS":
                continue
            if outer_verdict == "RECOVERABLE":
                feedback = (
                    f"OuterBot reported RECOVERABLE after subtask {subtask_index}: {outer_reason}. "
                    f"Current state is {current_state}. Replan from this state."
                )
                replan_required = True
                break
            if outer_verdict == "NON-RECOVERABLE":
                last_illegal_reason = outer_reason
                feedback = f"OuterBot reported NON-RECOVERABLE after subtask {subtask_index}: {outer_reason}"
                replan_required = True
                termination_reason = "non_recoverable"
                break

        attempt["output_state"] = {peg: list(stack) for peg, stack in current_state.items()}
        if solved:
            attempt["verdict"] = "TASK SUCCESS"
            attempt["feedback_out"] = ""
            attempts.append(attempt)
            termination_reason = "task_success"
            break

        if replan_required:
            attempt["verdict"] = "REPLAN"
            attempt["feedback_out"] = feedback
            attempts.append(attempt)
            if termination_reason == "non_recoverable":
                break
            continue

        feedback = (
            f"Plan finished without reaching the final goal. Current state is {current_state}. "
            "Generate a corrected plan from this state."
        )
        attempt["verdict"] = "REPLAN"
        attempt["feedback_out"] = feedback
        attempts.append(attempt)

    replan_count = sum(1 for attempt in attempts[:-1] if attempt.get("verdict") == "REPLAN")
    if current_state == task.goal:
        last_illegal_reason = None
    score = score_from_execution(
        task=task,
        final_state=current_state,
        moves=executed_moves,
        high_level_plan=high_level_plan,
        expanded_h0_plan=expanded_h0_plan,
        h1_valid=h1_valid_any,
        h2_valid=h2_valid_any,
        h1_call_count=total_h1_count,
        h2_call_count=total_h2_count,
        h0_call_count=total_h0_count,
        top_level_call_count=total_top_level_count,
        parse_errors=parse_errors,
        illegal_reason=last_illegal_reason,
    )
    last_outputs["attempts"] = attempts
    return {
        "score": score,
        "outputs": last_outputs,
        "attempts": attempts,
        "model_call_count": model_call_count,
        "replan_count": replan_count,
        "stage_counts": stage_counts,
        "termination_reason": termination_reason,
        "verifier_mode": verifier_mode,
    }


def validate_direct_symbolic_plan(
    task,
    current_state: Dict[str, List[str]],
    direct_output: str,
) -> Tuple[bool, str, List[str], List[tuple[str, str]], List[str]]:
    parse_errors: List[str] = []
    plan, plan_errors = parse_plan(direct_output)
    parse_errors.extend(f"Plan: {err}" for err in plan_errors)
    plan_strings = [str(call) for call in plan]
    moves = direct_moves_from_calls(plan)

    if not moves:
        expanded_h0 = [call for call in plan if call.name in PRIMITIVES]
        moves, h0_errors = extract_moves_from_h0(expanded_h0)
        parse_errors.extend(f"H0: {err}" for err in h0_errors)

    if parse_errors:
        return False, "Plan could not be parsed cleanly: " + "; ".join(parse_errors), plan_strings, moves, parse_errors

    if not moves:
        reason = "Direct plan did not contain MoveHoop-style calls or valid H0 primitive groups"
        parse_errors.append(reason)
        return False, reason, plan_strings, moves, parse_errors

    simulated_state = {peg: list(stack) for peg, stack in current_state.items()}
    for move_index, (source, target) in enumerate(moves, start=1):
        ok, reason = apply_hanoi_move(task, simulated_state, source, target, move_index)
        if not ok:
            return False, reason or "illegal symbolic Hanoi move", plan_strings, moves, parse_errors

    return True, "N/A", plan_strings, moves, parse_errors


def parse_innerbot_verdict(output: str) -> Tuple[bool, str]:
    block = extract_between_flags(output, "```start_result", "```end_result") or output
    result = extract_labeled_value(block, "RESULT")
    reason = extract_labeled_value(block, "REASON") or "N/A"
    normalized = normalize_verdict_text(result)
    if normalized.startswith("YES"):
        return True, reason
    if normalized.startswith("NO"):
        return False, reason
    return False, f"could not parse InnerBot RESULT from verifier output: {truncate_for_reason(output)}"


def parse_outerbot_verdict(output: str) -> Tuple[str, str]:
    block = extract_between_flags(output, "```start_error_type", "```end_error_type") or output
    error = extract_labeled_value(block, "Error") or extract_labeled_value(block, "ERROR")
    reason = extract_labeled_value(block, "Reason") or extract_labeled_value(block, "REASON") or "N/A"
    normalized = normalize_outerbot_verdict(error)
    if normalized:
        return normalized, reason
    return "RECOVERABLE", f"could not parse OuterBot Error field from verifier output: {truncate_for_reason(output)}"


def extract_labeled_value(text: str, label: str) -> str:
    pattern = rf"^\s*{label}\s*:\s*(.+?)\s*$"
    for line in text.splitlines():
        match = re_match_case_insensitive(pattern, line)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return ""


def re_match_case_insensitive(pattern: str, value: str):
    import re

    return re.search(pattern, value, flags=re.IGNORECASE)


def normalize_verdict_text(value: str) -> str:
    return value.strip().strip("`").strip('"').upper()


def normalize_outerbot_verdict(value: str) -> str:
    normalized = normalize_verdict_text(value)
    normalized = normalized.replace("_", " ").replace("-", " ")
    if "|" in normalized or "<" in normalized or ">" in normalized:
        return ""
    if "NON" in normalized and "RECOVERABLE" in normalized:
        return "NON-RECOVERABLE"
    if "SUBTASK" in normalized and "SUCCESS" in normalized:
        return "SUBTASK SUCCESS"
    if "TASK" in normalized and "SUCCESS" in normalized:
        return "TASK SUCCESS"
    if "EXECUTE" in normalized and "REMAINING" in normalized:
        return "EXECUTE REMAINING ACTIONS"
    if "RECOVERABLE" in normalized:
        return "RECOVERABLE"
    return ""


def truncate_for_reason(value: str, limit: int = 240) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def validate_symbolic_plan(
    task,
    current_state: Dict[str, List[str]],
    subtasks,
    mappings,
    h1_mappings,
    h2_mappings,
) -> Tuple[bool, str, List[Dict[str, object]]]:
    simulated_state = {peg: list(stack) for peg, stack in current_state.items()}
    validated_subtasks: List[Dict[str, object]] = []
    simulated_move_count = 0

    for subtask_index, subtask_calls in enumerate(subtasks, start=1):
        h1_count, h2_count = count_hierarchy_calls(subtask_calls, h1_mappings, h2_mappings)
        h0_calls, expand_errors = expand_calls(subtask_calls, mappings)
        if expand_errors:
            return False, "Plan expansion failed: " + "; ".join(expand_errors), validated_subtasks

        moves, h0_errors = extract_moves_from_h0(h0_calls)
        if h0_errors:
            return False, "Expanded H0 sequence is invalid: " + "; ".join(h0_errors), validated_subtasks

        for source, target in moves:
            simulated_move_count += 1
            ok, reason = apply_hanoi_move(task, simulated_state, source, target, simulated_move_count)
            if not ok:
                return False, reason or "illegal symbolic Hanoi move", validated_subtasks

        validated_subtasks.append(
            {
                "subtask_index": subtask_index,
                "calls": subtask_calls,
                "h0_calls": h0_calls,
                "moves": moves,
                "h1_call_count": h1_count,
                "h2_call_count": h2_count,
                "projected_state": {peg: list(stack) for peg, stack in simulated_state.items()},
            }
        )

    return True, "N/A", validated_subtasks


TOKEN_FIELDS = [
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
]


def empty_token_usage_summary() -> Dict[str, object]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cached_input_tokens": 0,
        "prompt_char_count": 0,
        "output_char_count": 0,
        "call_count": 0,
        "api_usage_call_count": 0,
        "estimated_usage_call_count": 0,
        "missing_usage_call_count": 0,
        "by_stage": {},
        "calls": [],
    }


def aggregate_token_usage(model_call_records: List[Dict[str, object]]) -> Dict[str, object]:
    summary = empty_token_usage_summary()
    by_stage: Dict[str, Dict[str, object]] = {}

    for call in model_call_records:
        usage = call.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        stage = str(call.get("stage") or "unknown")
        stage_summary = by_stage.setdefault(stage, empty_stage_token_usage_summary())

        summary["call_count"] += 1
        stage_summary["call_count"] += 1
        summary["prompt_char_count"] += int_or_zero(call.get("prompt_char_count"))
        summary["output_char_count"] += int_or_zero(call.get("output_char_count"))
        stage_summary["prompt_char_count"] += int_or_zero(call.get("prompt_char_count"))
        stage_summary["output_char_count"] += int_or_zero(call.get("output_char_count"))

        source = str(usage.get("usage_source") or "missing")
        if source == "api":
            summary["api_usage_call_count"] += 1
            stage_summary["api_usage_call_count"] += 1
        elif source == "estimated":
            summary["estimated_usage_call_count"] += 1
            stage_summary["estimated_usage_call_count"] += 1
        else:
            summary["missing_usage_call_count"] += 1
            stage_summary["missing_usage_call_count"] += 1

        for field in TOKEN_FIELDS:
            value = int_or_zero(usage.get(field))
            summary[field] += value
            stage_summary[field] += value

        summary["calls"].append(call)

    summary["by_stage"] = by_stage
    return summary


def empty_stage_token_usage_summary() -> Dict[str, object]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cached_input_tokens": 0,
        "prompt_char_count": 0,
        "output_char_count": 0,
        "call_count": 0,
        "api_usage_call_count": 0,
        "estimated_usage_call_count": 0,
        "missing_usage_call_count": 0,
    }


def int_or_zero(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def finalize_row(
    row: Dict[str, object],
    model_call_count: int,
    started_at: float,
    timer_start: float,
    model_call_records: List[Dict[str, object]],
) -> Dict[str, object]:
    elapsed_seconds = round(time.perf_counter() - timer_start, 3)
    row["model_call_records"] = model_call_records
    row["token_usage"] = aggregate_token_usage(model_call_records)
    row["metrics"] = build_metrics_with_extras(
        row, build_metrics(row, model_call_count, started_at, elapsed_seconds)
    )
    row["steps"] = build_steps(row)
    result_dir = structured_result_dir(row)
    row["structured_result_dir"] = str(result_dir)
    write_structured_result(row, result_dir)
    return row


def build_metrics(
    row: Dict[str, object],
    model_call_count: int,
    started_at: float,
    elapsed_seconds: float,
) -> Dict[str, object]:
    score = row["score"]
    stage_counts = row.get("stage_counts", {})
    token_usage = row.get("token_usage", empty_token_usage_summary())
    return {
        "task": row["task"],
        "provider": row["provider"],
        "model": row["model"],
        "mode": row["mode"],
        "verifier_mode": row.get("verifier_mode", "none"),
        "reasoning_effort": row.get("reasoning_effort"),
        "fixed_goal": row["fixed_goal"],
        "started_at_unix": started_at,
        "elapsed_seconds": elapsed_seconds,
        "model_steps": model_call_count,
        "model_call_count": model_call_count,
        "token_usage": token_usage,
        "token_usage_available": token_usage["api_usage_call_count"] > 0,
        "input_tokens": token_usage["input_tokens"],
        "output_tokens": token_usage["output_tokens"],
        "total_tokens": token_usage["total_tokens"],
        "reasoning_tokens": token_usage["reasoning_tokens"],
        "cached_input_tokens": token_usage["cached_input_tokens"],
        "termination_reason": row.get("termination_reason"),
        "attempt_count": len(row.get("attempts", [])) if "attempts" in row else 1,
        "replan_count": row.get("replan_count", 0),
        "total_steps": score["move_count"],
        "move_count": score["move_count"],
        "optimal_move_count": score["optimal_move_count"],
        "optimal": score["optimal"],
        "solved": score["solved"],
        "legal": score["legal"],
        "h1_valid": score["h1_valid"],
        "h2_valid": score["h2_valid"],
        "h1_count": score["h1_call_count"],
        "h2_count": score["h2_call_count"],
        "h0_count": score["h0_call_count"],
        "top_level_call_count": score["top_level_call_count"],
        "parse_error_count": len(score["parse_errors"]),
        "parse_errors": score["parse_errors"],
        "illegal_reason": score["illegal_reason"],
        "stage_counts": stage_counts,
        "extra_metrics_keys": sorted(row.get("extra_metrics", {})) if isinstance(row.get("extra_metrics"), dict) else [],
        "scene_descriptor_count": stage_counts.get("scene_descriptor_count", 0),
        "state_descriptor_count": stage_counts.get("state_descriptor_count", 0),
        "h1_generation_count": stage_counts.get("h1_generation_count", 0),
        "h2_generation_count": stage_counts.get("h2_generation_count", 0),
        "decision_count": stage_counts.get("decision_count", 0),
        "innerbot_state_check_count": stage_counts.get("innerbot_state_check_count", 0),
        "innerbot_plan_check_count": stage_counts.get("innerbot_plan_check_count", 0),
        "outerbot_check_count": stage_counts.get("outerbot_check_count", 0),
        "innerbot_state_llm_call_count": stage_counts.get("innerbot_state_llm_call_count", 0),
        "innerbot_plan_llm_call_count": stage_counts.get("innerbot_plan_llm_call_count", 0),
        "outerbot_llm_call_count": stage_counts.get("outerbot_llm_call_count", 0),
        "executed_subtask_count": stage_counts.get("executed_subtask_count", 0),
        "notes": benchmark_mode_notes(str(row["mode"])),
    }


def build_metrics_with_extras(row: Dict[str, object], metrics: Dict[str, object]) -> Dict[str, object]:
    """Merge a mode's own metric keys, if it supplied any, into the payload."""
    extra = row.get("extra_metrics")
    if isinstance(extra, dict):
        metrics.update(extra)
    return metrics


def benchmark_mode_notes(mode: str) -> str:
    if mode == "dynamic-hierarchy":
        return "Dynamic-hierarchy mode separates planning from hierarchy composition: the DecisionBot emits subtasks and goal states only, a HierarchyPlanner composes H2 through Hn from that plan, and an InnerBot router attributes any mistake to the planner, the hierarchy planner, or both. It reuses the StateDescriptor, H1 generation, symbolic H0 execution, and OuterBot checks from hierarchy mode. Unity camera/robot execution is not used."
    if mode == "hierarchy":
        return "Hierarchy mode uses JSON scene/state, LLM InnerBot/OuterBot verifier calls based on the Unity prompts, H1/H2 expansion, symbolic H0 execution, and replanning over Hanoi states. Unity camera/robot execution is not used."
    if mode == "inner-outer":
        return "Inner-outer mode uses a direct MoveHoop planner wrapped in LLM InnerBot/OuterBot verifier calls and replanning over Hanoi states. It does not generate StateDescriptor, H1, H2, or DecisionBot outputs."
    return "Not-hierarchy mode makes one direct MoveHoop model call and then scores legality, completion, and optimality. It does not run InnerBot, OuterBot, H1, or H2."


def build_steps(row: Dict[str, object]) -> Dict[str, object]:
    score = row["score"]
    outputs = row["outputs"]
    steps = {
        "task": row["task"],
        "provider": row["provider"],
        "model": row["model"],
        "mode": row["mode"],
        "verifier_mode": row.get("verifier_mode", "none"),
        "reasoning_effort": row.get("reasoning_effort"),
        "scene_json": outputs.get("scene_json"),
        "high_level_plan": score["high_level_plan"],
        "expanded_h0_plan": score["expanded_h0_plan"],
        "hanoi_moves": score["moves"],
        "final_state": score["final_state"],
        "replan_count": row.get("replan_count", 0),
        "termination_reason": row.get("termination_reason"),
        "stage_counts": row.get("stage_counts", {}),
        "token_usage": row.get("token_usage", empty_token_usage_summary()),
    }
    if "attempts" in row:
        steps["attempts"] = row["attempts"]
    if row["mode"] == "hierarchy":
        steps.update(
            {
                "state_output": outputs.get("state_output"),
                "h1_output": outputs.get("h1_output"),
                "h2_output": outputs.get("h2_output"),
                "decision_output": outputs.get("decision_output"),
            }
        )
    elif row["mode"] == "dynamic-hierarchy":
        steps.update(
            {
                "state_output": outputs.get("state_output"),
                "h1_output": outputs.get("h1_output"),
                "plan_output": outputs.get("plan_output"),
                "hierarchy_output": outputs.get("hierarchy_output"),
                "router_output": outputs.get("router_output"),
            }
        )
    else:
        steps["direct_output"] = outputs.get("direct_output")
    return steps


def write_structured_result(row: Dict[str, object], result_dir: Path) -> Path:
    result_dir.mkdir(parents=True, exist_ok=True)
    write_json(result_dir / "metrics.json", row["metrics"])
    write_json(result_dir / "steps.json", row["steps"])
    write_jsonl(result_dir / "raw_log.jsonl", row)
    return result_dir


def structured_result_dir(row: Dict[str, object]) -> Path:
    safe_model = safe_path_part(str(row["model"]))
    mode = str(row["mode"])
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    leaf = f"{row['task']}_{timestamp}"
    return RESULTS_DIR / safe_model / mode / leaf


def safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)


def write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def print_summary(rows: List[Dict[str, object]], output_path: Optional[Path]) -> None:
    print("")
    print("Task      Mode           Solved  Legal  Optimal  Moves  OptimalMoves  Replans  H1  H2")
    print("--------  -------------  ------  -----  -------  -----  ------------  -------  --  --")
    for row in rows:
        score = row["score"]
        framework_mode = row.get("mode", "hierarchy") in {"hierarchy", "dynamic-hierarchy"}
        print(
            f"{row['task']:<8}  "
            f"{row.get('mode', 'hierarchy'):<13}  "
            f"{yes_no(score['solved']):<6}  "
            f"{yes_no(score['legal']):<5}  "
            f"{yes_no(score['optimal']):<7}  "
            f"{score['move_count']:<5}  "
            f"{score['optimal_move_count']:<12}  "
            f"{row.get('replan_count', 0):<7}  "
            f"{yes_no(score['h1_valid']) if framework_mode else '--':<2}  "
            f"{yes_no(score['h2_valid']) if framework_mode else '--':<2}"
        )
        if score["illegal_reason"]:
            print(f"  illegal: {score['illegal_reason']}")
        if score["parse_errors"]:
            print(f"  parse/errors: {len(score['parse_errors'])} issue(s), see raw_log.jsonl")
    print("")
    if output_path is not None:
        print(f"Aggregate raw log: {output_path}")
    for row in rows:
        print(f"Structured result: {row['structured_result_dir']}")
        print(f"Raw log: {Path(str(row['structured_result_dir'])) / 'raw_log.jsonl'}")


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


if __name__ == "__main__":
    raise SystemExit(main())
