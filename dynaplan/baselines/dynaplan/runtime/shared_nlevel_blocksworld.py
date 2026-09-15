"""LexiCon Blocksworld adapter for the shared N-level control loop.

Only domain contracts live here.  The v5 controller remains the unchanged
``shared_nlevel_verified_repair_pipeline.run_shared_nlevel_loop``.  Primitive
prefixes are replayed against each released compiled-PDDL problem, so public
state, temporal-monitor state, applicability, and final validity are
deterministic.  Oracle plans and optimal lengths are used only by final score.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from unified_planning.io import PDDLReader
from unified_planning.plans import ActionInstance
from unified_planning.shortcuts import SequentialSimulator

import shared_nlevel_lexicon as common
from lexicon_blocksworld_task import (
    PRIMITIVE_SIGNATURES,
    LexiconBlocksworldTask,
    PlanVerification,
    PrimitiveAction,
    validate_ground_fact,
    validate_primitive_action,
    verify_plan,
)
from shared_nlevel_blocksworld_prompts import (
    SYSTEM_DECISION,
    SYSTEM_H1,
    SYSTEM_HIERARCHY,
    SYSTEM_INNERBOT_STATE,
    SYSTEM_OUTERBOT,
    SYSTEM_ROUTER,
    SYSTEM_STATE_DESCRIPTOR,
    decision_prompt,
    h1_prompt,
    hierarchy_prompt,
    innerbot_state_prompt,
    outerbot_prompt,
    router_prompt,
    state_descriptor_prompt,
)
from shared_nlevel_pipeline import (
    ArtifactCheck,
    CompiledHierarchy,
    HierarchyStats,
    OuterVerdict,
    PlannedSubtask,
    RouterVerdict,
    StageRequest,
    TransitionResult,
)


# The hierarchy wire grammar and immutable planning artifacts are deliberately
# identical to Logistics.  Reusing these pure types/parsers keeps the two
# adapters comparable without mutating Logistics module globals.
LexiconCall = common.LexiconCall
LexiconMapping = common.LexiconMapping
LexiconH1Library = common.LexiconH1Library
LexiconCheckpoint = common.LexiconCheckpoint
LexiconDecisionSubtask = common.LexiconDecisionSubtask
LexiconDecisionPlan = common.LexiconDecisionPlan
LexiconExecutionState = common.LexiconExecutionState
_ReplayResult = common._ReplayResult

_MAPPING_BLOCK_RE = common._MAPPING_BLOCK_RE
_SUBTASK_CALLS_RE = common._SUBTASK_CALLS_RE
_STATE_BLOCK_RE = common._STATE_BLOCK_RE
_NEGATED_FACT_RE = common._NEGATED_FACT_RE

PRIMITIVE_ARITIES: Dict[str, int] = {
    name: len(signature) for name, signature in PRIMITIVE_SIGNATURES.items()
}
_H1_TO_PRIMITIVE: Dict[str, str] = {
    "Pickup": "pickup",
    "Putdown": "putdown",
    "Stack": "stack",
    "Unstack": "unstack",
}
_TYPE_PARENT: Dict[str, str] = {"block": "object"}


def _unique(values: Iterable[str]) -> List[str]:
    return common._unique(values)


def _model_safe_evaluator_text(value: object) -> str:
    return common._model_safe_evaluator_text(value)


def _is_subtype(actual: str, expected: str) -> bool:
    if actual == expected:
        return True
    current = actual
    seen: set[str] = set()
    while current in _TYPE_PARENT and current not in seen:
        seen.add(current)
        current = _TYPE_PARENT[current]
        if current == expected:
            return True
    return False


def _object_type_map(task: LexiconBlocksworldTask) -> Dict[str, str]:
    return {
        object_name: type_name
        for type_name, object_names in task.objects_by_type.items()
        for object_name in object_names
    }


def _model_task_text(task: LexiconBlocksworldTask) -> str:
    return common._strip_stage_conflicting_output_instruction(task.prompt_text())


def _validate_h1_library(text: str) -> ArtifactCheck:
    mappings, errors = common._parse_mappings(text, context="H1")
    if set(mappings) != set(_H1_TO_PRIMITIVE):
        errors.append("H1 must define exactly " + ", ".join(_H1_TO_PRIMITIVE))
    for h1_name, primitive_name in _H1_TO_PRIMITIVE.items():
        mapping = mappings.get(h1_name)
        if mapping is None:
            continue
        expected_types = PRIMITIVE_SIGNATURES[primitive_name]
        if len(mapping.params) != len(expected_types):
            errors.append(
                f"{h1_name} has {len(mapping.params)} parameters; expected "
                f"{len(expected_types)}"
            )
        if len(mapping.calls) != 1 or mapping.calls[0].name != primitive_name:
            errors.append(
                f"{h1_name} must contain exactly one {primitive_name} call"
            )
            continue
        if mapping.calls[0].args != mapping.params:
            errors.append(
                f"{h1_name} must pass its parameters to {primitive_name} in exact order"
            )
    fixed = {
        name: LexiconMapping(mapping.name, mapping.params, mapping.calls, fixed_h1=True)
        for name, mapping in mappings.items()
    }
    return ArtifactCheck(
        valid=not errors,
        value=LexiconH1Library(fixed) if not errors else None,
        errors=tuple(_unique(errors)),
        metadata={"mapping_count": len(mappings)},
    )


def _parse_decision(task: LexiconBlocksworldTask, text: str) -> ArtifactCheck:
    descriptions_found = list(common._SUBTASK_DESCRIPTION_RE.finditer(text or ""))
    checkpoints_found = list(common._SUBTASK_CHECKPOINT_RE.finditer(text or ""))
    errors: List[str] = []
    descriptions: Dict[int, str] = {}
    raw_checkpoints: Dict[int, str] = {}
    for match in descriptions_found:
        index = int(match.group("index"))
        if index in descriptions:
            errors.append(f"Decision contains duplicate description block {index}")
        descriptions[index] = match.group("body").strip()
    for match in checkpoints_found:
        index = int(match.group("index"))
        if index in raw_checkpoints:
            errors.append(f"Decision contains duplicate checkpoint block {index}")
        raw_checkpoints[index] = match.group("body").strip()

    if not descriptions:
        errors.append("Decision contains no numbered subtask descriptions")
    indices = sorted(set(descriptions) | set(raw_checkpoints))
    expected = list(range(1, len(indices) + 1))
    if indices != expected:
        errors.append(f"Decision subtask ids must be {expected}; got {indices}")
    if set(descriptions) != set(raw_checkpoints):
        errors.append("Every Decision description must have one matching checkpoint")

    subtasks: List[LexiconDecisionSubtask] = []
    covered_constraints: set[int] = set()
    for index in indices:
        description = descriptions.get(index, "").strip()
        if not description:
            errors.append(f"Subtask {index} description is empty")
        if common._contains_executable_action_syntax(description, PRIMITIVE_ARITIES):
            errors.append(f"Subtask {index} description leaks executable action syntax")

        raw_checkpoint = raw_checkpoints.get(index)
        if raw_checkpoint is None:
            continue
        try:
            payload = json.loads(raw_checkpoint)
        except json.JSONDecodeError as error:
            errors.append(f"Subtask {index} checkpoint is not strict JSON: {error}")
            continue
        required_keys = {"required_true", "required_false", "constraints_addressed"}
        if not isinstance(payload, dict) or set(payload) != required_keys:
            errors.append(
                f"Subtask {index} checkpoint must contain exactly {sorted(required_keys)}"
            )
            continue
        true_facts = payload.get("required_true")
        false_facts = payload.get("required_false")
        constraint_indices = payload.get("constraints_addressed")
        if not isinstance(true_facts, list) or any(
            not isinstance(fact, str) for fact in true_facts
        ):
            errors.append(f"Subtask {index} required_true must be a string array")
            continue
        if not isinstance(false_facts, list) or any(
            not isinstance(fact, str) for fact in false_facts
        ):
            errors.append(f"Subtask {index} required_false must be a string array")
            continue
        if not isinstance(constraint_indices, list) or any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in constraint_indices
        ):
            errors.append(
                f"Subtask {index} constraints_addressed must be an integer array"
            )
            continue
        if len(set(true_facts)) != len(true_facts):
            errors.append(f"Subtask {index} required_true contains duplicates")
        if len(set(false_facts)) != len(false_facts):
            errors.append(f"Subtask {index} required_false contains duplicates")
        if set(true_facts) & set(false_facts):
            errors.append(f"Subtask {index} requires the same fact true and false")
        for fact in (*true_facts, *false_facts):
            try:
                validate_ground_fact(task, fact)
            except ValueError as error:
                errors.append(f"Subtask {index} has invalid fact {fact!r}: {error}")
        for fact in false_facts:
            if _NEGATED_FACT_RE.fullmatch(fact):
                errors.append(
                    f"Subtask {index} required_false must contain positive atoms"
                )
        if list(constraint_indices) != sorted(set(constraint_indices)):
            errors.append(
                f"Subtask {index} constraint indices must be sorted and unique"
            )
        for constraint_index in constraint_indices:
            if not 1 <= constraint_index <= len(task.constraints):
                errors.append(
                    f"Subtask {index} constraint {constraint_index} is outside "
                    f"1..{len(task.constraints)}"
                )
            else:
                covered_constraints.add(constraint_index)
        subtasks.append(
            LexiconDecisionSubtask(
                index,
                description,
                LexiconCheckpoint(
                    tuple(true_facts), tuple(false_facts), tuple(constraint_indices)
                ),
            )
        )

    if subtasks:
        final_true = set(subtasks[-1].checkpoint.required_true)
        missing_goals = [goal for goal in task.goals if goal not in final_true]
        if missing_goals:
            errors.append(
                "Final Decision checkpoint is missing task goals: "
                + ", ".join(missing_goals)
            )
    expected_constraints = set(range(1, len(task.constraints) + 1))
    if covered_constraints != expected_constraints:
        errors.append(
            "Decision checkpoints must collectively address every constraint; "
            f"expected {sorted(expected_constraints)}, got {sorted(covered_constraints)}"
        )
    plan = LexiconDecisionPlan(tuple(subtasks))
    return ArtifactCheck(
        valid=not errors,
        value=plan if not errors else None,
        errors=tuple(_unique(errors)),
        metadata={"subtask_count": len(subtasks)},
    )


def _infer_levels(
    mappings: Mapping[str, LexiconMapping],
) -> Tuple[Dict[str, int], List[str]]:
    levels = {name: 1 for name, mapping in mappings.items() if mapping.fixed_h1}
    errors: List[str] = []
    visiting: List[str] = []

    def visit(name: str) -> Optional[int]:
        if name in levels:
            return levels[name]
        if name in PRIMITIVE_ARITIES:
            return 0
        if name in visiting:
            start = visiting.index(name)
            errors.append("Hierarchy cycle: " + " -> ".join((*visiting[start:], name)))
            return None
        mapping = mappings.get(name)
        if mapping is None:
            errors.append(f"Unknown called function {name}")
            return None
        visiting.append(name)
        child_levels = [
            level for call in mapping.calls if (level := visit(call.name)) is not None
        ]
        visiting.pop()
        if not child_levels:
            errors.append(f"Mapping {name} has no resolvable calls")
            return None
        levels[name] = max(child_levels) + 1
        return levels[name]

    for name in sorted(mappings):
        visit(name)
    return levels, _unique(errors)


def _formal_type_requirements(
    mappings: Mapping[str, LexiconMapping], levels: Mapping[str, int]
) -> Tuple[Dict[str, Tuple[frozenset[str], ...]], List[str]]:
    errors: List[str] = []
    requirements: Dict[str, Tuple[frozenset[str], ...]] = {}
    for h1_name, primitive_name in _H1_TO_PRIMITIVE.items():
        if h1_name in mappings:
            requirements[h1_name] = tuple(
                frozenset((type_name,))
                for type_name in PRIMITIVE_SIGNATURES[primitive_name]
            )
    custom_names = sorted(
        (name for name, mapping in mappings.items() if not mapping.fixed_h1),
        key=lambda name: (levels.get(name, 10**9), name),
    )
    for name in custom_names:
        mapping = mappings[name]
        collected: List[set[str]] = [set() for _ in mapping.params]
        positions = {parameter: index for index, parameter in enumerate(mapping.params)}
        for call in mapping.calls:
            target = mappings.get(call.name)
            needed_by_arg = requirements.get(call.name)
            if target is None or needed_by_arg is None:
                continue
            if len(call.args) != len(target.params):
                errors.append(
                    f"{name} calls {call.name} with {len(call.args)} arguments; "
                    f"expected {len(target.params)}"
                )
                continue
            for argument, needed in zip(call.args, needed_by_arg):
                position = positions.get(argument)
                if position is None:
                    errors.append(
                        f"{name} body argument {argument!r} is not a declared parameter"
                    )
                else:
                    collected[position].update(needed)
        for parameter, needed in zip(mapping.params, collected):
            if not needed:
                errors.append(f"{name} has unused parameter {parameter!r}")
            elif not all(_is_subtype("block", expected) for expected in needed):
                errors.append(
                    f"{name} parameter {parameter!r} has incompatible type "
                    f"requirements {sorted(needed)}"
                )
        requirements[name] = tuple(frozenset(values) for values in collected)
    return requirements, _unique(errors)


def _expand_calls(
    calls: Sequence[LexiconCall],
    mappings: Mapping[str, LexiconMapping],
    *,
    max_actions: int = 10_000,
) -> Tuple[List[PrimitiveAction], List[str]]:
    expanded: List[PrimitiveAction] = []
    errors: List[str] = []

    def expand(call: LexiconCall, stack: Tuple[str, ...]) -> None:
        if len(expanded) >= max_actions:
            errors.append(f"Expansion exceeds safety limit of {max_actions} actions")
            return
        if call.name in PRIMITIVE_ARITIES:
            if len(call.args) != PRIMITIVE_ARITIES[call.name]:
                errors.append(
                    f"Primitive {call.name} has {len(call.args)} arguments; "
                    f"expected {PRIMITIVE_ARITIES[call.name]}"
                )
            else:
                expanded.append(PrimitiveAction(call.name, call.args))
            return
        mapping = mappings.get(call.name)
        if mapping is None:
            errors.append(f"Unknown function {call.name}")
            return
        if call.name in stack:
            errors.append("Expansion cycle: " + " -> ".join((*stack, call.name)))
            return
        if len(call.args) != len(mapping.params):
            errors.append(
                f"{call.name} has {len(call.args)} arguments; expected {len(mapping.params)}"
            )
            return
        bindings = dict(zip(mapping.params, call.args))
        for child in mapping.calls:
            bound = tuple(bindings.get(argument, argument) for argument in child.args)
            expand(LexiconCall(child.name, bound), (*stack, call.name))

    for call in calls:
        expand(call, ())
    return expanded, _unique(errors)


def _compile_hierarchy(
    task: LexiconBlocksworldTask,
    h1_output: str,
    decision: LexiconDecisionPlan,
    hierarchy_output: str,
) -> ArtifactCheck:
    errors: List[str] = []
    h1_check = _validate_h1_library(h1_output)
    if not h1_check.valid or not isinstance(h1_check.value, LexiconH1Library):
        return ArtifactCheck.rejected(*(f"H1: {error}" for error in h1_check.errors))

    custom, parse_errors = common._parse_mappings(
        hierarchy_output, context="Hierarchy"
    )
    errors.extend(parse_errors)
    for name in custom:
        if name in _H1_TO_PRIMITIVE or name in PRIMITIVE_ARITIES:
            errors.append(f"Custom mapping {name} collides with H1 or H0")
    mappings: Dict[str, LexiconMapping] = dict(h1_check.value.mappings)
    mappings.update(
        (name, mapping)
        for name, mapping in custom.items()
        if name not in mappings and name not in PRIMITIVE_ARITIES
    )
    for name, mapping in custom.items():
        for call in mapping.calls:
            if call.name in PRIMITIVE_ARITIES:
                errors.append(
                    f"{name} calls raw H0 primitive {call.name}; custom mappings "
                    "must build on H1 or another lower-level mapping"
                )
            if any(argument not in mapping.params for argument in call.args):
                errors.append(
                    f"{name} contains a concrete or unbound body argument in {call}"
                )

    levels, level_errors = _infer_levels(mappings)
    errors.extend(level_errors)
    for name in custom:
        if levels.get(name) is not None and levels[name] < 2:
            errors.append(f"Custom mapping {name} must infer to H2 or deeper")
    formal_requirements, type_errors = _formal_type_requirements(mappings, levels)
    errors.extend(type_errors)
    object_types = _object_type_map(task)

    matches = list(_SUBTASK_CALLS_RE.finditer(hierarchy_output or ""))
    blocks: Dict[int, str] = {}
    block_order: List[int] = []
    for match in matches:
        index = int(match.group("index"))
        block_order.append(index)
        if index in blocks:
            errors.append(f"Hierarchy contains duplicate subtask call block {index}")
        blocks[index] = match.group("body")
    expected_ids = [subtask.index for subtask in decision.subtasks]
    if block_order != expected_ids:
        errors.append(
            f"Hierarchy call blocks must be exactly {expected_ids} in order; "
            f"got {block_order}"
        )

    decision_by_id = decision.by_index()
    planned: List[PlannedSubtask] = []
    total_expanded = 0
    for index in expected_ids:
        raw_block = blocks.get(index)
        if raw_block is None:
            continue
        top_calls, call_errors = common._parse_call_list(
            raw_block, context=f"Hierarchy subtask {index}"
        )
        errors.extend(call_errors)
        for call in top_calls:
            target = mappings.get(call.name)
            if target is None:
                errors.append(f"Subtask {index} calls unknown function {call.name}")
                continue
            if len(call.args) != len(target.params):
                errors.append(
                    f"Subtask {index} calls {call.name} with {len(call.args)} "
                    f"arguments; expected {len(target.params)}"
                )
                continue
            required_types = formal_requirements.get(call.name, ())
            for position, argument in enumerate(call.args):
                actual_type = object_types.get(argument)
                if actual_type is None:
                    errors.append(
                        f"Subtask {index} call {call.name} uses unknown object {argument!r}"
                    )
                elif position < len(required_types) and any(
                    not _is_subtype(actual_type, expected)
                    for expected in required_types[position]
                ):
                    errors.append(
                        f"Subtask {index} argument {argument!r} ({actual_type}) is "
                        f"incompatible with {call.name} parameter {position + 1} "
                        f"requirements {sorted(required_types[position])}"
                    )
        expanded, expansion_errors = _expand_calls(top_calls, mappings)
        errors.extend(
            f"Subtask {index} expansion: {error}" for error in expansion_errors
        )
        for action in expanded:
            try:
                validate_primitive_action(task, action)
            except ValueError as error:
                errors.append(
                    f"Subtask {index} expands to invalid {action.pddl}: {error}"
                )
        total_expanded += len(expanded)
        decision_subtask = decision_by_id[index]
        planned.append(
            PlannedSubtask(
                index=index,
                description=decision_subtask.description,
                top_level_calls=tuple(top_calls),
                h0_calls=tuple(expanded),
                actions=tuple(expanded),
                level_counts=common._count_calls_by_level(top_calls, mappings, levels),
                metadata={"checkpoint": decision_subtask.checkpoint.to_dict()},
            )
        )

    mapping_counts: Dict[int, int] = {}
    for level in levels.values():
        mapping_counts[level] = mapping_counts.get(level, 0) + 1
    max_level = max(levels.values(), default=0)
    top_level_count = sum(len(subtask.top_level_calls) for subtask in planned)
    stats = HierarchyStats(
        max_level=max_level,
        base_pattern_valid=h1_check.valid,
        hierarchy_valid=bool(custom) and max_level >= 2,
        mapping_count_by_level=mapping_counts,
        errors=tuple(_unique(errors)),
        metadata={
            "custom_mapping_count": len(custom),
            "top_level_call_count": top_level_count,
            "expanded_action_count": total_expanded,
            "compression_ratio": (
                round(total_expanded / top_level_count, 6)
                if top_level_count
                else None
            ),
            "unused_custom_mappings": sorted(
                set(custom)
                - {
                    call.name
                    for subtask in planned
                    for call in subtask.top_level_calls
                }
            ),
        },
    )
    compiled = CompiledHierarchy(
        subtasks=tuple(planned),
        stats=stats,
        metadata={
            "mappings": mappings,
            "levels": levels,
            "h1_library": h1_check.value,
        },
    )
    return ArtifactCheck(
        valid=not errors,
        value=compiled if not errors else None,
        errors=tuple(_unique(errors)),
        metadata={
            "max_level": max_level,
            "mapping_count_by_level": mapping_counts,
            "custom_mapping_count": len(custom),
            "top_level_call_count": top_level_count,
            "expanded_action_count": total_expanded,
        },
    )


def _has_constraint_fluent(expression: Any) -> bool:
    return common._has_constraint_fluent(expression)


def _bind_action(problem: Any, action: PrimitiveAction) -> ActionInstance:
    declaration = problem.action(action.name)
    manager = problem.environment.expression_manager
    parameters = tuple(
        manager.ObjectExp(problem.object(argument)) for argument in action.args
    )
    return ActionInstance(declaration, parameters)


def _replay_actions(
    task: LexiconBlocksworldTask, actions: Sequence[PrimitiveAction]
) -> _ReplayResult:
    reader = PDDLReader()
    try:
        if hasattr(task, "compiled_domain_pddl"):
            problem = reader.parse_problem_string(
                str(task.compiled_domain_pddl),
                str(task.compiled_problem_pddl),
            )
        else:
            problem = reader.parse_problem(
                str(task.source_files["compiled_domain.pddl"]),
                str(task.source_files["compiled_problem.pddl"]),
            )
    except Exception as error:
        raise RuntimeError(
            f"Could not load released compiled LexiCon task: {error}"
        ) from error
    simulator = SequentialSimulator(problem)
    state = simulator.get_initial_state()
    for index, raw_action in enumerate(actions, start=1):
        action = (
            raw_action
            if isinstance(raw_action, PrimitiveAction)
            else PrimitiveAction(
                str(getattr(raw_action, "name")), tuple(getattr(raw_action, "args"))
            )
        )
        try:
            validate_primitive_action(task, action)
            bound = _bind_action(problem, action)
        except Exception as error:
            return _ReplayResult(
                False,
                state,
                problem,
                failed_action_index=index,
                failed_action=action,
                failure_kind="action_binding",
                reason=str(error),
            )
        try:
            if not simulator.is_applicable(state, bound):
                conditions, reason = simulator.get_unsatisfied_conditions(state, bound)
                unsatisfied = tuple(str(condition) for condition in conditions)
                constraint_failure = any(
                    _has_constraint_fluent(condition) for condition in conditions
                )
                message = f"Action is inapplicable: {action.pddl}"
                if unsatisfied:
                    message += f"; unsatisfied {list(unsatisfied)}"
                if reason is not None:
                    message += f" ({reason})"
                return _ReplayResult(
                    False,
                    state,
                    problem,
                    failed_action_index=index,
                    failed_action=action,
                    failure_kind=(
                        "constraint" if constraint_failure else "action_precondition"
                    ),
                    reason=message,
                    unsatisfied_conditions=unsatisfied,
                    constraint_failure=constraint_failure,
                )
            next_state = simulator.apply(state, bound)
        except Exception as error:
            return _ReplayResult(
                False,
                state,
                problem,
                failed_action_index=index,
                failed_action=action,
                failure_kind="simulation",
                reason=str(error),
            )
        if next_state is None:
            return _ReplayResult(
                False,
                state,
                problem,
                failed_action_index=index,
                failed_action=action,
                failure_kind="simulation",
                reason=f"Simulator rejected {action.pddl}",
            )
        state = next_state
    return _ReplayResult(True, state, problem)


def _state_truth(state: Any, expression: Any) -> bool:
    return common._state_truth(state, expression)


def _state_facts(
    problem: Any, state: Any, task: LexiconBlocksworldTask
) -> Tuple[str, ...]:
    facts: List[str] = []
    blocks = tuple(task.objects_by_type.get("block", ()))
    clear = problem.fluent("clear")
    ontable = problem.fluent("ontable")
    holding = problem.fluent("holding")
    on = problem.fluent("on")
    for block in blocks:
        obj = problem.object(block)
        if _state_truth(state, clear(obj)):
            facts.append(f"(clear {block})")
        if _state_truth(state, ontable(obj)):
            facts.append(f"(ontable {block})")
        if _state_truth(state, holding(obj)):
            facts.append(f"(holding {block})")
    if _state_truth(state, problem.fluent("handempty")()):
        facts.append("(handempty)")
    for upper in blocks:
        for lower in blocks:
            if _state_truth(state, on(problem.object(upper), problem.object(lower))):
                facts.append(f"(on {upper} {lower})")
    return tuple(sorted(facts))


def _execution_state(
    task: LexiconBlocksworldTask,
    actions: Sequence[PrimitiveAction],
    replay: Optional[_ReplayResult] = None,
) -> LexiconExecutionState:
    replay = replay or _replay_actions(task, actions)
    if not replay.ok:
        raise ValueError(f"Cannot construct state from invalid prefix: {replay.reason}")
    public_facts = _state_facts(replay.problem, replay.state, task)
    monitor_facts = common._monitor_facts(replay.problem, replay.state)
    action_tuple = tuple(actions)
    digest = hashlib.sha256(
        json.dumps(
            {
                "actions": [action.pddl for action in action_tuple],
                "public_facts": public_facts,
                "monitor_facts": monitor_facts,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return LexiconExecutionState(action_tuple, public_facts, monitor_facts, digest)


def _public_state_payload(state: LexiconExecutionState) -> Dict[str, object]:
    return {
        "current_facts": list(state.public_facts),
        "executed_actions": [action.pddl for action in state.executed_actions],
        "state_digest": state.digest,
    }


def _authoritative_model_view(
    task: LexiconBlocksworldTask, state: LexiconExecutionState
) -> Dict[str, object]:
    return {
        "task_id": task.id,
        "objects_by_type": {
            type_name: list(names)
            for type_name, names in sorted(task.objects_by_type.items())
        },
        "current_facts": list(state.public_facts),
        "goals": list(task.goals),
        "constraints": list(task.constraints),
        "executed_actions": [action.pddl for action in state.executed_actions],
    }


def _checkpoint_result(
    state: LexiconExecutionState, checkpoint: LexiconCheckpoint
) -> Tuple[bool, Dict[str, object]]:
    return common._checkpoint_result(state, checkpoint)


def _safe_verification_payload(
    verification: PlanVerification,
) -> Dict[str, object]:
    return common._safe_verification_payload(verification)


def _projection_payload(projection: Any) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "valid": bool(getattr(projection, "valid", False)),
        "reason": _model_safe_evaluator_text(getattr(projection, "reason", "N/A")),
        "failed_subtask_index": getattr(projection, "failed_subtask_index", None),
        "failed_action_index": getattr(projection, "failed_action_index", None),
        "checkpoint_failure": bool(
            getattr(projection, "checkpoint_failure", False)
        ),
    }
    failed_action = getattr(projection, "failed_action", None)
    payload["failed_action"] = (
        failed_action.pddl
        if isinstance(failed_action, PrimitiveAction)
        else str(failed_action) if failed_action is not None else None
    )
    metadata = getattr(projection, "metadata", {})
    if isinstance(metadata, Mapping):
        payload["failure_kind"] = metadata.get("failure_kind")
        payload["constraint_failure"] = metadata.get("constraint_failure")
        payload["unsatisfied_conditions"] = [
            _model_safe_evaluator_text(value)
            for value in metadata.get("unsatisfied_conditions", [])
        ]
    return payload


class SharedNLevelBlocksworldAdapter:
    """Stateless Blocksworld hooks consumed by the shared N-level engine."""

    name = "lexicon-blocksworld"
    verifier_mode = "compiled-pddl"
    state_descriptor_validation_authoritative = True

    def initial_state(self, task: LexiconBlocksworldTask) -> LexiconExecutionState:
        return _execution_state(task, ())

    def copy_state(
        self, task: LexiconBlocksworldTask, state: LexiconExecutionState
    ) -> LexiconExecutionState:
        del task
        return replace(state)

    def snapshot_state(
        self, task: LexiconBlocksworldTask, state: LexiconExecutionState
    ) -> Dict[str, object]:
        del task
        return _public_state_payload(state)

    def render_state(
        self, task: LexiconBlocksworldTask, state: LexiconExecutionState
    ) -> Dict[str, object]:
        return _authoritative_model_view(task, state)

    def goal_reached(
        self, task: LexiconBlocksworldTask, state: LexiconExecutionState
    ) -> bool:
        return verify_plan(task, state.executed_actions).valid

    is_goal = goal_reached

    def fixed_state_descriptor(
        self,
        task: LexiconBlocksworldTask,
        state: LexiconExecutionState,
        scene: object,
    ) -> str:
        del scene
        return (
            "```start_flag\n"
            + json.dumps(_authoritative_model_view(task, state), indent=2, sort_keys=True)
            + "\n```end_flag"
        )

    def state_descriptor_request(
        self,
        task: LexiconBlocksworldTask,
        state: LexiconExecutionState,
        scene: object,
        previous_state_output: str,
        feedback: str,
    ) -> StageRequest:
        del scene, previous_state_output
        view = _authoritative_model_view(task, state)
        return StageRequest(
            stage="state_descriptor",
            system=SYSTEM_STATE_DESCRIPTOR,
            prompt=state_descriptor_prompt(_model_task_text(task), view, feedback),
        )

    def validate_state_descriptor(
        self,
        task: LexiconBlocksworldTask,
        state: LexiconExecutionState,
        scene: object,
        output: str,
    ) -> ArtifactCheck:
        del scene
        match = _STATE_BLOCK_RE.fullmatch(output or "")
        if match is None:
            return ArtifactCheck.rejected(
                "StateDescriptor must be exactly one start_flag/end_flag JSON block"
            )
        try:
            payload = json.loads(match.group("body"))
        except json.JSONDecodeError as error:
            return ArtifactCheck.rejected(f"StateDescriptor JSON: {error}")
        expected = _authoritative_model_view(task, state)
        if payload != expected:
            fields = [
                key
                for key in sorted(
                    set(expected) | (set(payload) if isinstance(payload, dict) else set())
                )
                if not isinstance(payload, dict) or payload.get(key) != expected.get(key)
            ]
            return ArtifactCheck.rejected(
                f"StateDescriptor differs in fields: {fields}",
                metadata={"differing_fields": fields},
            )
        return ArtifactCheck.accepted(payload)

    def inner_state_request(
        self,
        task: LexiconBlocksworldTask,
        state: LexiconExecutionState,
        scene: object,
        state_output: str,
    ) -> StageRequest:
        del scene
        return StageRequest(
            stage="innerbot_state",
            system=SYSTEM_INNERBOT_STATE,
            prompt=innerbot_state_prompt(
                _authoritative_model_view(task, state), state_output
            ),
        )

    def parse_inner_state(self, output: str) -> Tuple[bool, str]:
        return common._parse_inner_verdict(output)

    def h0_spec(self, task: LexiconBlocksworldTask) -> Dict[str, object]:
        del task
        return {
            "actions": [
                {
                    "name": name,
                    "arity": PRIMITIVE_ARITIES[name],
                    "parameter_types": list(PRIMITIVE_SIGNATURES[name]),
                }
                for name in PRIMITIVE_ARITIES
            ]
        }

    def h1_source(
        self,
        task: LexiconBlocksworldTask,
        state: LexiconExecutionState,
        scene: object,
        feedback: str,
    ) -> StageRequest:
        del scene, feedback
        return StageRequest(
            stage="h1",
            system=SYSTEM_H1,
            prompt=h1_prompt(
                _model_task_text(task),
                self.h0_spec(task),
                _authoritative_model_view(task, state),
            ),
        )

    def validate_h1(self, task: LexiconBlocksworldTask, output: str) -> ArtifactCheck:
        del task
        return _validate_h1_library(output)

    def canonicalize_h1(
        self, task: LexiconBlocksworldTask, output: str, check: ArtifactCheck
    ) -> str:
        del task, output
        library = check.value
        if not isinstance(library, LexiconH1Library):
            raise TypeError("validated Blocksworld H1 did not produce LexiconH1Library")
        mappings = []
        for name in sorted(library.mappings):
            mapping = library.mappings[name]
            header = f"{mapping.name}({', '.join(mapping.params)})"
            body = ", ".join(str(call) for call in mapping.calls)
            mappings.append(f"{header} = [{body}]")
        return "```start_mapping\n" + ",\n".join(mappings) + "\n```end_mapping"

    def decision_request(
        self,
        task: LexiconBlocksworldTask,
        state: LexiconExecutionState,
        scene: object,
        state_output: str,
        h1_output: str,
        feedback: str,
    ) -> StageRequest:
        del state, scene
        return StageRequest(
            stage="decision",
            system=SYSTEM_DECISION,
            prompt=decision_prompt(
                _model_task_text(task), state_output, h1_output, feedback
            ),
        )

    def parse_decision(
        self, task: LexiconBlocksworldTask, output: str
    ) -> ArtifactCheck:
        return _parse_decision(task, output)

    def hierarchy_request(
        self,
        task: LexiconBlocksworldTask,
        state: LexiconExecutionState,
        scene: object,
        state_output: str,
        h1_output: str,
        decision_output: str,
        feedback: str,
        include_code_block: bool,
    ) -> StageRequest:
        del state, scene
        return StageRequest(
            stage="hierarchy_planner",
            system=SYSTEM_HIERARCHY,
            prompt=hierarchy_prompt(
                _model_task_text(task),
                state_output,
                h1_output,
                decision_output,
                feedback,
                include_code_block=include_code_block,
            ),
        )

    def compile_hierarchy(
        self,
        task: LexiconBlocksworldTask,
        state: LexiconExecutionState,
        h1_output: str,
        decision_output: str,
        decision: object,
        hierarchy_output: str,
    ) -> ArtifactCheck:
        del state, decision_output
        if not isinstance(decision, LexiconDecisionPlan):
            return ArtifactCheck.rejected(
                "Hierarchy received an invalid Decision artifact"
            )
        return _compile_hierarchy(task, h1_output, decision, hierarchy_output)

    def validate_projected_subtask(
        self,
        task: LexiconBlocksworldTask,
        decision: object,
        subtask: PlannedSubtask,
        projected_state: LexiconExecutionState,
        is_last: bool,
    ) -> ArtifactCheck:
        if not isinstance(decision, LexiconDecisionPlan):
            return ArtifactCheck.rejected("Invalid Decision artifact")
        decision_subtask = decision.by_index().get(subtask.index)
        if decision_subtask is None:
            return ArtifactCheck.rejected(
                f"No Decision checkpoint for subtask {subtask.index}"
            )
        checkpoint_ok, evidence = _checkpoint_result(
            projected_state, decision_subtask.checkpoint
        )
        errors: List[str] = []
        if not checkpoint_ok:
            errors.append(
                f"Subtask {subtask.index} does not satisfy its Decision checkpoint"
            )
        if is_last:
            final = verify_plan(task, projected_state.executed_actions)
            evidence["final_verification"] = _safe_verification_payload(final)
            if not final.valid:
                errors.append(
                    "Final projected prefix does not satisfy the released compiled "
                    "PDDL task and temporal constraints"
                )
        return ArtifactCheck(
            valid=not errors,
            value=projected_state if not errors else None,
            errors=tuple(errors),
            metadata=evidence,
        )

    def router_request(
        self,
        task: LexiconBlocksworldTask,
        state: LexiconExecutionState,
        scene: object,
        state_output: str,
        decision_output: str,
        hierarchy_output: str,
        projection: object,
        execution_feedback: Optional[str] = None,
    ) -> StageRequest:
        del state, scene
        return StageRequest(
            stage="innerbot_router",
            system=SYSTEM_ROUTER,
            prompt=router_prompt(
                _model_task_text(task),
                state_output,
                decision_output,
                hierarchy_output,
                _projection_payload(projection),
                execution_feedback,
            ),
        )

    def parse_router(self, output: str) -> RouterVerdict:
        return common._parse_router_verdict(output)

    def apply_action(
        self,
        task: LexiconBlocksworldTask,
        state: LexiconExecutionState,
        action: object,
        action_index: int,
    ) -> TransitionResult:
        try:
            primitive = (
                action
                if isinstance(action, PrimitiveAction)
                else PrimitiveAction(
                    str(getattr(action, "name")), tuple(getattr(action, "args"))
                )
            )
        except Exception as error:
            return TransitionResult(
                False,
                state,
                f"Action {action_index} is not a Blocksworld primitive: {error}",
                {"failure_kind": "action_binding"},
            )
        replay = _replay_actions(task, (*state.executed_actions, primitive))
        if not replay.ok:
            return TransitionResult(
                False,
                state,
                _model_safe_evaluator_text(replay.reason),
                {
                    "failure_kind": replay.failure_kind,
                    "constraint_failure": replay.constraint_failure,
                    "unsatisfied_conditions": list(replay.unsatisfied_conditions),
                    "absolute_failed_action_index": replay.failed_action_index,
                    "failed_action": (
                        replay.failed_action.pddl if replay.failed_action else None
                    ),
                },
            )
        candidate = (*state.executed_actions, primitive)
        next_state = _execution_state(task, candidate, replay)
        return TransitionResult(
            True,
            next_state,
            "N/A",
            {
                "state_digest": next_state.digest,
                "public_facts": list(next_state.public_facts),
                "compiler_monitor_facts": list(next_state.monitor_facts),
            },
        )

    def outer_request(
        self,
        task: LexiconBlocksworldTask,
        decision: object,
        hierarchy: CompiledHierarchy,
        subtask: object,
        previous_state: LexiconExecutionState,
        current_state: LexiconExecutionState,
        is_last: bool,
    ) -> StageRequest:
        del hierarchy
        plan = getattr(subtask, "plan", subtask)
        if not isinstance(plan, PlannedSubtask):
            raise TypeError("OuterBot received an invalid projected subtask")
        decision_subtask = (
            decision.by_index().get(plan.index)
            if isinstance(decision, LexiconDecisionPlan)
            else None
        )
        checkpoint = (
            decision_subtask.checkpoint
            if decision_subtask is not None
            else LexiconCheckpoint((), (), ())
        )
        checkpoint_ok, evidence = _checkpoint_result(current_state, checkpoint)
        deterministic: Dict[str, object] = {
            "transition_applicable": True,
            "checkpoint_satisfied": checkpoint_ok,
            **evidence,
            "remaining_subtasks": not is_last,
        }
        if is_last:
            deterministic["final_verification"] = _safe_verification_payload(
                verify_plan(task, current_state.executed_actions)
            )
        before_count = len(previous_state.executed_actions)
        actions = current_state.executed_actions[before_count:]
        return StageRequest(
            stage="outerbot",
            system=SYSTEM_OUTERBOT,
            prompt=outerbot_prompt(
                _model_task_text(task),
                plan.description,
                checkpoint.to_dict(),
                _public_state_payload(previous_state),
                _public_state_payload(current_state),
                [action.pddl for action in actions],
                deterministic,
            ),
        )

    def parse_outer(self, output: str) -> OuterVerdict:
        return common._parse_outer_verdict(output)

    def format_action(self, action: object) -> str:
        if isinstance(action, PrimitiveAction):
            return action.pddl
        return PrimitiveAction(
            str(getattr(action, "name", "unknown")),
            tuple(getattr(action, "args", ())),
        ).pddl

    def format_call(self, call: object) -> str:
        if isinstance(call, PrimitiveAction):
            return call.pddl
        if isinstance(call, LexiconCall):
            return str(call)
        name = str(getattr(call, "name", "unknown"))
        args = tuple(getattr(call, "args", ()))
        return f"{name}({', '.join(str(argument) for argument in args)})"

    def reasoning_effort_for(
        self, stage: str, base_effort: Optional[str]
    ) -> Optional[str]:
        if base_effort is None:
            return None
        return (
            base_effort
            if stage
            in {"decision", "hierarchy_planner", "innerbot_state", "innerbot_router"}
            else "low"
        )

    def final_score(self, context: object) -> PlanVerification:
        return verify_plan(
            getattr(context, "task"), tuple(getattr(context, "executed_actions"))
        )


BlocksworldNLevelAdapter = SharedNLevelBlocksworldAdapter


__all__ = [
    "BlocksworldNLevelAdapter",
    "LexiconCall",
    "LexiconCheckpoint",
    "LexiconDecisionPlan",
    "LexiconDecisionSubtask",
    "LexiconExecutionState",
    "LexiconH1Library",
    "LexiconMapping",
    "PRIMITIVE_ARITIES",
    "SharedNLevelBlocksworldAdapter",
]
