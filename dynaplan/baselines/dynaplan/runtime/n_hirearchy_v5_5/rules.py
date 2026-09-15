"""Domain-neutral interpreter for rules induced from a public task prompt.

The interpreter never reads benchmark PDDL, an oracle plan, or a domain
adapter. It accepts a closed JSON language describing typed objects,
STRIPS-style actions, goals, and common PDDL3 trajectory constraints.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = "n_hierarchy_rules_v1"
SUPPORTED_TEMPORAL_OPERATORS = frozenset(
    {"sometime", "sometime-before", "sometime-after", "always", "at-most-once"}
)
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_TERM_RE = re.compile(r"^(?:\?[A-Za-z][A-Za-z0-9_-]*|[A-Za-z0-9][A-Za-z0-9_-]*)$")
_FACT_RE = re.compile(
    r"^\((?P<predicate>[A-Za-z][A-Za-z0-9_-]*)(?P<arguments>(?: [A-Za-z0-9?_-]+)*)\)$"
)
_ROOT_KEYS = {
    "schema_version",
    "domain_name",
    "types",
    "objects",
    "predicates",
    "actions",
    "initial_facts",
    "goal",
    "temporal_constraints",
    "source_constraints",
}


class RuleValidationError(ValueError):
    """The model-produced rule artifact is not executable by the interpreter."""


@dataclass(frozen=True, order=True)
class Fact:
    predicate: str
    arguments: Tuple[str, ...] = ()

    @property
    def pddl(self) -> str:
        suffix = " " + " ".join(self.arguments) if self.arguments else ""
        return f"({self.predicate}{suffix})"


@dataclass(frozen=True)
class Condition:
    all_of: Tuple[Fact, ...] = ()
    any_of: Tuple[Fact, ...] = ()
    none_of: Tuple[Fact, ...] = ()

    def holds(self, facts: Iterable[Fact]) -> bool:
        present = frozenset(facts)
        return (
            all(fact in present for fact in self.all_of)
            and (not self.any_of or any(fact in present for fact in self.any_of))
            and all(fact not in present for fact in self.none_of)
        )

    @property
    def empty(self) -> bool:
        return not (self.all_of or self.any_of or self.none_of)


@dataclass(frozen=True)
class Parameter:
    name: str
    type_name: str


@dataclass(frozen=True)
class ActionRule:
    name: str
    parameters: Tuple[Parameter, ...]
    precondition: Condition
    add: Tuple[Fact, ...]
    delete: Tuple[Fact, ...]


@dataclass(frozen=True)
class TemporalRule:
    identifier: str
    operator: str
    first: Condition
    second: Condition


@dataclass(frozen=True)
class RuleProgram:
    domain_name: str
    type_parents: Mapping[str, Optional[str]]
    object_types: Mapping[str, str]
    predicates: Mapping[str, Tuple[str, ...]]
    mutable_predicates: frozenset[str]
    actions: Mapping[str, ActionRule]
    initial_facts: frozenset[Fact]
    goal: Condition
    temporal_constraints: Tuple[TemporalRule, ...]
    source_constraints: Tuple[str, ...]
    raw: Mapping[str, object]


@dataclass(frozen=True)
class RuleState:
    executed_actions: Tuple[object, ...]
    facts: frozenset[Fact]
    trace: Tuple[frozenset[Fact], ...]
    violated_constraints: Tuple[str, ...]
    digest: str

    @property
    def public_facts(self) -> Tuple[str, ...]:
        return tuple(sorted(fact.pddl for fact in self.facts))

    @property
    def monitor_facts(self) -> Tuple[str, ...]:
        return tuple(f"(violated {name})" for name in self.violated_constraints)


@dataclass(frozen=True)
class RuleTransition:
    ok: bool
    state: RuleState
    reason: str = "N/A"
    metadata: Mapping[str, object] = field(default_factory=dict)


def load_rules_schema() -> Dict[str, object]:
    path = Path(__file__).with_name("rules.schema.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("rules.schema.json must contain one JSON object")
    return payload


def _object(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuleValidationError(f"{context} must be an object")
    return value


def _array(value: object, context: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RuleValidationError(f"{context} must be an array")
    return value


def _string(value: object, context: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise RuleValidationError(f"{context} must be a non-empty string")
    return value


def _name(value: object, context: str) -> str:
    text = _string(value, context)
    if _NAME_RE.fullmatch(text) is None:
        raise RuleValidationError(f"{context} has invalid identifier {text!r}")
    return text


def parse_fact(value: object, context: str) -> Fact:
    text = _string(value, context)
    match = _FACT_RE.fullmatch(text)
    if match is None:
        raise RuleValidationError(f"{context} is not one flat fact: {text!r}")
    arguments = tuple(match.group("arguments").strip().split())
    if any(_TERM_RE.fullmatch(term) is None for term in arguments):
        raise RuleValidationError(f"{context} contains an invalid term: {text!r}")
    return Fact(match.group("predicate"), arguments)


def _condition(value: object, context: str) -> Condition:
    payload = _object(value, context)
    expected = {"all_of", "any_of", "none_of"}
    if set(payload) != expected:
        raise RuleValidationError(f"{context} must contain exactly {sorted(expected)}")

    def facts(field_name: str) -> Tuple[Fact, ...]:
        items = _array(payload[field_name], f"{context}.{field_name}")
        parsed = tuple(
            parse_fact(item, f"{context}.{field_name}[{index}]")
            for index, item in enumerate(items)
        )
        if len(set(parsed)) != len(parsed):
            raise RuleValidationError(f"{context}.{field_name} contains duplicates")
        return parsed

    result = Condition(facts("all_of"), facts("any_of"), facts("none_of"))
    overlap = (set(result.all_of) | set(result.any_of)) & set(result.none_of)
    if overlap:
        raise RuleValidationError(
            f"{context} requires and forbids the same facts: "
            + ", ".join(sorted(fact.pddl for fact in overlap))
        )
    return result


def _is_subtype(actual: str, expected: str, parents: Mapping[str, Optional[str]]) -> bool:
    current: Optional[str] = actual
    visited: set[str] = set()
    while current is not None and current not in visited:
        if current == expected:
            return True
        visited.add(current)
        current = parents.get(current)
    return False


def _validate_fact(
    fact: Fact,
    *,
    context: str,
    predicates: Mapping[str, Tuple[str, ...]],
    objects: Mapping[str, str],
    parents: Mapping[str, Optional[str]],
    variables: Optional[Mapping[str, str]] = None,
) -> None:
    signature = predicates.get(fact.predicate)
    if signature is None:
        raise RuleValidationError(f"{context} uses unknown predicate {fact.predicate!r}")
    if len(fact.arguments) != len(signature):
        raise RuleValidationError(
            f"{context} has arity {len(fact.arguments)}; {fact.predicate} expects {len(signature)}"
        )
    variable_types = variables or {}
    for index, (term, expected_type) in enumerate(zip(fact.arguments, signature), start=1):
        if term.startswith("?"):
            actual_type = variable_types.get(term[1:])
            if actual_type is None:
                raise RuleValidationError(f"{context} uses undeclared variable {term}")
        else:
            actual_type = objects.get(term)
            if actual_type is None:
                raise RuleValidationError(f"{context} uses unknown object {term!r}")
        if not _is_subtype(actual_type, expected_type, parents):
            raise RuleValidationError(
                f"{context} argument {index} has type {actual_type}; expected {expected_type}"
            )


def _validate_condition(
    condition: Condition,
    *,
    context: str,
    predicates: Mapping[str, Tuple[str, ...]],
    objects: Mapping[str, str],
    parents: Mapping[str, Optional[str]],
    variables: Optional[Mapping[str, str]] = None,
) -> None:
    for field_name, facts in (
        ("all_of", condition.all_of),
        ("any_of", condition.any_of),
        ("none_of", condition.none_of),
    ):
        for index, fact in enumerate(facts):
            _validate_fact(
                fact,
                context=f"{context}.{field_name}[{index}]",
                predicates=predicates,
                objects=objects,
                parents=parents,
                variables=variables,
            )


def parse_rule_program(text_or_payload: object) -> RuleProgram:
    """Parse and semantically validate one strict RulesBot artifact."""

    if isinstance(text_or_payload, str):
        text = text_or_payload.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                text = "\n".join(lines[1:-1])
                if text.lstrip().startswith("json\n"):
                    text = text.lstrip()[5:]
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise RuleValidationError(f"RulesBot output is not strict JSON: {error}") from error
    else:
        payload = text_or_payload
    root = _object(payload, "rules")
    if set(root) != _ROOT_KEYS:
        raise RuleValidationError(
            f"rules must contain exactly {sorted(_ROOT_KEYS)}; got {sorted(map(str, root))}"
        )
    if root["schema_version"] != SCHEMA_VERSION:
        raise RuleValidationError(f"unsupported rules schema {root['schema_version']!r}")
    domain_name = _name(root["domain_name"], "domain_name")

    parents: Dict[str, Optional[str]] = {}
    for index, raw in enumerate(_array(root["types"], "types")):
        item = _object(raw, f"types[{index}]")
        if set(item) != {"name", "parent"}:
            raise RuleValidationError(f"types[{index}] must contain name and parent")
        name = _name(item["name"], f"types[{index}].name")
        parent_text = _string(item["parent"], f"types[{index}].parent", allow_empty=True)
        parent = _name(parent_text, f"types[{index}].parent") if parent_text else None
        if name in parents:
            raise RuleValidationError(f"duplicate type {name!r}")
        parents[name] = parent
    if not parents:
        raise RuleValidationError("types must not be empty")
    for name, parent in parents.items():
        if parent is not None and parent not in parents:
            raise RuleValidationError(f"type {name!r} has unknown parent {parent!r}")
        cursor = parent
        seen = {name}
        while cursor is not None:
            if cursor in seen:
                raise RuleValidationError(f"type inheritance cycle involving {name!r}")
            seen.add(cursor)
            cursor = parents.get(cursor)

    objects: Dict[str, str] = {}
    for index, raw in enumerate(_array(root["objects"], "objects")):
        item = _object(raw, f"objects[{index}]")
        if set(item) != {"name", "type"}:
            raise RuleValidationError(f"objects[{index}] must contain name and type")
        name = _name(item["name"], f"objects[{index}].name")
        type_name = _name(item["type"], f"objects[{index}].type")
        if type_name not in parents:
            raise RuleValidationError(f"object {name!r} has unknown type {type_name!r}")
        if name in objects:
            raise RuleValidationError(f"duplicate object {name!r}")
        objects[name] = type_name

    predicates: Dict[str, Tuple[str, ...]] = {}
    mutable: set[str] = set()
    for index, raw in enumerate(_array(root["predicates"], "predicates")):
        item = _object(raw, f"predicates[{index}]")
        if set(item) != {"name", "parameter_types", "mutable"}:
            raise RuleValidationError(
                f"predicates[{index}] must contain name, parameter_types, and mutable"
            )
        name = _name(item["name"], f"predicates[{index}].name")
        signature = tuple(
            _name(value, f"predicates[{index}].parameter_types[{position}]")
            for position, value in enumerate(_array(item["parameter_types"], "parameter_types"))
        )
        unknown = [type_name for type_name in signature if type_name not in parents]
        if unknown:
            raise RuleValidationError(f"predicate {name!r} uses unknown types {unknown}")
        if name in predicates:
            raise RuleValidationError(f"duplicate predicate {name!r}")
        predicates[name] = signature
        if not isinstance(item["mutable"], bool):
            raise RuleValidationError(f"predicate {name!r}.mutable must be boolean")
        if item["mutable"]:
            mutable.add(name)

    initial = tuple(
        parse_fact(raw, f"initial_facts[{index}]")
        for index, raw in enumerate(_array(root["initial_facts"], "initial_facts"))
    )
    if len(set(initial)) != len(initial):
        raise RuleValidationError("initial_facts contains duplicates")
    for index, fact in enumerate(initial):
        _validate_fact(
            fact,
            context=f"initial_facts[{index}]",
            predicates=predicates,
            objects=objects,
            parents=parents,
        )

    actions: Dict[str, ActionRule] = {}
    for index, raw in enumerate(_array(root["actions"], "actions")):
        item = _object(raw, f"actions[{index}]")
        if set(item) != {"name", "parameters", "precondition", "effects"}:
            raise RuleValidationError(
                f"actions[{index}] must contain name, parameters, precondition, and effects"
            )
        name = _name(item["name"], f"actions[{index}].name")
        if name in actions:
            raise RuleValidationError(f"duplicate action {name!r}")
        parameters: List[Parameter] = []
        for position, raw_parameter in enumerate(_array(item["parameters"], "parameters")):
            parameter = _object(raw_parameter, f"actions[{index}].parameters[{position}]")
            if set(parameter) != {"name", "type"}:
                raise RuleValidationError(f"action {name} parameter must contain name and type")
            parameter_name = _name(parameter["name"], f"action {name} parameter name")
            parameter_type = _name(parameter["type"], f"action {name} parameter type")
            if parameter_type not in parents:
                raise RuleValidationError(
                    f"action {name} parameter {parameter_name} has unknown type {parameter_type}"
                )
            parameters.append(Parameter(parameter_name, parameter_type))
        if len({parameter.name for parameter in parameters}) != len(parameters):
            raise RuleValidationError(f"action {name} has duplicate parameters")
        variables = {parameter.name: parameter.type_name for parameter in parameters}
        precondition = _condition(item["precondition"], f"action {name}.precondition")
        effects = _object(item["effects"], f"action {name}.effects")
        if set(effects) != {"add", "delete"}:
            raise RuleValidationError(f"action {name}.effects must contain add and delete")
        add = tuple(
            parse_fact(value, f"action {name}.effects.add[{position}]")
            for position, value in enumerate(_array(effects["add"], "effects.add"))
        )
        delete = tuple(
            parse_fact(value, f"action {name}.effects.delete[{position}]")
            for position, value in enumerate(_array(effects["delete"], "effects.delete"))
        )
        _validate_condition(
            precondition,
            context=f"action {name}.precondition",
            predicates=predicates,
            objects=objects,
            parents=parents,
            variables=variables,
        )
        for field_name, facts in (("add", add), ("delete", delete)):
            for position, fact in enumerate(facts):
                _validate_fact(
                    fact,
                    context=f"action {name}.effects.{field_name}[{position}]",
                    predicates=predicates,
                    objects=objects,
                    parents=parents,
                    variables=variables,
                )
                if fact.predicate not in mutable:
                    raise RuleValidationError(
                        f"action {name} modifies immutable predicate {fact.predicate!r}"
                    )
        if set(add) & set(delete):
            raise RuleValidationError(f"action {name} adds and deletes the same template")
        actions[name] = ActionRule(name, tuple(parameters), precondition, add, delete)

    goal = _condition(root["goal"], "goal")
    _validate_condition(
        goal,
        context="goal",
        predicates=predicates,
        objects=objects,
        parents=parents,
    )
    temporal: List[TemporalRule] = []
    seen_constraint_ids: set[str] = set()
    for index, raw in enumerate(_array(root["temporal_constraints"], "temporal_constraints")):
        item = _object(raw, f"temporal_constraints[{index}]")
        if set(item) != {"id", "operator", "first", "second"}:
            raise RuleValidationError(
                f"temporal_constraints[{index}] must contain id, operator, first, second"
            )
        identifier = _name(item["id"], f"temporal_constraints[{index}].id")
        operator = _string(item["operator"], f"temporal_constraints[{index}].operator")
        if identifier in seen_constraint_ids:
            raise RuleValidationError(f"duplicate temporal constraint id {identifier!r}")
        seen_constraint_ids.add(identifier)
        if operator not in SUPPORTED_TEMPORAL_OPERATORS:
            raise RuleValidationError(f"unsupported temporal operator {operator!r}")
        first = _condition(item["first"], f"temporal constraint {identifier}.first")
        second = _condition(item["second"], f"temporal constraint {identifier}.second")
        for label, condition in (("first", first), ("second", second)):
            _validate_condition(
                condition,
                context=f"temporal constraint {identifier}.{label}",
                predicates=predicates,
                objects=objects,
                parents=parents,
            )
        if operator in {"sometime-before", "sometime-after"} and second.empty:
            raise RuleValidationError(f"{operator} constraint {identifier} needs second condition")
        if operator not in {"sometime-before", "sometime-after"} and not second.empty:
            raise RuleValidationError(f"{operator} constraint {identifier} must use empty second condition")
        temporal.append(TemporalRule(identifier, operator, first, second))

    source_constraints = tuple(
        _string(value, f"source_constraints[{index}]")
        for index, value in enumerate(_array(root["source_constraints"], "source_constraints"))
    )
    return RuleProgram(
        domain_name=domain_name,
        type_parents=dict(parents),
        object_types=dict(objects),
        predicates=dict(predicates),
        mutable_predicates=frozenset(mutable),
        actions=dict(actions),
        initial_facts=frozenset(initial),
        goal=goal,
        temporal_constraints=tuple(temporal),
        source_constraints=source_constraints,
        raw=dict(root),
    )


def _bind_fact(fact: Fact, bindings: Mapping[str, str]) -> Fact:
    return Fact(
        fact.predicate,
        tuple(
            bindings.get(term[1:], term) if term.startswith("?") else term
            for term in fact.arguments
        ),
    )


def _bind_condition(condition: Condition, bindings: Mapping[str, str]) -> Condition:
    return Condition(
        tuple(_bind_fact(fact, bindings) for fact in condition.all_of),
        tuple(_bind_fact(fact, bindings) for fact in condition.any_of),
        tuple(_bind_fact(fact, bindings) for fact in condition.none_of),
    )


def _state_digest(actions: Sequence[object], facts: Iterable[Fact], trace_length: int) -> str:
    action_strings = []
    for action in actions:
        name = str(getattr(action, "name", action))
        args = tuple(str(value) for value in getattr(action, "args", ()))
        action_strings.append([name, *args])
    payload = {
        "actions": action_strings,
        "facts": sorted(fact.pddl for fact in facts),
        "trace_length": trace_length,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class PromptRuleInterpreter:
    """Execute and verify a :class:`RuleProgram` without domain callbacks."""

    def __init__(self, program: RuleProgram):
        self.program = program

    def initial_state(self) -> RuleState:
        facts = self.program.initial_facts
        trace = (facts,)
        violations = self._irreversible_violations(trace)
        return RuleState((), facts, trace, violations, _state_digest((), facts, 1))

    def copy_state(self, state: RuleState) -> RuleState:
        return RuleState(
            tuple(state.executed_actions),
            frozenset(state.facts),
            tuple(frozenset(snapshot) for snapshot in state.trace),
            tuple(state.violated_constraints),
            state.digest,
        )

    def apply(self, state: RuleState, action: object, action_index: int) -> RuleTransition:
        name = str(getattr(action, "name", ""))
        arguments = tuple(str(value) for value in getattr(action, "args", ()))
        rule = self.program.actions.get(name)
        if rule is None:
            return RuleTransition(
                False,
                state,
                f"Action {action_index} uses unknown induced action {name!r}",
                {"failure_kind": "action_binding", "rule_source": "prompt-induced-json"},
            )
        if len(arguments) != len(rule.parameters):
            return RuleTransition(
                False,
                state,
                f"Action {action_index} {name} has {len(arguments)} arguments; expected {len(rule.parameters)}",
                {"failure_kind": "action_binding", "rule_source": "prompt-induced-json"},
            )
        bindings = dict(zip((parameter.name for parameter in rule.parameters), arguments))
        for parameter, value in zip(rule.parameters, arguments):
            actual = self.program.object_types.get(value)
            if actual is None:
                return RuleTransition(
                    False,
                    state,
                    f"Action {action_index} {name} uses unknown object {value!r}",
                    {"failure_kind": "action_binding", "rule_source": "prompt-induced-json"},
                )
            if not _is_subtype(actual, parameter.type_name, self.program.type_parents):
                return RuleTransition(
                    False,
                    state,
                    f"Action {action_index} {name} binds {value}:{actual} to {parameter.name}:{parameter.type_name}",
                    {"failure_kind": "action_binding", "rule_source": "prompt-induced-json"},
                )
        precondition = _bind_condition(rule.precondition, bindings)
        if not precondition.holds(state.facts):
            missing = [fact.pddl for fact in precondition.all_of if fact not in state.facts]
            absent_any = (
                [fact.pddl for fact in precondition.any_of]
                if precondition.any_of
                and not any(fact in state.facts for fact in precondition.any_of)
                else []
            )
            forbidden = [fact.pddl for fact in precondition.none_of if fact in state.facts]
            return RuleTransition(
                False,
                state,
                f"Action {action_index} is inapplicable under induced rules: {name}{arguments}; "
                f"missing={missing + absent_any}; forbidden={forbidden}",
                {
                    "failure_kind": "action_precondition",
                    "unsatisfied_conditions": missing + absent_any + forbidden,
                    "rule_source": "prompt-induced-json",
                },
            )
        next_facts = set(state.facts)
        deleted = tuple(_bind_fact(fact, bindings) for fact in rule.delete)
        added = tuple(_bind_fact(fact, bindings) for fact in rule.add)
        next_facts.difference_update(deleted)
        next_facts.update(added)
        frozen = frozenset(next_facts)
        trace = (*state.trace, frozen)
        violations = self._irreversible_violations(trace)
        newly_violated = [name for name in violations if name not in state.violated_constraints]
        if newly_violated:
            return RuleTransition(
                False,
                state,
                f"Action {action_index} violates induced temporal constraints: {newly_violated}",
                {
                    "failure_kind": "constraint",
                    "constraint_failure": True,
                    "unsatisfied_conditions": newly_violated,
                    "rule_source": "prompt-induced-json",
                },
            )
        actions = (*state.executed_actions, action)
        next_state = RuleState(
            actions,
            frozen,
            trace,
            violations,
            _state_digest(actions, frozen, len(trace)),
        )
        return RuleTransition(
            True,
            next_state,
            metadata={
                "rule_source": "prompt-induced-json",
                "public_facts": list(next_state.public_facts),
                "constraint_status": self.constraint_report(next_state),
            },
        )

    def _irreversible_violations(self, trace: Sequence[frozenset[Fact]]) -> Tuple[str, ...]:
        failures: List[str] = []
        for rule in self.program.temporal_constraints:
            truth = [rule.first.holds(state) for state in trace]
            if rule.operator == "always" and not all(truth):
                failures.append(rule.identifier)
            elif rule.operator == "at-most-once":
                entries = sum(
                    value and (index == 0 or not truth[index - 1])
                    for index, value in enumerate(truth)
                )
                if entries > 1:
                    failures.append(rule.identifier)
            elif rule.operator == "sometime-before":
                second_truth = [rule.second.holds(state) for state in trace]
                for index, triggered in enumerate(truth):
                    if triggered and not any(second_truth[:index]):
                        failures.append(rule.identifier)
                        break
        return tuple(failures)

    def constraint_report(self, state: RuleState) -> Dict[str, object]:
        report: Dict[str, object] = {}
        for rule in self.program.temporal_constraints:
            first_truth = [rule.first.holds(snapshot) for snapshot in state.trace]
            second_truth = [rule.second.holds(snapshot) for snapshot in state.trace]
            if rule.operator == "sometime":
                satisfied = any(first_truth)
            elif rule.operator == "always":
                satisfied = all(first_truth)
            elif rule.operator == "at-most-once":
                entries = sum(
                    value and (index == 0 or not first_truth[index - 1])
                    for index, value in enumerate(first_truth)
                )
                satisfied = entries <= 1
            elif rule.operator == "sometime-before":
                satisfied = all(
                    not triggered or any(second_truth[:index])
                    for index, triggered in enumerate(first_truth)
                )
            else:
                satisfied = all(
                    not triggered or any(second_truth[index:])
                    for index, triggered in enumerate(first_truth)
                )
            report[rule.identifier] = {"operator": rule.operator, "satisfied": satisfied}
        return report

    def completion_report(self, state: RuleState) -> Dict[str, object]:
        goal_satisfied = self.program.goal.holds(state.facts)
        constraints = self.constraint_report(state)
        unsatisfied = [
            identifier
            for identifier, payload in constraints.items()
            if isinstance(payload, Mapping) and payload.get("satisfied") is not True
        ]
        return {
            "valid": goal_satisfied and not unsatisfied and not state.violated_constraints,
            "goal_satisfied": goal_satisfied,
            "unsatisfied_constraints": unsatisfied,
            "violated_constraints": list(state.violated_constraints),
            "constraint_status": constraints,
            "rule_source": "prompt-induced-json",
        }

    def complete(self, state: RuleState) -> bool:
        return bool(self.completion_report(state)["valid"])


__all__ = [
    "ActionRule",
    "Condition",
    "Fact",
    "Parameter",
    "PromptRuleInterpreter",
    "RuleProgram",
    "RuleState",
    "RuleTransition",
    "RuleValidationError",
    "SCHEMA_VERSION",
    "SUPPORTED_TEMPORAL_OPERATORS",
    "TemporalRule",
    "load_rules_schema",
    "parse_fact",
    "parse_rule_program",
]
