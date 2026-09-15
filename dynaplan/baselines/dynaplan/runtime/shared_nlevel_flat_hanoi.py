"""Flat-to-flat Tower of Hanoi adapter for the shared n-level pipeline.

This module deliberately contains domain semantics only.  Retry policy, model
calling, routing, projection, execution, and metric accumulation live in
``shared_nlevel_pipeline``.  The adapter reuses the exact Flat Hanoi prompts,
parsers, hierarchy expansion, transition, and scoring functions used by
``flat_dynamic_hierarchy_benchmark.py``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from dynamic_scoring import (
    OWNER_BOTH,
    analyze_hierarchy,
    count_calls_by_level,
    expand_hierarchy,
    legacy_call_counts,
    parse_plan_subtasks,
    parse_router_verdict,
)
from flat_dynamic_prompts import (
    build_hierarchy_planner_prompt,
    build_plan_prompt,
    build_router_prompt,
)
from flat_hanoi_benchmark import parse_innerbot_verdict, parse_outerbot_verdict
from flat_hanoi_scoring import score_from_execution
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
    FunctionCall,
    apply_hanoi_move,
    extract_moves_from_h0,
    parse_mappings,
    parse_subtask_plans,
)
from shared_nlevel_pipeline import (
    ArtifactCheck,
    CompiledHierarchy,
    FinalScoreContext,
    HierarchyStats,
    LocalArtifact,
    NLevelDomainAdapter,
    OuterVerdict,
    PlannedSubtask,
    RouterVerdict,
    StageRequest,
    TransitionResult,
)


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

_REASONING_AT_BASE = {
    "decision",
    "hierarchy_planner",
    "innerbot_state",
    "innerbot_router",
}


def _copy_stacks(state: Mapping[str, Sequence[str]]) -> Dict[str, List[str]]:
    return {peg: list(stack) for peg, stack in state.items()}


def _errors(prefix: str, values: Iterable[str]) -> List[str]:
    return [f"{prefix}: {value}" for value in values]


class FlatHanoiNLevelAdapter(NLevelDomainAdapter):
    """Domain hooks reproducing the existing dynamic Flat Hanoi pipeline."""

    def initial_state(self, task: Any) -> Dict[str, List[str]]:
        return _copy_stacks(task.initial)

    def copy_state(self, task: Any, state: Mapping[str, Sequence[str]]) -> Dict[str, List[str]]:
        del task
        return _copy_stacks(state)

    def snapshot_state(
        self, task: Any, state: Mapping[str, Sequence[str]]
    ) -> Dict[str, List[str]]:
        del task
        return _copy_stacks(state)

    def render_state(self, task: Any, state: Mapping[str, Sequence[str]]) -> Dict[str, object]:
        return build_scene_description(task, _copy_stacks(state))

    def goal_reached(self, task: Any, state: Mapping[str, Sequence[str]]) -> bool:
        return _copy_stacks(state) == task.goal

    # ``is_goal`` is retained as a compatibility spelling for early versions
    # of the shared engine.  Both names implement the same deterministic gate.
    def is_goal(self, task: Any, state: Mapping[str, Sequence[str]]) -> bool:
        return self.goal_reached(task, state)

    def fixed_state_descriptor(
        self,
        task: Any,
        state: Mapping[str, Sequence[str]],
        scene: Mapping[str, object],
    ) -> LocalArtifact:
        del state, scene
        return LocalArtifact(
            "```start_flag\n" + as_json(build_goal_description(task)) + "\n```end_flag"
        )

    def state_descriptor_request(
        self,
        task: Any,
        state: Mapping[str, Sequence[str]],
        scene: Mapping[str, object],
        previous_state_output: str,
        feedback: str,
    ) -> StageRequest:
        del state
        return StageRequest(
            stage="state_descriptor",
            system=SYSTEM_STATE,
            prompt=build_state_prompt(
                task,
                dict(scene),
                previous_state_output=previous_state_output,
                feedback=feedback or "N/A",
            ),
        )

    def validate_state_descriptor(
        self,
        task: Any,
        state: Mapping[str, Sequence[str]],
        scene: Mapping[str, object],
        output: str,
    ) -> ArtifactCheck:
        # The legacy Flat pipeline delegates this semantic check to InnerBot;
        # it has no additional deterministic state-descriptor parser.
        del task, state, scene
        return ArtifactCheck(valid=True, value=output)

    def inner_state_request(
        self,
        task: Any,
        state: Mapping[str, Sequence[str]],
        scene: Mapping[str, object],
        state_output: str,
    ) -> StageRequest:
        del state
        return StageRequest(
            stage="innerbot_state",
            system=SYSTEM_INNERBOT_STATE,
            prompt=build_innerbot_state_prompt(task, dict(scene), state_output),
        )

    def parse_inner_state(self, output: str) -> Tuple[bool, str]:
        return parse_innerbot_verdict(output)

    def h1_source(
        self,
        task: Any,
        state: Mapping[str, Sequence[str]],
        scene: Mapping[str, object],
        feedback: str,
    ) -> StageRequest:
        del task, state, feedback
        return StageRequest(
            stage="h1",
            system=SYSTEM_H1,
            prompt=build_h1_prompt(dict(scene)),
        )

    def decision_request(
        self,
        task: Any,
        state: Mapping[str, Sequence[str]],
        scene: Mapping[str, object],
        state_output: str,
        h1_output: str,
        feedback: str,
    ) -> StageRequest:
        del state
        return StageRequest(
            stage="decision",
            system=SYSTEM_PLAN,
            prompt=build_plan_prompt(
                task,
                dict(scene),
                state_output,
                h1_output,
                feedback=feedback,
            ),
        )

    def parse_decision(self, task: Any, output: str) -> ArtifactCheck:
        del task
        subtasks, errors = parse_plan_subtasks(output)
        return ArtifactCheck(
            valid=bool(subtasks) and not errors,
            value=tuple(subtasks),
            errors=tuple(errors),
        )

    def hierarchy_request(
        self,
        task: Any,
        state: Mapping[str, Sequence[str]],
        scene: Mapping[str, object],
        state_output: str,
        h1_output: str,
        decision_output: str,
        feedback: str,
        include_code_block: bool,
    ) -> StageRequest:
        del state
        return StageRequest(
            stage="hierarchy_planner",
            system=SYSTEM_HIERARCHY,
            prompt=build_hierarchy_planner_prompt(
                task=task,
                scene_json=dict(scene),
                state_output=state_output,
                h1_output=h1_output,
                plan_output=decision_output,
                feedback=feedback,
                include_code_block=include_code_block,
            ),
        )

    def compile_hierarchy(
        self,
        task: Any,
        state: Mapping[str, Sequence[str]],
        h1_output: str,
        decision_output: str,
        decision: Sequence[Mapping[str, object]],
        hierarchy_output: str,
    ) -> ArtifactCheck:
        del task, state, decision_output

        h1_mappings, h1_errors = parse_mappings(h1_output)
        composed_mappings, composed_errors = parse_mappings(hierarchy_output)
        mappings = {**h1_mappings, **composed_mappings}
        analysis = analyze_hierarchy(mappings)
        subtask_calls, subtask_errors = parse_subtask_plans(hierarchy_output)

        errors: List[str] = []
        errors.extend(_errors("H1", h1_errors))
        errors.extend(_errors("Hierarchy", composed_errors))
        errors.extend(_errors("Hierarchy", analysis.errors))
        errors.extend(_errors("Calls", subtask_errors))

        descriptions = {
            int(item["subtask_index"]): str(item["description"])
            for item in decision
            if "subtask_index" in item and "description" in item
        }
        planned: List[PlannedSubtask] = []
        if not errors:
            for index, calls in enumerate(subtask_calls, start=1):
                level_counts = count_calls_by_level(calls, mappings, analysis.levels)
                h0_calls, expand_errors = expand_hierarchy(calls, mappings)
                errors.extend(_errors("Expand", expand_errors))
                actions, action_errors = extract_moves_from_h0(h0_calls)
                errors.extend(_errors("H0", action_errors))
                planned.append(
                    PlannedSubtask(
                        index=index,
                        description=descriptions.get(
                            index,
                            "Execute subtask "
                            f"{index} with calls: {', '.join(str(call) for call in calls)}",
                        ),
                        top_level_calls=tuple(calls),
                        h0_calls=tuple(h0_calls),
                        actions=tuple(actions),
                        level_counts=dict(level_counts),
                    )
                )

        stats = HierarchyStats(
            max_level=analysis.max_level,
            base_pattern_valid=analysis.base_pattern_valid,
            hierarchy_valid=analysis.valid and analysis.max_level >= 2,
            mapping_count_by_level=dict(analysis.mapping_count_by_level),
            errors=tuple(analysis.errors),
        )
        compiled = CompiledHierarchy(subtasks=tuple(planned), stats=stats)
        return ArtifactCheck(
            valid=bool(planned) and not errors,
            value=compiled,
            errors=tuple(errors),
            metadata={"mappings": mappings, "levels": dict(analysis.levels)},
        )

    def validate_projected_subtask(
        self,
        task: Any,
        decision: Sequence[Mapping[str, object]],
        subtask: PlannedSubtask,
        projected_state: Mapping[str, Sequence[str]],
        is_last: bool,
    ) -> ArtifactCheck:
        # Legacy semantics do not parse/compare DecisionBot's free-form JSON
        # checkpoint.  Legal projection is authoritative; the OuterBot judges
        # checkpoint meaning after the subtask is committed.
        del task, decision, subtask, is_last
        return ArtifactCheck(valid=True, value=_copy_stacks(projected_state))

    def router_request(
        self,
        task: Any,
        state: Mapping[str, Sequence[str]],
        scene: Mapping[str, object],
        state_output: str,
        decision_output: str,
        hierarchy_output: str,
        projection: Any,
        execution_feedback: Optional[str] = None,
    ) -> StageRequest:
        del state
        symbolic_reason = getattr(projection, "reason", "N/A")
        return StageRequest(
            stage="innerbot_router",
            system=SYSTEM_ROUTER,
            prompt=build_router_prompt(
                task=task,
                scene_json=dict(scene),
                state_output=state_output,
                plan_output=decision_output,
                hierarchy_output=hierarchy_output,
                symbolic_reason=symbolic_reason,
                execution_feedback=execution_feedback or "",
            ),
        )

    def parse_router(self, output: str) -> RouterVerdict:
        no_mistake, owner, reason = parse_router_verdict(output)
        return RouterVerdict(no_mistake=no_mistake, owner=owner or OWNER_BOTH, reason=reason)

    def apply_action(
        self,
        task: Any,
        state: Mapping[str, Sequence[str]],
        action: Tuple[str, str],
        action_index: int,
    ) -> TransitionResult:
        next_state = _copy_stacks(state)
        source, target = action
        ok, reason = apply_hanoi_move(task, next_state, source, target, action_index)
        return TransitionResult(
            ok=ok,
            state=next_state,
            reason=reason or "N/A",
            metadata={"source": source, "target": target},
        )

    def outer_request(
        self,
        task: Any,
        decision: Sequence[Mapping[str, object]],
        hierarchy: CompiledHierarchy,
        subtask: Any,
        previous_state: Mapping[str, Sequence[str]],
        current_state: Mapping[str, Sequence[str]],
        is_last: bool,
    ) -> StageRequest:
        del decision, hierarchy
        plan = getattr(subtask, "plan", subtask)
        projected_state = getattr(subtask, "projected_state", current_state)
        description = getattr(plan, "description", "") or (
            f"Execute subtask {plan.index} with calls: "
            + ", ".join(self.format_call(call) for call in plan.top_level_calls)
        )
        subtask_goal_state = (
            build_scene_description(task, task.goal)
            if is_last
            else build_scene_description(task, _copy_stacks(projected_state))
        )
        return StageRequest(
            stage="outerbot",
            system=SYSTEM_OUTERBOT,
            prompt=build_outerbot_prompt(
                task=task,
                env_constraint=build_goal_description(task)["constraint_spatial_relations"],
                subtask_nl=description,
                prev_state=build_scene_description(task, _copy_stacks(previous_state)),
                curr_state=build_scene_description(task, _copy_stacks(current_state)),
                subtask_goal_state=subtask_goal_state,
                final_goal_state=build_scene_description(task, task.goal),
            ),
        )

    def parse_outer(self, output: str) -> OuterVerdict:
        status, reason = parse_outerbot_verdict(output)
        return OuterVerdict(status=status, reason=reason)

    def format_action(self, action: Tuple[str, str]) -> str:
        source, target = action
        return f"MoveSingleRing({source}, {target})"

    def format_call(self, call: FunctionCall) -> str:
        return str(call)

    def reasoning_effort_for(self, stage: str, base_effort: Optional[str]) -> Optional[str]:
        if base_effort is None:
            return None
        return base_effort if stage in _REASONING_AT_BASE else "low"

    def final_score(self, context: FinalScoreContext) -> Any:
        h1_call_count, h2_call_count = legacy_call_counts(context.level_totals)
        return score_from_execution(
            task=context.task,
            final_state=_copy_stacks(context.final_state),
            moves=list(context.executed_actions),
            high_level_plan=list(context.high_level_plan),
            expanded_h0_plan=list(context.expanded_h0_plan),
            h1_valid=context.base_valid_any,
            h2_valid=context.hierarchy_valid_any,
            h1_call_count=h1_call_count,
            h2_call_count=h2_call_count,
            h0_call_count=context.total_h0_count,
            top_level_call_count=context.total_top_level_count,
            parse_errors=list(context.parse_errors),
            illegal_reason=context.last_illegal_reason,
        )


# Concise aliases for callers and the protocol conformance assertion below.
FlatHanoiAdapter = FlatHanoiNLevelAdapter
assert issubclass(FlatHanoiNLevelAdapter, NLevelDomainAdapter)


__all__ = [
    "FlatHanoiAdapter",
    "FlatHanoiNLevelAdapter",
    "SYSTEM_STATE",
    "SYSTEM_INNERBOT_STATE",
    "SYSTEM_H1",
    "SYSTEM_PLAN",
    "SYSTEM_HIERARCHY",
    "SYSTEM_ROUTER",
    "SYSTEM_OUTERBOT",
]
