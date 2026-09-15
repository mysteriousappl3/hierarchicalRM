"""LexiCon Logistics adapter for :mod:`shared_nlevel_pipeline`.

This adapter deliberately contains no orchestration loop.  The shared engine
owns the exact StateDescriptor -> InnerBot -> H1 -> DecisionBot -> dynamic
hierarchy -> projection -> router -> execution -> OuterBot flow used by Flat
Hanoi.  This file supplies only the Logistics-specific contracts:

* an oracle-free model view of the released task and current execution prefix;
* model-generated, deterministically checked H1 wrappers;
* plan-only checkpoint parsing;
* tagged, arbitrary-depth hierarchy compilation with inferred levels;
* pure action transitions through the released compiled PDDL problem; and
* final scoring through ``lexicon_logistics_task.verify_plan``.

The execution Harmony invariant is simple: ``LexiconExecutionState`` stores an
immutable primitive-action prefix.  Every transition reconstructs the official
compiled problem and replays that prefix before attempting the new action.  It
is intentionally conservative -- released Logistics plans are short, and an
opaque Unified Planning state is not safe to deepcopy or serialize between
projection, execution, retries, and worker threads.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from unified_planning.io import PDDLReader
from unified_planning.plans import ActionInstance
from unified_planning.shortcuts import SequentialSimulator

from lexicon_logistics_task import (
    PRIMITIVE_ARITIES,
    PRIMITIVE_SIGNATURES,
    LexiconLogisticsTask,
    PlanVerification,
    PrimitiveAction,
    validate_ground_fact,
    validate_primitive_action,
    verify_plan,
)
from shared_nlevel_lexicon_prompts import (
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


_FUNCTION_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CALL_RE = re.compile(r"(?P<name>[A-Za-z][A-Za-z0-9_]*)\s*\((?P<args>[^()]*)\)")
_MAPPING_RE = re.compile(
    r"(?P<header>[A-Z][A-Za-z0-9_]*\s*\([^()]*\))\s*=\s*"
    r"\[(?P<body>[^\[\]]*)\]",
    re.DOTALL,
)
_MAPPING_BLOCK_RE = re.compile(
    r"(?<![A-Za-z0-9_\x60])(?P<fence>```)?start_mapping\b\s*"
    r"(?P<body>.*?)\s*(?(fence)```|(?<!\x60))end_mapping\b(?!\x60)",
    re.DOTALL,
)
_SUBTASK_DESCRIPTION_RE = re.compile(
    r"(?<![A-Za-z0-9_\x60])(?P<fence>```)?start_subtask_"
    r"(?P<index>\d+)\b\s*(?P<body>.*?)\s*"
    r"(?(fence)```|(?<!\x60))end_subtask_(?P=index)\b(?!\x60)",
    re.DOTALL,
)
_SUBTASK_CHECKPOINT_RE = re.compile(
    r"(?<![A-Za-z0-9_\x60])(?P<fence>```)?start_subtask_goalstate_"
    r"(?P<index>\d+)\b\s*(?P<body>.*?)\s*"
    r"(?(fence)```|(?<!\x60))end_subtask_goalstate_(?P=index)\b(?!\x60)",
    re.DOTALL,
)
_SUBTASK_CALLS_RE = re.compile(
    r"(?<![A-Za-z0-9_\x60])(?P<fence>```)?start_subtask_funcs_"
    r"(?P<index>\d+)\b\s*(?P<body>.*?)\s*"
    r"(?(fence)```|(?<!\x60))end_subtask_funcs_(?P=index)\b(?!\x60)",
    re.DOTALL,
)
_STATE_BLOCK_RE = re.compile(
    r"\A\s*(?P<fence>```)?start_flag\b\s*(?P<body>.*?)\s*"
    r"(?(fence)```|(?<!\x60))end_flag\b(?!\x60)\s*\Z",
    re.DOTALL,
)
_RESULT_BLOCK_RE = re.compile(
    r"(?<![A-Za-z0-9_\x60])(?P<fence>```)?start_result\b\s*"
    r"(?P<body>.*?)\s*(?(fence)```|(?<!\x60))end_result\b(?!\x60)",
    re.DOTALL,
)
_NEGATED_FACT_RE = re.compile(r"^\(not (?P<atom>\(.+\))\)$")
_COMPILER_MONITOR_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:hold|seen)_[A-Za-z0-9_]*"
)


_H1_TO_PRIMITIVE: Dict[str, str] = {
    "LoadTruck": "loadtruck",
    "LoadAirplane": "loadairplane",
    "UnloadTruck": "unloadtruck",
    "UnloadAirplane": "unloadairplane",
    "DriveTruck": "drivetruck",
    "FlyAirplane": "flyairplane",
}

_TYPE_PARENT: Dict[str, str] = {
    "airport": "location",
    "location": "object",
    "city": "object",
    "package": "obj",
    "truck": "obj",
    "airplane": "obj",
    "obj": "object",
}


@dataclass(frozen=True)
class LexiconCall:
    """One hierarchy or primitive call in the tagged shared notation."""

    name: str
    args: Tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.name}({', '.join(self.args)})"


@dataclass(frozen=True)
class LexiconMapping:
    name: str
    params: Tuple[str, ...]
    calls: Tuple[LexiconCall, ...]
    fixed_h1: bool = False


@dataclass(frozen=True)
class LexiconH1Library:
    mappings: Mapping[str, LexiconMapping]


@dataclass(frozen=True)
class LexiconCheckpoint:
    required_true: Tuple[str, ...]
    required_false: Tuple[str, ...]
    constraints_addressed: Tuple[int, ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            "required_true": list(self.required_true),
            "required_false": list(self.required_false),
            "constraints_addressed": list(self.constraints_addressed),
        }


@dataclass(frozen=True)
class LexiconDecisionSubtask:
    index: int
    description: str
    checkpoint: LexiconCheckpoint


@dataclass(frozen=True)
class LexiconDecisionPlan:
    subtasks: Tuple[LexiconDecisionSubtask, ...]

    def by_index(self) -> Dict[int, LexiconDecisionSubtask]:
        return {subtask.index: subtask for subtask in self.subtasks}


@dataclass(frozen=True)
class LexiconExecutionState:
    """Serializable state handle derived only from an accepted action prefix."""

    executed_actions: Tuple[PrimitiveAction, ...]
    public_facts: Tuple[str, ...]
    monitor_facts: Tuple[str, ...]
    digest: str


@dataclass(frozen=True)
class _ReplayResult:
    ok: bool
    state: Any
    problem: Any
    failed_action_index: Optional[int] = None
    failed_action: Optional[PrimitiveAction] = None
    failure_kind: Optional[str] = None
    reason: str = "N/A"
    unsatisfied_conditions: Tuple[str, ...] = ()
    constraint_failure: bool = False


@dataclass
class _HierarchyBuild:
    mappings: Dict[str, LexiconMapping]
    levels: Dict[str, int]
    subtasks: List[PlannedSubtask]
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, object] = field(default_factory=dict)


def _unique(values: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


def _model_safe_evaluator_text(value: object) -> str:
    """Redact private compilation fluents from any model-visible diagnostic."""

    return _COMPILER_MONITOR_RE.sub("<temporal_constraint_monitor>", str(value))


def _is_subtype(actual: str, expected: str) -> bool:
    current = actual
    while True:
        if current == expected:
            return True
        parent = _TYPE_PARENT.get(current)
        if parent is None:
            return False
        current = parent


def _object_type_map(task: LexiconLogisticsTask) -> Dict[str, str]:
    return {
        name: type_name
        for type_name, names in task.objects_by_type.items()
        for name in names
    }


def _all_task_objects(task: LexiconLogisticsTask) -> set[str]:
    return set(_object_type_map(task))


def _fact_atom(fact: str) -> Tuple[str, bool]:
    negated = _NEGATED_FACT_RE.fullmatch(fact)
    if negated is None:
        return fact, True
    return negated.group("atom"), False


def _strip_stage_conflicting_output_instruction(text: str) -> str:
    """Remove only the canonical prompt's final primitive-plan instruction.

    The task facts, goals, constraints, action semantics, and their ordering are
    left byte-for-byte intact.  Stage-specific JSON/tag instructions are added
    by the prompt builders instead.  This avoids telling DecisionBot both "emit
    no actions" and "output only the plan" in the same request.
    """

    objective = (
        "Objective: produce a minimum-length valid plan that reaches every goal "
        "and obeys every temporal constraint. Use exactly one action per line."
    )
    if objective in text:
        text = text.replace(
            objective,
            "Task objective: reach every goal and obey every temporal constraint "
            "with a minimum-length primitive action expansion.",
            1,
        )
    marker = "\nOutput only the plan:"
    if marker in text:
        text = text.split(marker, 1)[0].rstrip() + "\n"
    return text


def _model_task_text(task: LexiconLogisticsTask) -> str:
    """Return the selected task prompt without its final output directive.

    ``LexiconLogisticsTask.prompt_text`` is the provenance-preserving selector
    for ``canonical-pddl``, ``official-mapper``, and ``official-nl``.  Respecting
    it here keeps the recorded ``prompt_source`` aligned with the text actually
    shown to every model stage.  None of those task texts contains an answer;
    oracle plans remain available only to final evaluator-side scoring.
    """

    return _strip_stage_conflicting_output_instruction(task.prompt_text())


def _parse_labeled_value(body: str, label: str) -> str:
    match = re.search(
        rf"(?im)^\s*{re.escape(label)}\s*:\s*(.*?)\s*$", body
    )
    return match.group(1).strip() if match else ""


def _parse_inner_verdict(output: str) -> Tuple[bool, str]:
    match = _RESULT_BLOCK_RE.search(output or "")
    body = match.group("body") if match else output or ""
    result = _parse_labeled_value(body, "RESULT").upper()
    reason = _parse_labeled_value(body, "REASON") or "unparseable InnerBot verdict"
    return result == "YES", reason


def _parse_router_verdict(output: str) -> RouterVerdict:
    match = _RESULT_BLOCK_RE.search(output or "")
    body = match.group("body") if match else output or ""
    result = _parse_labeled_value(body, "RESULT").upper()
    owner_text = _parse_labeled_value(body, "OWNER").lower().replace("_", " ")
    reason = _parse_labeled_value(body, "REASON") or "unparseable router verdict"
    has_decision = "decision" in owner_text or "planner bot" in owner_text
    has_hierarchy = "hierarchy" in owner_text
    if result == "YES":
        return RouterVerdict(True, "both", reason or "N/A")
    if owner_text == "both" or (has_decision and has_hierarchy):
        owner = "both"
    elif has_hierarchy:
        owner = "hierarchy"
    elif has_decision:
        owner = "decision"
    else:
        owner = "both"
    return RouterVerdict(False, owner, reason)


def _parse_outer_verdict(output: str) -> OuterVerdict:
    match = _RESULT_BLOCK_RE.search(output or "")
    body = match.group("body") if match else output or ""
    raw = _parse_labeled_value(body, "VERDICT") or _parse_labeled_value(body, "RESULT")
    normalized = re.sub(r"[^A-Z]+", " ", raw.upper()).strip()
    accepted = {
        "TASK SUCCESS",
        "SUBTASK SUCCESS",
        "EXECUTE REMAINING ACTIONS",
        "RECOVERABLE",
        "NON RECOVERABLE",
    }
    status = normalized if normalized in accepted else "RECOVERABLE"
    if status == "NON RECOVERABLE":
        status = "NON-RECOVERABLE"
    reason = _parse_labeled_value(body, "REASON") or "unparseable OuterBot verdict"
    return OuterVerdict(status, reason)


def _parse_call_text(text: str, *, context: str) -> Tuple[Optional[LexiconCall], List[str]]:
    stripped = text.strip().rstrip(".").strip()
    match = _CALL_RE.fullmatch(stripped)
    if match is None:
        return None, [f"{context}: expected one Function(arg, ...) call"]
    name = match.group("name")
    raw_args = match.group("args").strip()
    args = tuple(argument.strip() for argument in raw_args.split(",")) if raw_args else ()
    if any(not _IDENTIFIER_RE.fullmatch(argument) for argument in args):
        return None, [f"{context}: arguments must be bare lowercase identifiers"]
    return LexiconCall(name, args), []


def _parse_call_list(text: str, *, context: str) -> Tuple[List[LexiconCall], List[str]]:
    calls: List[LexiconCall] = []
    errors: List[str] = []
    cursor = 0
    for position, match in enumerate(_CALL_RE.finditer(text), start=1):
        separator = text[cursor : match.start()]
        if separator.strip().strip(",.;"):
            errors.append(f"{context}: unexpected text {separator.strip()!r}")
        call, call_errors = _parse_call_text(match.group(0), context=f"{context} call {position}")
        if call is not None:
            calls.append(call)
        errors.extend(call_errors)
        cursor = match.end()
    trailer = text[cursor:]
    if trailer.strip().strip(",.;"):
        errors.append(f"{context}: unexpected trailing text {trailer.strip()!r}")
    if not calls:
        errors.append(f"{context}: no calls found")
    return calls, errors


def _parse_mappings(text: str, *, context: str) -> Tuple[Dict[str, LexiconMapping], List[str]]:
    blocks = list(_MAPPING_BLOCK_RE.finditer(text or ""))
    if len(blocks) != 1:
        return {}, [f"{context}: expected exactly one start_mapping/end_mapping block"]
    body = blocks[0].group("body")
    mappings: Dict[str, LexiconMapping] = {}
    errors: List[str] = []
    cursor = 0
    for position, match in enumerate(_MAPPING_RE.finditer(body), start=1):
        separator = body[cursor : match.start()]
        if separator.strip().strip(",.;"):
            errors.append(f"{context}: unexpected mapping text {separator.strip()!r}")
        header, header_errors = _parse_call_text(
            match.group("header"), context=f"{context} mapping {position} header"
        )
        errors.extend(header_errors)
        calls, call_errors = _parse_call_list(
            match.group("body"), context=f"{context} mapping {position} body"
        )
        errors.extend(call_errors)
        if header is not None:
            if not _FUNCTION_NAME_RE.fullmatch(header.name):
                errors.append(f"{context}: mapping name {header.name!r} must start uppercase")
            elif header.name in mappings:
                errors.append(f"{context}: duplicate mapping {header.name}")
            elif len(set(header.args)) != len(header.args):
                errors.append(f"{context}: mapping {header.name} has duplicate parameters")
            else:
                mappings[header.name] = LexiconMapping(
                    header.name, header.args, tuple(calls)
                )
        cursor = match.end()
    trailer = body[cursor:]
    if trailer.strip().strip(",.;"):
        errors.append(f"{context}: unexpected trailing mapping text {trailer.strip()!r}")
    if not mappings:
        errors.append(f"{context}: no valid mappings found")
    return mappings, _unique(errors)


def _validate_h1_library(text: str) -> ArtifactCheck:
    mappings, errors = _parse_mappings(text, context="H1")
    if set(mappings) != set(_H1_TO_PRIMITIVE):
        errors.append(
            "H1 must define exactly " + ", ".join(_H1_TO_PRIMITIVE)
        )
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


def _parse_decision(task: LexiconLogisticsTask, text: str) -> ArtifactCheck:
    description_matches = list(_SUBTASK_DESCRIPTION_RE.finditer(text or ""))
    checkpoint_matches = list(_SUBTASK_CHECKPOINT_RE.finditer(text or ""))
    errors: List[str] = []
    descriptions: Dict[int, str] = {}
    raw_checkpoints: Dict[int, str] = {}
    for match in description_matches:
        index = int(match.group("index"))
        if index in descriptions:
            errors.append(f"Decision contains duplicate description block {index}")
        descriptions[index] = match.group("body").strip()
    for match in checkpoint_matches:
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
    primitive_leak_re = re.compile(
        r"\b(?:" + "|".join(map(re.escape, PRIMITIVE_ARITIES)) + r")\b",
        re.IGNORECASE,
    )
    function_call_leak_re = re.compile(r"\b[A-Z][A-Za-z0-9_]*\s*\(")
    for index in indices:
        description = descriptions.get(index, "").strip()
        if not description:
            errors.append(f"Subtask {index} description is empty")
        if primitive_leak_re.search(description) or function_call_leak_re.search(description):
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
                    tuple(true_facts),
                    tuple(false_facts),
                    tuple(constraint_indices),
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
    levels: Dict[str, int] = {
        name: 1 for name, mapping in mappings.items() if mapping.fixed_h1
    }
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
        child_levels: List[int] = []
        for call in mapping.calls:
            level = visit(call.name)
            if level is not None:
                child_levels.append(level)
        visiting.pop()
        if not child_levels:
            errors.append(f"Mapping {name} has no resolvable calls")
            return None
        inferred = max(child_levels) + 1
        levels[name] = inferred
        return inferred

    for name in sorted(mappings):
        visit(name)
    return levels, _unique(errors)


def _formal_type_requirements(
    mappings: Mapping[str, LexiconMapping], levels: Mapping[str, int]
) -> Tuple[Dict[str, Tuple[frozenset[str], ...]], List[str]]:
    """Propagate primitive type requirements through every mapping parameter."""

    errors: List[str] = []
    requirements: Dict[str, Tuple[frozenset[str], ...]] = {}
    for h1_name, primitive_name in _H1_TO_PRIMITIVE.items():
        mapping = mappings.get(h1_name)
        if mapping is None:
            continue
        requirements[h1_name] = tuple(
            frozenset((type_name,))
            for type_name in PRIMITIVE_SIGNATURES[primitive_name]
        )

    custom_names = sorted(
        (name for name, mapping in mappings.items() if not mapping.fixed_h1),
        key=lambda name: (levels.get(name, 10**9), name),
    )
    concrete_types = ("airport", "location", "city", "package", "truck", "airplane")
    for name in custom_names:
        mapping = mappings[name]
        collected: List[set[str]] = [set() for _ in mapping.params]
        positions = {parameter: index for index, parameter in enumerate(mapping.params)}
        for call in mapping.calls:
            target = mappings.get(call.name)
            target_requirements = requirements.get(call.name)
            if target is None or target_requirements is None:
                continue
            if len(call.args) != len(target.params):
                errors.append(
                    f"{name} calls {call.name} with {len(call.args)} arguments; "
                    f"expected {len(target.params)}"
                )
                continue
            for argument, needed in zip(call.args, target_requirements):
                position = positions.get(argument)
                if position is None:
                    errors.append(
                        f"{name} body argument {argument!r} is not a declared parameter"
                    )
                    continue
                collected[position].update(needed)
        for parameter, needed in zip(mapping.params, collected):
            if not needed:
                errors.append(f"{name} has unused parameter {parameter!r}")
                continue
            if not any(
                all(_is_subtype(actual, expected) for expected in needed)
                for actual in concrete_types
            ):
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
                return
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
                f"{call.name} has {len(call.args)} arguments; expected "
                f"{len(mapping.params)}"
            )
            return
        bindings = dict(zip(mapping.params, call.args))
        for child in mapping.calls:
            bound = tuple(bindings.get(argument, argument) for argument in child.args)
            expand(LexiconCall(child.name, bound), (*stack, call.name))

    for call in calls:
        expand(call, ())
    return expanded, _unique(errors)


def _count_calls_by_level(
    calls: Sequence[LexiconCall],
    mappings: Mapping[str, LexiconMapping],
    levels: Mapping[str, int],
) -> Dict[int, int]:
    histogram: Dict[int, int] = {}

    def walk(call: LexiconCall, depth: int) -> None:
        if depth > 64:
            return
        level = levels.get(call.name)
        if level is None:
            return
        histogram[level] = histogram.get(level, 0) + 1
        if level <= 1:
            return
        mapping = mappings.get(call.name)
        if mapping is None:
            return
        for child in mapping.calls:
            walk(child, depth + 1)

    for call in calls:
        walk(call, 0)
    return histogram


def _compile_hierarchy(
    task: LexiconLogisticsTask,
    h1_output: str,
    decision: LexiconDecisionPlan,
    hierarchy_output: str,
) -> ArtifactCheck:
    errors: List[str] = []
    h1_check = _validate_h1_library(h1_output)
    if not h1_check.valid or not isinstance(h1_check.value, LexiconH1Library):
        errors.extend(f"H1: {error}" for error in h1_check.errors)
        return ArtifactCheck(False, errors=tuple(_unique(errors)))

    custom, parse_errors = _parse_mappings(hierarchy_output, context="Hierarchy")
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
        inferred = levels.get(name)
        if inferred is not None and inferred < 2:
            errors.append(f"Custom mapping {name} must infer to H2 or deeper")

    formal_requirements, type_errors = _formal_type_requirements(mappings, levels)
    errors.extend(type_errors)
    object_types = _object_type_map(task)

    call_matches = list(_SUBTASK_CALLS_RE.finditer(hierarchy_output or ""))
    blocks: Dict[int, str] = {}
    block_order: List[int] = []
    for match in call_matches:
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
    planned_subtasks: List[PlannedSubtask] = []
    total_expanded = 0
    for index in expected_ids:
        raw_block = blocks.get(index)
        if raw_block is None:
            continue
        top_calls, call_errors = _parse_call_list(
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
                    continue
                if position < len(required_types) and any(
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
        planned_subtasks.append(
            PlannedSubtask(
                index=index,
                description=decision_subtask.description,
                top_level_calls=tuple(top_calls),
                h0_calls=tuple(expanded),
                actions=tuple(expanded),
                level_counts=_count_calls_by_level(top_calls, mappings, levels),
                metadata={"checkpoint": decision_subtask.checkpoint.to_dict()},
            )
        )

    mapping_counts: Dict[int, int] = {}
    for level in levels.values():
        mapping_counts[level] = mapping_counts.get(level, 0) + 1
    max_level = max(levels.values(), default=0)
    hierarchy_valid = bool(custom) and max_level >= 2
    top_level_count = sum(len(subtask.top_level_calls) for subtask in planned_subtasks)
    stats = HierarchyStats(
        max_level=max_level,
        base_pattern_valid=h1_check.valid,
        hierarchy_valid=hierarchy_valid,
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
            # These are descriptive only.  Neither one is an acceptance gate.
            "unused_custom_mappings": sorted(
                set(custom)
                - {
                    call.name
                    for subtask in planned_subtasks
                    for call in subtask.top_level_calls
                }
            ),
        },
    )
    compiled = CompiledHierarchy(
        subtasks=tuple(planned_subtasks),
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
    try:
        if expression.is_fluent_exp():
            name = expression.fluent().name
            return name.startswith("hold_") or name.startswith("seen_")
        return any(_has_constraint_fluent(argument) for argument in expression.args)
    except Exception:
        text = str(expression)
        return "hold_" in text or "seen_" in text


def _bind_action(problem: Any, action: PrimitiveAction) -> ActionInstance:
    declaration = problem.action(action.name)
    manager = problem.environment.expression_manager
    parameters = tuple(
        manager.ObjectExp(problem.object(argument)) for argument in action.args
    )
    return ActionInstance(declaration, parameters)


def _replay_actions(
    task: LexiconLogisticsTask, actions: Sequence[PrimitiveAction]
) -> _ReplayResult:
    """Replay a prefix without requiring final goals.

    This is deliberately separate from ``verify_plan``.  An intermediate prefix
    may leave a ``sometime`` monitor goal false without having violated it.
    """

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
        raise RuntimeError(f"Could not load released compiled LexiCon task: {error}") from error

    simulator = SequentialSimulator(problem)
    state = simulator.get_initial_state()
    for index, raw_action in enumerate(actions, start=1):
        action = (
            raw_action
            if isinstance(raw_action, PrimitiveAction)
            else PrimitiveAction(
                str(getattr(raw_action, "name")),
                tuple(getattr(raw_action, "args")),
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
    try:
        return bool(state.get_value(expression).is_true())
    except Exception:
        return False


def _state_facts(problem: Any, state: Any, task: LexiconLogisticsTask) -> Tuple[str, ...]:
    facts: List[str] = []
    packages = tuple(task.objects_by_type.get("package", ()))
    trucks = tuple(task.objects_by_type.get("truck", ()))
    airplanes = tuple(task.objects_by_type.get("airplane", ()))
    locations = tuple(
        dict.fromkeys(
            (*task.objects_by_type.get("location", ()), *task.objects_by_type.get("airport", ()))
        )
    )
    cities = tuple(task.objects_by_type.get("city", ()))

    at_fluent = problem.fluent("at_")
    for subject in (*packages, *trucks, *airplanes):
        for location in locations:
            expression = at_fluent(problem.object(subject), problem.object(location))
            if _state_truth(state, expression):
                facts.append(f"(at_ {subject} {location})")

    in_fluent = problem.fluent("in")
    for package in packages:
        for vehicle in (*trucks, *airplanes):
            expression = in_fluent(problem.object(package), problem.object(vehicle))
            if _state_truth(state, expression):
                facts.append(f"(in {package} {vehicle})")

    incity_fluent = problem.fluent("incity")
    for location in locations:
        for city in cities:
            expression = incity_fluent(problem.object(location), problem.object(city))
            if _state_truth(state, expression):
                facts.append(f"(incity {location} {city})")
    return tuple(sorted(facts))


def _monitor_facts(problem: Any, state: Any) -> Tuple[str, ...]:
    values: List[str] = []
    for fluent in problem.fluents:
        if fluent.name.startswith("hold_") or fluent.name.startswith("seen_"):
            expression = fluent()
            values.append(
                f"({fluent.name})={'true' if _state_truth(state, expression) else 'false'}"
            )
    return tuple(sorted(values))


def _execution_state(
    task: LexiconLogisticsTask,
    actions: Sequence[PrimitiveAction],
    replay: Optional[_ReplayResult] = None,
) -> LexiconExecutionState:
    replay = replay or _replay_actions(task, actions)
    if not replay.ok:
        raise ValueError(f"Cannot construct state from invalid prefix: {replay.reason}")
    public_facts = _state_facts(replay.problem, replay.state, task)
    monitor_facts = _monitor_facts(replay.problem, replay.state)
    action_tuple = tuple(actions)
    digest_payload = {
        "actions": [action.pddl for action in action_tuple],
        "public_facts": public_facts,
        "monitor_facts": monitor_facts,
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return LexiconExecutionState(action_tuple, public_facts, monitor_facts, digest)


def _public_state_payload(state: LexiconExecutionState) -> Dict[str, object]:
    return {
        "current_facts": list(state.public_facts),
        "executed_actions": [action.pddl for action in state.executed_actions],
        "state_digest": state.digest,
    }


def _authoritative_model_view(
    task: LexiconLogisticsTask, state: LexiconExecutionState
) -> Dict[str, object]:
    """Return a complete current-state view with evaluator-only fields absent."""

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
    current = set(state.public_facts)
    missing_true: List[str] = []
    present_false: List[str] = []
    for fact in checkpoint.required_true:
        atom, positive = _fact_atom(fact)
        holds = atom in current
        if holds != positive:
            missing_true.append(fact)
    for atom in checkpoint.required_false:
        if atom in current:
            present_false.append(atom)
    return not missing_true and not present_false, {
        "checkpoint": checkpoint.to_dict(),
        "missing_required_true": missing_true,
        "present_required_false": present_false,
    }


def _safe_verification_payload(verification: PlanVerification) -> Dict[str, object]:
    """Model-visible verification evidence with no oracle/optimality fields."""

    return {
        "valid": verification.valid,
        "goal_and_constraints_satisfied": verification.valid,
        "submitted_length": verification.submitted_length,
        "goal_failure": verification.goal_failure,
        "constraint_failure": verification.constraint_failure,
        "failure_kind": verification.failure_kind,
        "failure_message": (
            _model_safe_evaluator_text(verification.failure_message)
            if verification.failure_message is not None
            else None
        ),
        "first_failed_action_index": verification.first_failed_action_index,
        "first_failed_action": (
            verification.first_failed_action.pddl
            if verification.first_failed_action is not None
            else None
        ),
        "unsatisfied_preconditions": [
            _model_safe_evaluator_text(value)
            for value in verification.unsatisfied_preconditions
        ],
        "unsatisfied_task_goals": list(verification.unsatisfied_task_goals),
        "unsatisfied_constraint_goals": [
            _model_safe_evaluator_text(value)
            for value in verification.unsatisfied_constraint_goals
        ],
    }


def _projection_payload(projection: Any) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "valid": bool(getattr(projection, "valid", False)),
        "reason": _model_safe_evaluator_text(
            getattr(projection, "reason", "N/A")
        ),
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
        # Metadata is evaluator-generated.  Filter explicitly instead of
        # passing through a future oracle-bearing key by accident.
        payload["failure_kind"] = metadata.get("failure_kind")
        payload["constraint_failure"] = metadata.get("constraint_failure")
        payload["unsatisfied_conditions"] = [
            _model_safe_evaluator_text(value)
            for value in metadata.get("unsatisfied_conditions", [])
        ]
    return payload


class SharedNLevelLexiconAdapter:
    """Domain hooks consumed by ``run_shared_nlevel_loop``.

    All methods are stateless and therefore safe to share across worker threads.
    The only authoritative mutable quantity -- execution progress -- is encoded
    in the immutable ``LexiconExecutionState.executed_actions`` tuple.
    """

    name = "lexicon-logistics"
    verifier_mode = "compiled-pddl"

    def initial_state(self, task: LexiconLogisticsTask) -> LexiconExecutionState:
        return _execution_state(task, ())

    def copy_state(
        self, task: LexiconLogisticsTask, state: LexiconExecutionState
    ) -> LexiconExecutionState:
        del task
        return LexiconExecutionState(
            tuple(state.executed_actions),
            tuple(state.public_facts),
            tuple(state.monitor_facts),
            state.digest,
        )

    def snapshot_state(
        self, task: LexiconLogisticsTask, state: LexiconExecutionState
    ) -> Dict[str, object]:
        del task
        # snapshot_state is interpolated into retry/router feedback by the
        # shared engine, so it must be just as model-safe as render_state().
        # Private compiler-monitor facts remain in LexiconExecutionState and
        # transition metadata for evaluator-side audit only.
        return _public_state_payload(state)

    def render_state(
        self, task: LexiconLogisticsTask, state: LexiconExecutionState
    ) -> Dict[str, object]:
        return _authoritative_model_view(task, state)

    def goal_reached(
        self, task: LexiconLogisticsTask, state: LexiconExecutionState
    ) -> bool:
        # World goals alone are insufficient: compiled monitor goals represent
        # liveness constraints such as sometime and sometime-after.
        return verify_plan(task, state.executed_actions).valid

    # Alias accepted by some early shared-engine drafts.
    is_goal = goal_reached

    def fixed_state_descriptor(
        self,
        task: LexiconLogisticsTask,
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
        task: LexiconLogisticsTask,
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
            prompt=state_descriptor_prompt(
                _model_task_text(task),
                view,
                feedback,
            ),
        )

    def validate_state_descriptor(
        self,
        task: LexiconLogisticsTask,
        state: LexiconExecutionState,
        scene: object,
        output: str,
    ) -> ArtifactCheck:
        del scene
        match = _STATE_BLOCK_RE.fullmatch(output or "")
        if match is None:
            return ArtifactCheck(
                False,
                errors=(
                    "StateDescriptor must be exactly one start_flag/end_flag JSON block",
                ),
            )
        try:
            payload = json.loads(match.group("body"))
        except json.JSONDecodeError as error:
            return ArtifactCheck(False, errors=(f"StateDescriptor JSON: {error}",))
        expected = _authoritative_model_view(task, state)
        if payload != expected:
            differing = [
                key
                for key in sorted(set(expected) | (set(payload) if isinstance(payload, dict) else set()))
                if not isinstance(payload, dict) or payload.get(key) != expected.get(key)
            ]
            return ArtifactCheck(
                False,
                errors=(f"StateDescriptor differs in fields: {differing}",),
                metadata={"differing_fields": differing},
            )
        return ArtifactCheck(True, value=payload)

    def inner_state_request(
        self,
        task: LexiconLogisticsTask,
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
        return _parse_inner_verdict(output)

    def h0_spec(self, task: LexiconLogisticsTask) -> Dict[str, object]:
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
        task: LexiconLogisticsTask,
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

    def validate_h1(self, task: LexiconLogisticsTask, output: str) -> ArtifactCheck:
        del task
        return _validate_h1_library(output)

    def decision_request(
        self,
        task: LexiconLogisticsTask,
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
                _model_task_text(task),
                state_output,
                h1_output,
                feedback,
            ),
        )

    def parse_decision(
        self, task: LexiconLogisticsTask, output: str
    ) -> ArtifactCheck:
        return _parse_decision(task, output)

    def hierarchy_request(
        self,
        task: LexiconLogisticsTask,
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
        task: LexiconLogisticsTask,
        state: LexiconExecutionState,
        h1_output: str,
        decision_output: str,
        decision: object,
        hierarchy_output: str,
    ) -> ArtifactCheck:
        del state, decision_output
        if not isinstance(decision, LexiconDecisionPlan):
            return ArtifactCheck(
                False, errors=("Hierarchy received an invalid Decision artifact",)
            )
        return _compile_hierarchy(task, h1_output, decision, hierarchy_output)

    def validate_projected_subtask(
        self,
        task: LexiconLogisticsTask,
        decision: object,
        subtask: PlannedSubtask,
        projected_state: LexiconExecutionState,
        is_last: bool,
    ) -> ArtifactCheck:
        if not isinstance(decision, LexiconDecisionPlan):
            return ArtifactCheck(False, errors=("Invalid Decision artifact",))
        decision_subtask = decision.by_index().get(subtask.index)
        if decision_subtask is None:
            return ArtifactCheck(
                False,
                errors=(f"No Decision checkpoint for subtask {subtask.index}",),
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
            final_verification = verify_plan(task, projected_state.executed_actions)
            evidence["final_verification"] = _safe_verification_payload(
                final_verification
            )
            if not final_verification.valid:
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
        task: LexiconLogisticsTask,
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
        return _parse_router_verdict(output)

    def apply_action(
        self,
        task: LexiconLogisticsTask,
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
                f"Action {action_index} is not a Logistics primitive: {error}",
                {"failure_kind": "action_binding"},
            )
        candidate = (*state.executed_actions, primitive)
        replay = _replay_actions(task, candidate)
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
        task: LexiconLogisticsTask,
        decision: object,
        hierarchy: CompiledHierarchy,
        subtask: object,
        previous_state: LexiconExecutionState,
        current_state: LexiconExecutionState,
        is_last: bool,
    ) -> StageRequest:
        del hierarchy
        # The shared engine passes the projected wrapper at execution time;
        # accepting the underlying PlannedSubtask as well keeps this hook easy
        # to exercise directly in adapter-level tests.
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
        checkpoint_ok, checkpoint_evidence = _checkpoint_result(
            current_state, checkpoint
        )
        deterministic: Dict[str, object] = {
            "transition_applicable": True,
            "checkpoint_satisfied": checkpoint_ok,
            **checkpoint_evidence,
            "remaining_subtasks": not is_last,
        }
        if is_last:
            deterministic["final_verification"] = _safe_verification_payload(
                verify_plan(task, current_state.executed_actions)
            )
        before_count = len(previous_state.executed_actions)
        executed_segment = current_state.executed_actions[before_count:]
        return StageRequest(
            stage="outerbot",
            system=SYSTEM_OUTERBOT,
            prompt=outerbot_prompt(
                _model_task_text(task),
                plan.description,
                checkpoint.to_dict(),
                _public_state_payload(previous_state),
                _public_state_payload(current_state),
                [action.pddl for action in executed_segment],
                deterministic,
            ),
        )

    def parse_outer(self, output: str) -> OuterVerdict:
        return _parse_outer_verdict(output)

    def format_action(self, action: object) -> str:
        if isinstance(action, PrimitiveAction):
            return action.pddl
        name = str(getattr(action, "name", "unknown"))
        args = tuple(getattr(action, "args", ()))
        return PrimitiveAction(name, args).pddl

    def format_call(self, call: object) -> str:
        if isinstance(call, PrimitiveAction):
            return call.pddl
        if isinstance(call, LexiconCall):
            return str(call)
        name = str(getattr(call, "name", "unknown"))
        args = tuple(getattr(call, "args", ()))
        return f"{name}({', '.join(str(arg) for arg in args)})"

    def reasoning_effort_for(
        self, stage: str, base_effort: Optional[str]
    ) -> Optional[str]:
        if base_effort is None:
            return None
        medium_stages = {
            "decision",
            "hierarchy_planner",
            "innerbot_state",
            "innerbot_router",
        }
        return base_effort if stage in medium_stages else "low"

    def final_score(self, context: object) -> PlanVerification:
        task = getattr(context, "task")
        executed_actions = tuple(getattr(context, "executed_actions"))
        # This is the sole final authority.  OuterBot never modifies this result.
        return verify_plan(task, executed_actions)


# Short aliases make integration readable and tolerate the name used in early
# shared-engine design notes.
LexiconNLevelAdapter = SharedNLevelLexiconAdapter
LexiconLogisticsNLevelAdapter = SharedNLevelLexiconAdapter


__all__ = [
    "LexiconCall",
    "LexiconCheckpoint",
    "LexiconDecisionPlan",
    "LexiconDecisionSubtask",
    "LexiconExecutionState",
    "LexiconH1Library",
    "LexiconLogisticsNLevelAdapter",
    "LexiconMapping",
    "LexiconNLevelAdapter",
    "SharedNLevelLexiconAdapter",
]
