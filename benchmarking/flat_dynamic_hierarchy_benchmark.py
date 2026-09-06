"""Dynamic (n-level) hierarchy benchmark, flat-to-flat variant.

Mirrors dynamic_hierarchy_benchmark.py's pipeline exactly:

  StateDescriptor -> InnerBot state check -> H1 generation
    -> DecisionBot (plan only, no actions)
    -> HierarchyPlanner (composes H2..Hn from the plan)
    -> deterministic symbolic validation
    -> InnerBot router (mistake? whose? why?)
    -> execution -> OuterBot -> back through the router

against flat_hanoi_task_loader.FlatHanoiTask and flat_dynamic_prompts.py /
flat_prompts.py instead of the tower-to-tower task_loader.py / prompts.py /
dynamic_prompts.py, so tower framing never reaches a flat task's prompts.

finalize_row and print_summary are imported from flat_hanoi_benchmark.py
rather than hanoi_benchmark.py: both operate only on the row dict (task
shape never enters them), and flat_hanoi_benchmark.py's print_summary
already renders a None optimal_move_count as "--" instead of crashing, and
its structured_result_dir already includes the microsecond+uuid suffix
needed for --jobs. Reusing that fixed copy avoids re-doing both fixes here.

Results are written under mode "dynamic-hierarchy", matching
dynamic_hierarchy_benchmark.py, under results_flat/ instead of results/.

Usage mirrors dynamic_hierarchy_benchmark.py:
    python benchmarking/flat_dynamic_hierarchy_benchmark.py --task hanoi_flat_3_00 --provider mock
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from flat_dynamic_prompts import (
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
    hierarchy_metrics,
    legacy_call_counts,
    legacy_validity,
    parse_plan_subtasks,
    parse_router_verdict,
)
from flat_hanoi_benchmark import (
    finalize_row,
    parse_innerbot_verdict,
    parse_outerbot_verdict,
    print_summary,
)
from models import TruncatedResponseError, create_client, load_env_file
from flat_prompts import (
    as_json,
    build_goal_description,
    build_h1_prompt,
    build_innerbot_state_prompt,
    build_outerbot_prompt,
    build_scene_description,
    build_state_prompt,
)
from scoring import (
    apply_hanoi_move,
    extract_moves_from_h0,
    parse_mappings,
    parse_subtask_plans,
)
from flat_hanoi_scoring import score_from_execution
from flat_hanoi_task_loader import available_tasks, load_task


BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = BENCHMARK_DIR / ".env"

MODE = "dynamic-hierarchy"

# System strings. The mock client dispatches on these, and they are recorded in
# model_call_records for every provider.
SYSTEM_STATE = "StateDescriptor: generate goal_spatial_relations and constraint_spatial_relations."
SYSTEM_INNERBOT_STATE = (
    "InnerBot state verifier: verify goal state and constraints against the user instruction."
)
SYSTEM_H1 = "H1ActionGenerator: create H1 functions from H0 primitives."
SYSTEM_PLAN = "DecisionBot planner: produce subtasks and goal states, plan only, no actions."
SYSTEM_HIERARCHY = "HierarchyPlanner: compose H2 through Hn from the plan and the H1 actions."
SYSTEM_ROUTER = (
    "InnerBot router: decide whether there is a mistake, which component owns it, and why."
)
SYSTEM_OUTERBOT = (
    "OuterBot execution error detector: compare JSON state representations and "
    "classify task completion or recoverable errors."
)

# Per-stage reasoning effort overrides. The plan and hierarchy composition
# stages, plus the InnerBot checks, get the base --reasoning value (medium);
# everything else drops to low since those stages are comparatively simple
# and the pipeline is sequential, so per-call latency there directly adds up.
REASONING_MEDIUM_STAGES = {SYSTEM_PLAN, SYSTEM_HIERARCHY, SYSTEM_INNERBOT_STATE, SYSTEM_ROUTER}


def stage_reasoning_effort(system: str, base_effort: Optional[str]) -> Optional[str]:
    if base_effort is None:
        return None
    return base_effort if system in REASONING_MEDIUM_STAGES else "low"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Tower of Hanoi planning benchmarks through the n-level hierarchy pipeline."
    )
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
    parser.add_argument("--reasoning", choices=["low", "medium", "high"], default=None)
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Sampling temperature for local/openai-compatible providers. Defaults to 0 (or LOCAL_TEMPERATURE from .env).",
    )
    parser.add_argument(
        "--fixed-goal",
        action="store_true",
        help="Use deterministic goal JSON instead of asking the model for the StateDescriptor output.",
    )
    parser.add_argument("--output", default=None, help="Optional aggregate JSONL result path.")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument(
        "--max-replans",
        type=int,
        default=15,
        help="Maximum correction rounds. Matches the hierarchy-mode default for comparability.",
    )
    parser.add_argument(
        "--reuse-h1",
        action="store_true",
        help=(
            "Generate the H1 actions once and reuse them across correction rounds. "
            "Off by default so token accounting matches hierarchy mode."
        ),
    )
    parser.add_argument(
        "--no-code-block",
        action="store_true",
        help=(
            "Ask the HierarchyPlanner for mappings only, without C# definitions. "
            "Nothing parses that block; this is a token ablation."
        ),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help=(
            "Run up to N tasks concurrently via a thread pool. Task runs are "
            "independent, so this gives near-linear speedup over the default "
            "serial loop. Each worker still makes model calls one at a time "
            "within its own task."
        ),
    )
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")
    return args


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))

    provider = args.provider or os.environ.get("DEFAULT_PROVIDER") or "mock"
    model = args.model or os.environ.get("DEFAULT_MODEL")
    reasoning_effort = args.reasoning or os.environ.get("DEFAULT_REASONING_EFFORT")

    task_ids = available_tasks() if args.task == "all" else [args.task]
    output_path = Path(args.output) if args.output else None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    def run_one(task_id: str) -> Dict[str, object]:
        # Each concurrent task gets its own client instance -- ModelClient
        # accumulates call_history on self and is not designed to be shared
        # across threads.
        client = create_client(
            provider=provider,
            model=model,
            base_url=args.base_url,
            reasoning_effort=reasoning_effort,
            temperature=args.temperature,
        )
        return run_task(
            task_id,
            client,
            fixed_goal=args.fixed_goal,
            max_tokens=args.max_tokens,
            max_replans=args.max_replans,
            reasoning_effort=reasoning_effort,
            reuse_h1=args.reuse_h1,
            include_code_block=not args.no_code_block,
        )

    rows: List[Dict[str, object]] = []
    write_lock = threading.Lock()
    aggregate_handle = output_path.open("w", encoding="utf-8") if output_path is not None else None
    try:
        if args.jobs == 1:
            for task_id in task_ids:
                row = run_one(task_id)
                rows.append(row)
                if aggregate_handle is not None:
                    aggregate_handle.write(json.dumps(row, sort_keys=True) + "\n")
                    aggregate_handle.flush()
        else:
            with ThreadPoolExecutor(max_workers=args.jobs) as executor:
                futures = {executor.submit(run_one, task_id): task_id for task_id in task_ids}
                for future in as_completed(futures):
                    row = future.result()
                    rows.append(row)
                    if aggregate_handle is not None:
                        with write_lock:
                            aggregate_handle.write(json.dumps(row, sort_keys=True) + "\n")
                            aggregate_handle.flush()
            rows.sort(key=lambda r: task_ids.index(r["task"]) if r["task"] in task_ids else 0)
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
    max_replans: int,
    reasoning_effort: Optional[str],
    reuse_h1: bool,
    include_code_block: bool,
) -> Dict[str, object]:
    call_start = len(getattr(client, "call_history", []))
    started_at = time.time()
    timer_start = time.perf_counter()
    task = load_task(task_id)

    result = run_dynamic_hierarchy_loop(
        task=task,
        client=client,
        fixed_goal=fixed_goal,
        max_tokens=max_tokens,
        max_replans=max_replans,
        reuse_h1=reuse_h1,
        include_code_block=include_code_block,
        reasoning_effort=reasoning_effort,
    )
    row = {
        "task": task.id,
        "provider": client.provider,
        "model": client.model,
        "mode": MODE,
        "verifier_mode": result["verifier_mode"],
        "reasoning_effort": reasoning_effort,
        "fixed_goal": fixed_goal,
        "replan_count": result["replan_count"],
        "termination_reason": result["termination_reason"],
        "stage_counts": result["stage_counts"],
        "score": result["score"].as_dict(),
        "outputs": result["outputs"],
        "attempts": result["attempts"],
        "extra_metrics": result["extra_metrics"],
    }
    return finalize_row(
        row,
        result["model_call_count"],
        started_at,
        timer_start,
        client.call_records_since(call_start),
    )


def run_dynamic_hierarchy_loop(
    task,
    client,
    fixed_goal: bool,
    max_tokens: int,
    max_replans: int,
    reuse_h1: bool,
    include_code_block: bool,
    reasoning_effort: Optional[str] = None,
) -> Dict[str, object]:
    current_state = {peg: list(stack) for peg, stack in task.initial.items()}
    executed_moves: List[Tuple[str, str]] = []
    high_level_plan: List[str] = []
    expanded_h0_plan: List[str] = []
    parse_errors: List[str] = []
    attempts: List[Dict[str, object]] = []
    router_attributions: List[str] = []

    feedback = ""
    plan_output: Optional[str] = None
    h1_output: Optional[str] = None
    regenerate_plan = True
    model_call_count = 0
    stage_counts = new_stage_counts()

    total_top_level_count = 0
    total_h0_count = 0
    level_totals: Dict[int, int] = {}
    max_level_seen = 0
    base_valid_any = False
    hierarchy_valid_any = False
    last_mapping_count_by_level: Dict[int, int] = {}
    hierarchy_errors_seen: List[str] = []
    last_illegal_reason: Optional[str] = None
    termination_reason = "max_replans_exhausted"
    previous_state_output = "N/A"
    last_outputs: Dict[str, object] = {"scene_json": build_scene_description(task, current_state)}

    def route(owner: str) -> None:
        """Apply the router's attribution. Only 'hierarchy' keeps the plan."""
        nonlocal regenerate_plan
        router_attributions.append(owner)
        regenerate_plan = owner != OWNER_HIERARCHY

    for attempt_index in range(max_replans + 1):
        try:
            feedback_in = feedback
            scene_json = build_scene_description(task, current_state)
            stage_counts["scene_descriptor_count"] += 1

            if fixed_goal:
                state_output = "```start_flag\n" + as_json(build_goal_description(task)) + "\n```end_flag"
                stage_counts["state_descriptor_count"] += 1
            else:
                model_call_count += 1
                stage_counts["state_descriptor_count"] += 1
                state_output = client.generate(
                    system=SYSTEM_STATE,
                    prompt=build_state_prompt(
                        task,
                        scene_json,
                        previous_state_output=previous_state_output,
                        feedback=feedback or "N/A",
                    ),
                    max_tokens=max_tokens,
                    reasoning_effort=stage_reasoning_effort(SYSTEM_STATE, reasoning_effort),
                )
                previous_state_output = state_output

            stage_counts["innerbot_state_check_count"] += 1
            model_call_count += 1
            stage_counts["innerbot_state_llm_call_count"] += 1
            innerbot_state_output = client.generate(
                system=SYSTEM_INNERBOT_STATE,
                prompt=build_innerbot_state_prompt(task, scene_json, state_output),
                max_tokens=max_tokens,
                reasoning_effort=stage_reasoning_effort(SYSTEM_INNERBOT_STATE, reasoning_effort),
            )
            state_valid, state_reason = parse_innerbot_verdict(innerbot_state_output)
            if not state_valid:
                feedback = f"InnerBot state verifier rejected the state descriptor: {state_reason}"
                parse_errors.append(f"InnerBotState: {state_reason}")
                regenerate_plan = True
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

            if h1_output is None or not reuse_h1:
                model_call_count += 1
                stage_counts["h1_generation_count"] += 1
                h1_output = client.generate(
                    system=SYSTEM_H1,
                    prompt=build_h1_prompt(scene_json),
                    max_tokens=max_tokens,
                    reasoning_effort=stage_reasoning_effort(SYSTEM_H1, reasoning_effort),
                )

            if regenerate_plan or plan_output is None:
                model_call_count += 1
                stage_counts["plan_generation_count"] += 1
                plan_output = client.generate(
                    system=SYSTEM_PLAN,
                    prompt=build_plan_prompt(task, scene_json, state_output, h1_output, feedback=feedback),
                    max_tokens=max_tokens,
                    reasoning_effort=stage_reasoning_effort(SYSTEM_PLAN, reasoning_effort),
                )
            plan_subtasks, plan_parse_errors = parse_plan_subtasks(plan_output)

            model_call_count += 1
            stage_counts["hierarchy_generation_count"] += 1
            hierarchy_output = client.generate(
                system=SYSTEM_HIERARCHY,
                prompt=build_hierarchy_planner_prompt(
                    task=task,
                    scene_json=scene_json,
                    state_output=state_output,
                    h1_output=h1_output,
                    plan_output=plan_output,
                    feedback=feedback,
                    include_code_block=include_code_block,
                ),
                max_tokens=max_tokens,
                reasoning_effort=stage_reasoning_effort(SYSTEM_HIERARCHY, reasoning_effort),
            )

            last_outputs = {
                "scene_json": scene_json,
                "state_output": state_output,
                "innerbot_state_output": innerbot_state_output,
                "h1_output": h1_output,
                "plan_output": plan_output,
                "hierarchy_output": hierarchy_output,
            }
            attempt: Dict[str, object] = {
                "attempt_index": attempt_index,
                "input_state": {peg: list(stack) for peg, stack in current_state.items()},
                "feedback_in": feedback_in,
                "plan_regenerated": regenerate_plan or attempt_index == 0,
                "innerbot_state_check": {"result": "YES", "reason": state_reason},
                "events": [],
                "stage_outputs": dict(last_outputs),
            }

            h1_mappings, h1_errors = parse_mappings(h1_output)
            composed_mappings, composed_errors = parse_mappings(hierarchy_output)
            mappings = {**h1_mappings, **composed_mappings}
            analysis = analyze_hierarchy(mappings)
            subtasks, subtask_errors = parse_subtask_plans(hierarchy_output)

            attempt_errors = [f"H1: {err}" for err in h1_errors]
            attempt_errors += [f"Hierarchy: {err}" for err in composed_errors]
            attempt_errors += [f"Hierarchy: {err}" for err in analysis.errors]
            attempt_errors += [f"Calls: {err}" for err in subtask_errors]
            plan_errors = [f"Plan: {err}" for err in plan_parse_errors]

            base_valid_any = base_valid_any or analysis.base_pattern_valid
            hierarchy_valid_any = hierarchy_valid_any or (analysis.valid and analysis.max_level >= 2)
            max_level_seen = max(max_level_seen, analysis.max_level)
            last_mapping_count_by_level = dict(analysis.mapping_count_by_level)
            for err in analysis.errors:
                if err not in hierarchy_errors_seen:
                    hierarchy_errors_seen.append(err)
            parse_errors.extend(attempt_errors + plan_errors)

            if attempt_errors or plan_errors or not subtasks:
                combined = attempt_errors + plan_errors
                feedback = "Hierarchy or plan could not be parsed: " + "; ".join(combined)
                # The plan carries no function calls, so a parsing failure in the
                # hierarchy is the hierarchy planner's. Only a malformed plan is the
                # planner's.
                owner = OWNER_DECISION if plan_errors else OWNER_HIERARCHY
                route(owner)
                stage_counts["router_check_count"] += 1
                attempt["router_check"] = {"result": "NO", "owner": owner, "reason": feedback}
                attempt["verdict"] = "REPLAN"
                attempt["feedback_out"] = feedback
                attempts.append(attempt)
                continue

            plan_valid, plan_reason, validated_subtasks = validate_dynamic_plan(
                task=task,
                current_state=current_state,
                subtasks=subtasks,
                mappings=mappings,
                levels=analysis.levels,
            )

            stage_counts["router_check_count"] += 1
            if not plan_valid:
                # Deterministic failure. By construction the plan contains no calls,
                # so no model call is needed to attribute this one.
                feedback = f"Symbolic validation rejected the hierarchy: {plan_reason}"
                parse_errors.append(f"Symbolic: {plan_reason}")
                route(OWNER_HIERARCHY)
                attempt["router_check"] = {
                    "result": "NO",
                    "owner": OWNER_HIERARCHY,
                    "reason": plan_reason,
                    "source": "symbolic",
                }
                attempt["verdict"] = "REPLAN"
                attempt["feedback_out"] = feedback
                attempts.append(attempt)
                continue

            model_call_count += 1
            stage_counts["router_llm_call_count"] += 1
            router_output = client.generate(
                system=SYSTEM_ROUTER,
                prompt=build_router_prompt(
                    task=task,
                    scene_json=scene_json,
                    state_output=state_output,
                    plan_output=plan_output,
                    hierarchy_output=hierarchy_output,
                    symbolic_reason=plan_reason,
                ),
                max_tokens=max_tokens,
                reasoning_effort=stage_reasoning_effort(SYSTEM_ROUTER, reasoning_effort),
            )
            last_outputs["router_output"] = router_output
            attempt["stage_outputs"]["router_output"] = router_output
            no_mistake, owner, router_reason = parse_router_verdict(router_output)
            if not no_mistake:
                feedback = f"InnerBot router assigned the mistake to {owner}: {router_reason}"
                parse_errors.append(f"Router: {router_reason}")
                route(owner)
                attempt["router_check"] = {
                    "result": "NO",
                    "owner": owner,
                    "reason": router_reason,
                    "source": "llm",
                }
                attempt["verdict"] = "REPLAN"
                attempt["feedback_out"] = feedback
                attempts.append(attempt)
                continue

            attempt["router_check"] = {"result": "YES", "owner": "NA", "reason": router_reason}
            descriptions = {
                int(item["subtask_index"]): str(item["description"]) for item in plan_subtasks
            }
            replan_required = False
            solved = False

            for validated in validated_subtasks:
                subtask_index = validated["subtask_index"]
                subtask_calls = validated["calls"]
                h0_calls = validated["h0_calls"]
                moves = validated["moves"]
                prev_state_for_outer = build_scene_description(task, current_state)

                total_top_level_count += len(subtask_calls)
                total_h0_count += len(h0_calls)
                for level, count in validated["level_counts"].items():
                    level_totals[level] = level_totals.get(level, 0) + count
                high_level_plan.extend(str(call) for call in subtask_calls)
                expanded_h0_plan.extend(str(call) for call in h0_calls)

                executed_this_subtask: List[Tuple[str, str]] = []
                for source, target in moves:
                    move_number = len(executed_moves) + 1
                    ok, reason = apply_hanoi_move(task, current_state, source, target, move_number)
                    if not ok:
                        last_illegal_reason = reason
                        feedback = (
                            f"Recoverable execution error at move {move_number}: {reason}. "
                            f"Current state is {current_state}. Rebuild the hierarchy from this state."
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
                        route(OWNER_HIERARCHY)
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
                # The planner now produces a real description per subtask, so the
                # OuterBot no longer has to be handed a synthesised call list.
                subtask_nl = descriptions.get(
                    subtask_index,
                    f"Execute subtask {subtask_index} with calls: "
                    + ", ".join(str(call) for call in subtask_calls),
                )
                outerbot_output = client.generate(
                    system=SYSTEM_OUTERBOT,
                    prompt=build_outerbot_prompt(
                        task=task,
                        env_constraint=build_goal_description(task)["constraint_spatial_relations"],
                        subtask_nl=subtask_nl,
                        prev_state=prev_state_for_outer,
                        curr_state=build_scene_description(task, current_state),
                        subtask_goal_state=subtask_goal_state,
                        final_goal_state=build_scene_description(task, task.goal),
                    ),
                    max_tokens=max_tokens,
                    reasoning_effort=stage_reasoning_effort(SYSTEM_OUTERBOT, reasoning_effort),
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
                if outer_verdict in {"SUBTASK SUCCESS", "EXECUTE REMAINING ACTIONS"}:
                    continue
                if outer_verdict in {"RECOVERABLE", "NON-RECOVERABLE"}:
                    # The OuterBot's finding goes to the router, not straight back to
                    # a planner. Same code path as the pre-execution check.
                    execution_feedback = (
                        f"OuterBot reported {outer_verdict} after subtask {subtask_index}: "
                        f"{outer_reason}. Current state is {current_state}."
                    )
                    model_call_count += 1
                    stage_counts["router_check_count"] += 1
                    stage_counts["router_llm_call_count"] += 1
                    recheck_output = client.generate(
                        system=SYSTEM_ROUTER,
                        prompt=build_router_prompt(
                            task=task,
                            scene_json=build_scene_description(task, current_state),
                            state_output=state_output,
                            plan_output=plan_output,
                            hierarchy_output=hierarchy_output,
                            execution_feedback=execution_feedback,
                        ),
                        max_tokens=max_tokens,
                        reasoning_effort=stage_reasoning_effort(SYSTEM_ROUTER, reasoning_effort),
                    )
                    last_outputs["router_output"] = recheck_output
                    _, recheck_owner, recheck_reason = parse_router_verdict(recheck_output)
                    route(recheck_owner)
                    attempt["events"][-1]["router_owner"] = recheck_owner
                    attempt["events"][-1]["router_reason"] = recheck_reason
                    feedback = f"{execution_feedback} Router assigned this to {recheck_owner}: {recheck_reason}"
                    replan_required = True
                    if outer_verdict == "NON-RECOVERABLE":
                        last_illegal_reason = outer_reason
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
            route(OWNER_BOTH)
            attempt["verdict"] = "REPLAN"
            attempt["feedback_out"] = feedback
            attempts.append(attempt)
        except TruncatedResponseError as exc:
            attempts.append(
                {
                    "attempt_index": attempt_index,
                    "input_state": {peg: list(stack) for peg, stack in current_state.items()},
                    "feedback_in": feedback,
                    "events": [],
                    "verdict": "REPLAN",
                    "feedback_out": f"Truncated: {exc}",
                }
            )
            feedback = f"Truncated: {exc} Retry with a more concise response."
            continue

    replan_count = sum(1 for attempt in attempts[:-1] if attempt.get("verdict") == "REPLAN")
    if current_state == task.goal:
        last_illegal_reason = None

    h1_call_count, composed_call_count = legacy_call_counts(level_totals)
    final_analysis = FinalAnalysis(
        max_level=max_level_seen,
        base_pattern_valid=base_valid_any,
        hierarchy_valid=hierarchy_valid_any,
        errors=hierarchy_errors_seen,
        mapping_count_by_level=last_mapping_count_by_level,
    )
    score = score_from_execution(
        task=task,
        final_state=current_state,
        moves=executed_moves,
        high_level_plan=high_level_plan,
        expanded_h0_plan=expanded_h0_plan,
        h1_valid=base_valid_any,
        h2_valid=hierarchy_valid_any,
        h1_call_count=h1_call_count,
        h2_call_count=composed_call_count,
        h0_call_count=total_h0_count,
        top_level_call_count=total_top_level_count,
        parse_errors=parse_errors,
        illegal_reason=last_illegal_reason,
    )

    # Back-compat aliases so build_metrics and the existing figure scripts see
    # the stage keys they already know about.
    stage_counts["decision_count"] = stage_counts["plan_generation_count"]
    stage_counts["h2_generation_count"] = stage_counts["hierarchy_generation_count"]
    stage_counts["innerbot_plan_check_count"] = stage_counts["router_check_count"]
    stage_counts["innerbot_plan_llm_call_count"] = stage_counts["router_llm_call_count"]

    return {
        "verifier_mode": "llm",
        "model_call_count": model_call_count,
        "replan_count": replan_count,
        "termination_reason": termination_reason,
        "stage_counts": stage_counts,
        "score": score,
        "outputs": last_outputs,
        "attempts": attempts,
        "extra_metrics": build_extra_metrics(final_analysis, level_totals, router_attributions),
    }


class FinalAnalysis:
    """Run-level rollup of per-attempt hierarchy analyses."""

    def __init__(
        self,
        max_level: int,
        base_pattern_valid: bool,
        hierarchy_valid: bool,
        errors,
        mapping_count_by_level: Optional[Dict[int, int]] = None,
    ):
        self.max_level = max_level
        self.base_pattern_valid = base_pattern_valid
        self.hierarchy_valid = hierarchy_valid
        self.mapping_count_by_level: Dict[int, int] = dict(mapping_count_by_level or {})
        self.errors = list(errors)

    @property
    def valid(self) -> bool:
        return self.hierarchy_valid


def build_extra_metrics(analysis, level_totals, router_attributions) -> Dict[str, object]:
    payload = hierarchy_metrics(analysis, level_totals)
    # h1_valid / h2_valid / h1_call_count / h2_call_count already reach
    # metrics.json through the score, so only the new keys are passed through.
    for legacy_key in ("h1_valid", "h2_valid", "h1_call_count", "h2_call_count"):
        payload.pop(legacy_key, None)
    payload["max_hierarchy_level"] = analysis.max_level
    payload["router_attributions"] = list(router_attributions)
    payload["router_attribution_counts"] = {
        owner: router_attributions.count(owner)
        for owner in (OWNER_DECISION, OWNER_HIERARCHY, OWNER_BOTH)
    }
    return payload


def validate_dynamic_plan(
    task,
    current_state: Dict[str, List[str]],
    subtasks,
    mappings,
    levels: Dict[str, int],
) -> Tuple[bool, str, List[Dict[str, object]]]:
    """Level-generic counterpart of hanoi_benchmark.validate_symbolic_plan."""
    simulated_state = {peg: list(stack) for peg, stack in current_state.items()}
    validated_subtasks: List[Dict[str, object]] = []
    simulated_move_count = 0

    for subtask_index, subtask_calls in enumerate(subtasks, start=1):
        level_counts = count_calls_by_level(subtask_calls, mappings, levels)
        h0_calls, expand_errors = expand_hierarchy(subtask_calls, mappings)
        if expand_errors:
            return False, "Hierarchy expansion failed: " + "; ".join(expand_errors), validated_subtasks

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
                "level_counts": level_counts,
                "projected_state": {peg: list(stack) for peg, stack in simulated_state.items()},
            }
        )

    return True, "N/A", validated_subtasks


def new_stage_counts() -> Dict[str, int]:
    return {
        "scene_descriptor_count": 0,
        "state_descriptor_count": 0,
        "h1_generation_count": 0,
        "plan_generation_count": 0,
        "hierarchy_generation_count": 0,
        "innerbot_state_check_count": 0,
        "innerbot_state_llm_call_count": 0,
        "router_check_count": 0,
        "router_llm_call_count": 0,
        "outerbot_check_count": 0,
        "outerbot_llm_call_count": 0,
        "executed_subtask_count": 0,
    }


if __name__ == "__main__":
    raise SystemExit(main())
