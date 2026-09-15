"""Compact, canonical generation contracts for DynaPlan.

The existing DynaPlan compilers consume a tagged text representation.  That
representation remains the internal compatibility boundary; this module adds
an optional JSON wire format for DecisionBot and HierarchyPlanner and
deterministically serializes accepted JSON into the existing tagged form.

This is deliberately a *structural* codec, not a semantic state verifier.  It
checks JSON shape, identifiers, hierarchy call resolution, arity, argument
types, and the call graph.  Existing domain adapters remain responsible for
validating checkpoint facts, task goals, temporal constraints, and the
meaning of the expanded action trace.

Nothing is enabled merely by importing this module.  Callers must explicitly
pass ``enabled=True`` to :func:`configure_compact_stage_request` and invoke the
matching decoder.  This makes the v1.2 behavior the default and gives v1.3 an
independently switchable ``compact_generation_contracts`` feature flag.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


COMPACT_CONTRACT_REVISION = "dynaplan_compact_generation_contracts_v1"
COMPACT_GENERATION_CONTRACTS_DEFAULT = False
DECISION_SCHEMA_NAME = "dynaplan_compact_decision_v1"
HIERARCHY_SCHEMA_NAME = "dynaplan_compact_hierarchy_v1"

DECISION_KIND_LEXICON = "lexicon"
DECISION_KIND_HANOI = "hanoi"
_DECISION_KINDS = {DECISION_KIND_LEXICON, DECISION_KIND_HANOI}

_FUNCTION_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ACTION_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_TAG_INJECTION_RE = re.compile(
    r"```|(?:start|end)_subtask(?:_goalstate|_funcs)?_", re.IGNORECASE
)


@dataclass(frozen=True)
class CompactDecodeResult:
    """Result of strict JSON validation and tagged serialization."""

    valid: bool
    tagged_text: Optional[str] = None
    document: Optional[Mapping[str, object]] = None
    errors: Tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors", tuple(str(error) for error in self.errors))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def reason(self) -> str:
        return "; ".join(self.errors) if self.errors else "N/A"


@dataclass(frozen=True)
class FunctionSignature:
    """Types required by each parameter of one already-validated H1 function.

    A parameter position stores a set because a composed parameter may flow to
    several lower-level positions.  Its concrete argument must satisfy every
    type requirement in that set.
    """

    parameter_requirements: Tuple[frozenset[str], ...]

    @classmethod
    def typed(cls, *parameter_types: str) -> "FunctionSignature":
        return cls(tuple(frozenset((value,)) for value in parameter_types))

    @property
    def arity(self) -> int:
        return len(self.parameter_requirements)


@dataclass(frozen=True)
class CompactHierarchyVocabulary:
    """Domain-supplied names and types needed for structural validation."""

    base_functions: Mapping[str, FunctionSignature]
    primitive_arities: Mapping[str, int]
    object_types: Mapping[str, str]
    type_parents: Mapping[str, str] = field(default_factory=dict)
    # The inherited Flat-Hanoi compiler intentionally permits a composed
    # mapping to close over concrete public peg names.  LexiCon mappings do
    # not.  Keep that established exception explicit and domain-scoped rather
    # than weakening the shared contract for every benchmark.
    allow_grounded_mapping_arguments: bool = False

    def __post_init__(self) -> None:
        bases = dict(self.base_functions)
        primitives = {str(name): int(arity) for name, arity in self.primitive_arities.items()}
        objects = {str(name): str(kind) for name, kind in self.object_types.items()}
        parents = {str(child): str(parent) for child, parent in self.type_parents.items()}
        object.__setattr__(self, "base_functions", bases)
        object.__setattr__(self, "primitive_arities", primitives)
        object.__setattr__(self, "object_types", objects)
        object.__setattr__(self, "type_parents", parents)
        object.__setattr__(
            self,
            "allow_grounded_mapping_arguments",
            bool(self.allow_grounded_mapping_arguments),
        )

        overlap = set(bases) & set(primitives)
        if overlap:
            raise ValueError(
                "Base functions and H0 primitives must be disjoint: "
                + ", ".join(sorted(overlap))
            )
        for name, signature in bases.items():
            if not _FUNCTION_RE.fullmatch(name):
                raise ValueError(f"Invalid base function name {name!r}")
            if not isinstance(signature, FunctionSignature):
                raise TypeError(f"Base function {name!r} has no FunctionSignature")
        for name, arity in primitives.items():
            # LexiCon's H0 names are lower-case while the inherited Flat-Hanoi
            # compiler uses MoveCoroutine/GrabCoroutine/DropCoroutine.  Both
            # are established action identifiers at this boundary.
            if not _ACTION_NAME_RE.fullmatch(name):
                raise ValueError(f"Invalid primitive action name {name!r}")
            if arity < 0:
                raise ValueError(f"Primitive {name!r} has a negative arity")
        for name, type_name in objects.items():
            if not _IDENTIFIER_RE.fullmatch(name):
                raise ValueError(f"Invalid concrete object name {name!r}")
            if not _IDENTIFIER_RE.fullmatch(type_name):
                raise ValueError(f"Invalid object type {type_name!r}")


def _unique(values: Iterable[str]) -> Tuple[str, ...]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _strict_json_object(text: str, *, stage: str) -> Tuple[Optional[Dict[str, object]], Tuple[str, ...]]:
    if not isinstance(text, str) or not text.strip():
        return None, (f"{stage} output must be one non-empty JSON object",)

    duplicate_keys: List[str] = []

    def pairs_hook(pairs: Sequence[Tuple[str, object]]) -> Dict[str, object]:
        value: Dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                duplicate_keys.append(key)
            value[key] = item
        return value

    try:
        payload = json.loads(text, object_pairs_hook=pairs_hook)
    except json.JSONDecodeError as error:
        return None, (f"{stage} output is not strict JSON: {error}",)
    if duplicate_keys:
        return None, (
            f"{stage} output contains duplicate JSON keys: "
            + ", ".join(sorted(set(duplicate_keys))),
        )
    if not isinstance(payload, dict):
        return None, (f"{stage} JSON root must be an object",)
    return payload, ()


def _exact_keys(
    value: Mapping[str, object], expected: Iterable[str], *, context: str
) -> List[str]:
    expected_set = set(expected)
    actual_set = set(value)
    if actual_set == expected_set:
        return []
    return [
        f"{context} must contain exactly {sorted(expected_set)}; got {sorted(actual_set)}"
    ]


def _string_array(value: object, *, context: str) -> Tuple[List[str], List[str]]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return [], [f"{context} must be a string array"]
    return list(value), []


def _integer_array(value: object, *, context: str) -> Tuple[List[int], List[str]]:
    if not isinstance(value, list) or any(
        not isinstance(item, int) or isinstance(item, bool) for item in value
    ):
        return [], [f"{context} must be an integer array"]
    return list(value), []


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def decision_response_schema(
    kind: str,
    *,
    hanoi_checkpoint_fields: Sequence[str] = (),
    hanoi_ring_names: Sequence[str] = (),
) -> Dict[str, object]:
    """Return the provider-facing JSON schema for a compact DecisionBot call."""

    if kind not in _DECISION_KINDS:
        raise ValueError(f"Unknown compact Decision contract kind {kind!r}")
    if kind == DECISION_KIND_LEXICON:
        checkpoint: Dict[str, object] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "required_true": {"type": "array", "items": {"type": "string"}},
                "required_false": {"type": "array", "items": {"type": "string"}},
                "constraints_addressed": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                },
            },
            "required": [
                "required_true",
                "required_false",
                "constraints_addressed",
            ],
        }
    else:
        # OpenAI strict structured output rejects unconstrained objects.  A
        # Flat-Hanoi checkpoint is nevertheless dynamic because peg names are
        # task data.  Supplying the public task's concrete peg (and optionally
        # ring) names produces a strict schema without changing the checkpoint
        # representation consumed by the legacy parser.
        fields = list(hanoi_checkpoint_fields)
        if not fields or any(
            not isinstance(name, str) or not _IDENTIFIER_RE.fullmatch(name)
            for name in fields
        ):
            raise ValueError(
                "Strict Hanoi Decision schema requires valid concrete peg fields"
            )
        if len(fields) != len(set(fields)):
            raise ValueError("Hanoi checkpoint peg fields must be unique")
        rings = list(hanoi_ring_names)
        if any(
            not isinstance(name, str) or not _IDENTIFIER_RE.fullmatch(name)
            for name in rings
        ) or len(rings) != len(set(rings)):
            raise ValueError("Hanoi ring names must be unique identifiers")
        item_schema: Dict[str, object] = {"type": "string"}
        if rings:
            item_schema["enum"] = rings
        checkpoint = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                name: {"type": "array", "items": dict(item_schema)}
                for name in fields
            },
            "required": fields,
        }

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "subtasks": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "integer", "minimum": 1},
                        "description": {"type": "string", "minLength": 1},
                        "checkpoint": checkpoint,
                    },
                    "required": ["id", "description", "checkpoint"],
                },
            }
        },
        "required": ["subtasks"],
    }


def hierarchy_response_schema() -> Dict[str, object]:
    """Return the provider-facing schema for a compact HierarchyPlanner call."""

    call_schema: Dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "pattern": r"^[A-Z][A-Za-z0-9_]*$"},
            "args": {
                "type": "array",
                "items": {"type": "string", "pattern": r"^[a-z][a-z0-9_]*$"},
            },
        },
        "required": ["name", "args"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "mappings": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {
                            "type": "string",
                            "pattern": r"^[A-Z][A-Za-z0-9_]*$",
                        },
                        "params": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "pattern": r"^[a-z][a-z0-9_]*$",
                            },
                        },
                        "calls": {
                            "type": "array",
                            "minItems": 1,
                            "items": call_schema,
                        },
                    },
                    "required": ["name", "params", "calls"],
                },
            },
            "subtasks": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "integer", "minimum": 1},
                        "calls": {
                            "type": "array",
                            "minItems": 1,
                            "items": call_schema,
                        },
                    },
                    "required": ["id", "calls"],
                },
            },
        },
        "required": ["mappings", "subtasks"],
    }


def decode_compact_decision(
    text: str,
    *,
    kind: str,
    hanoi_checkpoint_fields: Sequence[str] = (),
    hanoi_ring_names: Sequence[str] = (),
) -> CompactDecodeResult:
    """Validate DecisionBot JSON and serialize it to the legacy tagged form."""

    if kind not in _DECISION_KINDS:
        return CompactDecodeResult(False, errors=(f"Unknown Decision kind {kind!r}",))
    payload, load_errors = _strict_json_object(text, stage="DecisionBot")
    if payload is None:
        return CompactDecodeResult(False, errors=load_errors)

    errors = _exact_keys(payload, ("subtasks",), context="DecisionBot root")
    raw_subtasks = payload.get("subtasks")
    if not isinstance(raw_subtasks, list) or not raw_subtasks:
        errors.append("DecisionBot subtasks must be a non-empty array")
        raw_subtasks = []

    normalized: List[Dict[str, object]] = []
    for position, raw_subtask in enumerate(raw_subtasks, start=1):
        context = f"DecisionBot subtask {position}"
        if not isinstance(raw_subtask, dict):
            errors.append(f"{context} must be an object")
            continue
        errors.extend(
            _exact_keys(raw_subtask, ("id", "description", "checkpoint"), context=context)
        )
        index = raw_subtask.get("id")
        if not isinstance(index, int) or isinstance(index, bool) or index < 1:
            errors.append(f"{context} id must be a positive integer")
            continue
        if index != position:
            errors.append(
                f"DecisionBot subtask ids must be ordered 1..N; position {position} has {index}"
            )
        description = raw_subtask.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{context} description must be a non-empty string")
            continue
        if description != description.strip():
            errors.append(f"{context} description must be trimmed")
        if _TAG_INJECTION_RE.search(description):
            errors.append(f"{context} description contains reserved tagged syntax")

        checkpoint = raw_subtask.get("checkpoint")
        if not isinstance(checkpoint, dict):
            errors.append(f"{context} checkpoint must be an object")
            continue
        if kind == DECISION_KIND_LEXICON:
            errors.extend(
                _exact_keys(
                    checkpoint,
                    ("required_true", "required_false", "constraints_addressed"),
                    context=f"{context} checkpoint",
                )
            )
            required_true, item_errors = _string_array(
                checkpoint.get("required_true"), context=f"{context} required_true"
            )
            errors.extend(item_errors)
            required_false, item_errors = _string_array(
                checkpoint.get("required_false"), context=f"{context} required_false"
            )
            errors.extend(item_errors)
            constraints, item_errors = _integer_array(
                checkpoint.get("constraints_addressed"),
                context=f"{context} constraints_addressed",
            )
            errors.extend(item_errors)
            if len(required_true) != len(set(required_true)):
                errors.append(f"{context} required_true contains duplicates")
            if len(required_false) != len(set(required_false)):
                errors.append(f"{context} required_false contains duplicates")
            if set(required_true) & set(required_false):
                errors.append(f"{context} requires the same fact true and false")
            if constraints != sorted(set(constraints)):
                errors.append(f"{context} constraints_addressed must be sorted and unique")
            normalized_checkpoint: Dict[str, object] = {
                "required_true": required_true,
                "required_false": required_false,
                "constraints_addressed": constraints,
            }
        else:
            fields = list(hanoi_checkpoint_fields)
            rings = list(hanoi_ring_names)
            if fields:
                errors.extend(
                    _exact_keys(
                        checkpoint,
                        fields,
                        context=f"{context} checkpoint",
                    )
                )
                normalized_checkpoint = {}
                flattened: List[str] = []
                for field_name in fields:
                    stack, item_errors = _string_array(
                        checkpoint.get(field_name),
                        context=f"{context} checkpoint {field_name}",
                    )
                    errors.extend(item_errors)
                    for ring in stack:
                        if not _IDENTIFIER_RE.fullmatch(ring):
                            errors.append(
                                f"{context} checkpoint has invalid ring identifier {ring!r}"
                            )
                        if rings and ring not in rings:
                            errors.append(
                                f"{context} checkpoint uses unknown ring {ring!r}"
                            )
                    flattened.extend(stack)
                    normalized_checkpoint[field_name] = stack
                if rings and sorted(flattened) != sorted(rings):
                    errors.append(
                        f"{context} checkpoint must place every ring exactly once"
                    )
            else:
                normalized_checkpoint = dict(checkpoint)

        normalized.append(
            {
                "id": index,
                "description": description.strip(),
                "checkpoint": normalized_checkpoint,
            }
        )

    if errors:
        return CompactDecodeResult(
            False,
            document=payload,
            errors=_unique(errors),
            metadata={"contract_revision": COMPACT_CONTRACT_REVISION},
        )

    blocks: List[str] = []
    for subtask in normalized:
        index = int(subtask["id"])
        blocks.extend(
            (
                f"```start_subtask_{index}\n{subtask['description']}\n```end_subtask_{index}",
                "```start_subtask_goalstate_"
                f"{index}\n{_canonical_json(subtask['checkpoint'])}\n"
                f"```end_subtask_goalstate_{index}",
            )
        )
    tagged = "\n\n".join(blocks)
    document = {"subtasks": normalized}
    return CompactDecodeResult(
        True,
        tagged_text=tagged,
        document=document,
        metadata={
            "contract_revision": COMPACT_CONTRACT_REVISION,
            "schema_name": DECISION_SCHEMA_NAME,
            "subtask_count": len(normalized),
            "raw_sha256": sha256(text.encode("utf-8")).hexdigest(),
            "tagged_sha256": sha256(tagged.encode("utf-8")).hexdigest(),
        },
    )


@dataclass(frozen=True)
class _Call:
    name: str
    args: Tuple[str, ...]

    def tagged(self) -> str:
        return f"{self.name}({', '.join(self.args)})"


@dataclass(frozen=True)
class _Mapping:
    name: str
    params: Tuple[str, ...]
    calls: Tuple[_Call, ...]


def _parse_call_document(value: object, *, context: str) -> Tuple[Optional[_Call], List[str]]:
    if not isinstance(value, dict):
        return None, [f"{context} must be an object"]
    errors = _exact_keys(value, ("name", "args"), context=context)
    name = value.get("name")
    if not isinstance(name, str) or not _FUNCTION_RE.fullmatch(name):
        errors.append(f"{context} name must be an uppercase function identifier")
    args, item_errors = _string_array(value.get("args"), context=f"{context} args")
    errors.extend(item_errors)
    for argument in args:
        if not _IDENTIFIER_RE.fullmatch(argument):
            errors.append(f"{context} has invalid argument identifier {argument!r}")
    if errors:
        return None, errors
    return _Call(str(name), tuple(args)), []


def _is_subtype(actual: str, expected: str, parents: Mapping[str, str]) -> bool:
    current = actual
    visited: set[str] = set()
    while True:
        if current == expected:
            return True
        if current in visited or current not in parents:
            return False
        visited.add(current)
        current = parents[current]


def _can_satisfy(
    actual: str, requirements: Iterable[str], parents: Mapping[str, str]
) -> bool:
    return all(_is_subtype(actual, expected, parents) for expected in requirements)


def decode_compact_hierarchy(
    text: str,
    *,
    vocabulary: CompactHierarchyVocabulary,
    expected_subtask_ids: Sequence[int],
) -> CompactDecodeResult:
    """Validate HierarchyPlanner JSON and serialize legacy mapping/call blocks."""

    payload, load_errors = _strict_json_object(text, stage="HierarchyPlanner")
    if payload is None:
        return CompactDecodeResult(False, errors=load_errors)

    errors = _exact_keys(payload, ("mappings", "subtasks"), context="Hierarchy root")
    raw_mappings = payload.get("mappings")
    raw_subtasks = payload.get("subtasks")
    if not isinstance(raw_mappings, list) or not raw_mappings:
        errors.append("Hierarchy mappings must be a non-empty array")
        raw_mappings = []
    if not isinstance(raw_subtasks, list) or not raw_subtasks:
        errors.append("Hierarchy subtasks must be a non-empty array")
        raw_subtasks = []

    mappings: Dict[str, _Mapping] = {}
    mapping_order: List[str] = []
    for position, raw_mapping in enumerate(raw_mappings, start=1):
        context = f"Hierarchy mapping {position}"
        if not isinstance(raw_mapping, dict):
            errors.append(f"{context} must be an object")
            continue
        errors.extend(_exact_keys(raw_mapping, ("name", "params", "calls"), context=context))
        name = raw_mapping.get("name")
        if not isinstance(name, str) or not _FUNCTION_RE.fullmatch(name):
            errors.append(f"{context} name must be an uppercase function identifier")
            continue
        if name in mappings:
            errors.append(f"Hierarchy contains duplicate mapping {name}")
            continue
        if name in vocabulary.base_functions:
            errors.append(f"Custom mapping {name} collides with an H1 function")
        if name in vocabulary.primitive_arities:
            errors.append(f"Custom mapping {name} collides with an H0 action")
        params, item_errors = _string_array(raw_mapping.get("params"), context=f"{context} params")
        errors.extend(item_errors)
        for parameter in params:
            if not _IDENTIFIER_RE.fullmatch(parameter):
                errors.append(f"{context} has invalid parameter {parameter!r}")
        if len(params) != len(set(params)):
            errors.append(f"{context} has duplicate parameters")
        raw_calls = raw_mapping.get("calls")
        if not isinstance(raw_calls, list) or not raw_calls:
            errors.append(f"{context} calls must be a non-empty array")
            raw_calls = []
        calls: List[_Call] = []
        for call_position, raw_call in enumerate(raw_calls, start=1):
            call, call_errors = _parse_call_document(
                raw_call, context=f"{context} call {call_position}"
            )
            errors.extend(call_errors)
            if call is not None:
                calls.append(call)
        mappings[name] = _Mapping(name, tuple(params), tuple(calls))
        mapping_order.append(name)

    known_functions = set(vocabulary.base_functions) | set(mappings)
    for mapping in mappings.values():
        param_set = set(mapping.params)
        used: set[str] = set()
        for call in mapping.calls:
            if call.name in vocabulary.primitive_arities:
                errors.append(
                    f"Mapping {mapping.name} calls raw H0 action {call.name}; use H1 functions"
                )
                continue
            if call.name not in known_functions:
                errors.append(f"Mapping {mapping.name} calls unknown function {call.name}")
                continue
            expected_arity = (
                vocabulary.base_functions[call.name].arity
                if call.name in vocabulary.base_functions
                else len(mappings[call.name].params)
            )
            if len(call.args) != expected_arity:
                errors.append(
                    f"Mapping {mapping.name} calls {call.name} with {len(call.args)} "
                    f"arguments; expected {expected_arity}"
                )
            for argument in call.args:
                if argument not in param_set:
                    if not (
                        vocabulary.allow_grounded_mapping_arguments
                        and argument in vocabulary.object_types
                    ):
                        errors.append(
                            f"Mapping {mapping.name} uses unbound argument {argument!r} "
                            f"in {call.tagged()}"
                        )
                else:
                    used.add(argument)
        unused = [parameter for parameter in mapping.params if parameter not in used]
        if unused:
            errors.append(
                f"Mapping {mapping.name} has unused parameters: {', '.join(unused)}"
            )

    levels: Dict[str, int] = {name: 1 for name in vocabulary.base_functions}
    visiting: List[str] = []

    def infer_level(name: str) -> Optional[int]:
        if name in levels:
            return levels[name]
        if name in visiting:
            start = visiting.index(name)
            errors.append("Hierarchy cycle: " + " -> ".join((*visiting[start:], name)))
            return None
        mapping = mappings.get(name)
        if mapping is None:
            return None
        visiting.append(name)
        child_levels = [
            level
            for call in mapping.calls
            if call.name in known_functions
            for level in (infer_level(call.name),)
            if level is not None
        ]
        visiting.pop()
        if not child_levels:
            errors.append(f"Mapping {name} has no resolvable lower-level calls")
            return None
        level = max(child_levels) + 1
        levels[name] = level
        return level

    for name in mapping_order:
        inferred = infer_level(name)
        if inferred is not None and inferred < 2:
            errors.append(f"Custom mapping {name} must infer to H2 or deeper")

    requirements: Dict[str, Tuple[frozenset[str], ...]] = {
        name: signature.parameter_requirements
        for name, signature in vocabulary.base_functions.items()
    }
    requirement_visiting: set[str] = set()

    def infer_requirements(name: str) -> Tuple[frozenset[str], ...]:
        if name in requirements:
            return requirements[name]
        mapping = mappings.get(name)
        if mapping is None or name in requirement_visiting:
            return ()
        requirement_visiting.add(name)
        collected: List[set[str]] = [set() for _ in mapping.params]
        positions = {parameter: index for index, parameter in enumerate(mapping.params)}
        for call in mapping.calls:
            target_requirements = infer_requirements(call.name)
            if len(call.args) != len(target_requirements):
                continue
            for argument, needed in zip(call.args, target_requirements):
                position = positions.get(argument)
                if position is not None:
                    collected[position].update(needed)
        requirement_visiting.remove(name)
        result = tuple(frozenset(values) for values in collected)
        requirements[name] = result
        return result

    available_types = set(vocabulary.object_types.values())
    for name in mapping_order:
        inferred = infer_requirements(name)
        mapping = mappings[name]
        for parameter, needed in zip(mapping.params, inferred):
            if not needed:
                errors.append(
                    f"Mapping {name} parameter {parameter!r} has no grounded type requirement"
                )
            elif not any(
                _can_satisfy(actual, needed, vocabulary.type_parents)
                for actual in available_types
            ):
                errors.append(
                    f"Mapping {name} parameter {parameter!r} has incompatible type "
                    f"requirements {sorted(needed)}"
                )

        # Grounded arguments are an explicit Flat-Hanoi compatibility path.
        # They still have to name a known public object and satisfy the same
        # inferred parameter types as a normal subtask call.  This therefore
        # accepts concrete peg closures without accepting arbitrary literals,
        # unknown objects, or a ring where a peg is required.
        if vocabulary.allow_grounded_mapping_arguments:
            param_set = set(mapping.params)
            for call in mapping.calls:
                target_requirements = infer_requirements(call.name)
                if len(call.args) != len(target_requirements):
                    continue
                for argument_position, (argument, needed) in enumerate(
                    zip(call.args, target_requirements), start=1
                ):
                    if argument in param_set:
                        continue
                    actual = vocabulary.object_types.get(argument)
                    if actual is None:
                        # The unbound-argument pass above already records the
                        # actionable structural error.
                        continue
                    if not _can_satisfy(
                        actual, needed, vocabulary.type_parents
                    ):
                        errors.append(
                            f"Mapping {name} grounded argument {argument!r} ({actual}) "
                            f"is incompatible with {call.name} parameter "
                            f"{argument_position} requirements {sorted(needed)}"
                        )

    parsed_subtasks: List[Tuple[int, Tuple[_Call, ...]]] = []
    observed_ids: List[int] = []
    for position, raw_subtask in enumerate(raw_subtasks, start=1):
        context = f"Hierarchy subtask {position}"
        if not isinstance(raw_subtask, dict):
            errors.append(f"{context} must be an object")
            continue
        errors.extend(_exact_keys(raw_subtask, ("id", "calls"), context=context))
        index = raw_subtask.get("id")
        if not isinstance(index, int) or isinstance(index, bool) or index < 1:
            errors.append(f"{context} id must be a positive integer")
            continue
        observed_ids.append(index)
        raw_calls = raw_subtask.get("calls")
        if not isinstance(raw_calls, list) or not raw_calls:
            errors.append(f"{context} calls must be a non-empty array")
            raw_calls = []
        calls: List[_Call] = []
        for call_position, raw_call in enumerate(raw_calls, start=1):
            call, call_errors = _parse_call_document(
                raw_call, context=f"{context} call {call_position}"
            )
            errors.extend(call_errors)
            if call is None:
                continue
            calls.append(call)
            if call.name in vocabulary.primitive_arities:
                errors.append(f"{context} calls raw H0 action {call.name}")
                continue
            if call.name not in known_functions:
                errors.append(f"{context} calls unknown function {call.name}")
                continue
            expected_arity = (
                vocabulary.base_functions[call.name].arity
                if call.name in vocabulary.base_functions
                else len(mappings[call.name].params)
            )
            if len(call.args) != expected_arity:
                errors.append(
                    f"{context} calls {call.name} with {len(call.args)} arguments; "
                    f"expected {expected_arity}"
                )
                continue
            needed_by_position = infer_requirements(call.name)
            for argument_position, (argument, needed) in enumerate(
                zip(call.args, needed_by_position), start=1
            ):
                actual = vocabulary.object_types.get(argument)
                if actual is None:
                    errors.append(f"{context} uses unknown object {argument!r}")
                elif not _can_satisfy(actual, needed, vocabulary.type_parents):
                    errors.append(
                        f"{context} argument {argument!r} ({actual}) is incompatible "
                        f"with {call.name} parameter {argument_position} requirements "
                        f"{sorted(needed)}"
                    )
        parsed_subtasks.append((index, tuple(calls)))

    expected_ids = list(expected_subtask_ids)
    if any(not isinstance(index, int) or isinstance(index, bool) or index < 1 for index in expected_ids):
        errors.append("Expected Decision subtask ids must be positive integers")
    if observed_ids != expected_ids:
        errors.append(
            f"Hierarchy subtask ids must be exactly {expected_ids} in order; got {observed_ids}"
        )

    if errors:
        return CompactDecodeResult(
            False,
            document=payload,
            errors=_unique(errors),
            metadata={"contract_revision": COMPACT_CONTRACT_REVISION},
        )

    mapping_lines = []
    for name in mapping_order:
        mapping = mappings[name]
        body = ", ".join(call.tagged() for call in mapping.calls)
        mapping_lines.append(f"{name}({', '.join(mapping.params)}) = [{body}]")
    blocks = ["```start_mapping\n" + ",\n".join(mapping_lines) + "\n```end_mapping"]
    for index, calls in parsed_subtasks:
        blocks.append(
            f"```start_subtask_funcs_{index}\n"
            + ", ".join(call.tagged() for call in calls)
            + f"\n```end_subtask_funcs_{index}"
        )
    tagged = "\n\n".join(blocks)
    return CompactDecodeResult(
        True,
        tagged_text=tagged,
        document=payload,
        metadata={
            "contract_revision": COMPACT_CONTRACT_REVISION,
            "schema_name": HIERARCHY_SCHEMA_NAME,
            "mapping_count": len(mapping_order),
            "subtask_count": len(parsed_subtasks),
            "max_level": max(levels.values(), default=0),
            "raw_sha256": sha256(text.encode("utf-8")).hexdigest(),
            "tagged_sha256": sha256(tagged.encode("utf-8")).hexdigest(),
        },
    )


def decision_contract_prompt(
    kind: str,
    *,
    hanoi_checkpoint_fields: Sequence[str] = (),
    hanoi_ring_names: Sequence[str] = (),
) -> str:
    """Short authoritative output-format addendum for DecisionBot."""

    if kind not in _DECISION_KINDS:
        raise ValueError(f"Unknown compact Decision contract kind {kind!r}")
    if kind == DECISION_KIND_LEXICON:
        checkpoint = (
            '{"required_true": ["(...)"], "required_false": [], '
            '"constraints_addressed": [1]}'
        )
    else:
        fields = list(hanoi_checkpoint_fields)
        if not fields:
            raise ValueError(
                "Strict Hanoi Decision schema requires valid concrete peg fields"
            )
        rings = ", ".join(hanoi_ring_names) or "the public ring names"
        checkpoint = _canonical_json({field: [] for field in fields})
        checkpoint += (
            " (replace the arrays with the complete bottom-to-top stack state; "
            f"use every ring exactly once from: {rings})"
        )
    return (
        "COMPACT OUTPUT CONTRACT (authoritative): Return only the JSON object "
        "required by the response schema. Do not emit markdown, tags, calls, or "
        "commentary. Use consecutive subtask ids beginning at 1. Each subtask is "
        '{"id": 1, "description": "natural-language checkpoint", '
        f'"checkpoint": {checkpoint}}}. The runtime deterministically serializes '
        "this JSON into the legacy tagged representation."
    )


def hierarchy_contract_prompt(
    vocabulary: CompactHierarchyVocabulary, expected_subtask_ids: Sequence[int]
) -> str:
    """Short authoritative output-format addendum for HierarchyPlanner."""

    bases = ", ".join(
        f"{name}/{signature.arity}"
        for name, signature in sorted(vocabulary.base_functions.items())
    )
    primitives = ", ".join(sorted(vocabulary.primitive_arities))
    return (
        "COMPACT OUTPUT CONTRACT (authoritative): Return only the JSON object "
        "required by the response schema; no markdown, tags, code, or commentary. "
        'Each mapping is {"name": "H2Name", "params": ["parameter"], '
        '"calls": [{"name": "KnownLowerFunction", "args": ["parameter"]}]}. '
        'Each concrete subtask is {"id": 1, "calls": [{"name": "KnownFunction", '
        '"args": ["concrete_object"]}]}. '
        f"Known H1 functions (name/arity): {bases}. H0 action names are forbidden "
        f"above H1: {primitives or 'none'}. Required subtask ids: "
        f"{list(expected_subtask_ids)}."
    )


def configure_compact_stage_request(
    request: Any,
    *,
    enabled: bool = COMPACT_GENERATION_CONTRACTS_DEFAULT,
    decision_kind: Optional[str] = None,
    hierarchy_vocabulary: Optional[CompactHierarchyVocabulary] = None,
    expected_subtask_ids: Sequence[int] = (),
    hanoi_checkpoint_fields: Sequence[str] = (),
    hanoi_ring_names: Sequence[str] = (),
) -> Any:
    """Opt a frozen ``StageRequest`` into a compact response contract.

    With the default flag this returns the *same object*, which is useful both
    as a compatibility guarantee and as a regression assertion.  The function
    intentionally accepts ``Any`` to avoid coupling this standalone codec to a
    particular pipeline revision; the value must be a dataclass with the
    standard StageRequest fields when enabled.
    """

    if not enabled:
        return request
    stage = getattr(request, "stage", None)
    if stage == "decision":
        if decision_kind is None:
            raise ValueError("decision_kind is required for a compact Decision request")
        return replace(
            request,
            prompt=str(request.prompt)
            + "\n\n"
            + decision_contract_prompt(
                decision_kind,
                hanoi_checkpoint_fields=hanoi_checkpoint_fields,
                hanoi_ring_names=hanoi_ring_names,
            ),
            response_schema=decision_response_schema(
                decision_kind,
                hanoi_checkpoint_fields=hanoi_checkpoint_fields,
                hanoi_ring_names=hanoi_ring_names,
            ),
            schema_name=DECISION_SCHEMA_NAME,
        )
    if stage == "hierarchy_planner":
        if hierarchy_vocabulary is None:
            raise ValueError(
                "hierarchy_vocabulary is required for a compact Hierarchy request"
            )
        return replace(
            request,
            prompt=str(request.prompt)
            + "\n\n"
            + hierarchy_contract_prompt(hierarchy_vocabulary, expected_subtask_ids),
            response_schema=hierarchy_response_schema(),
            schema_name=HIERARCHY_SCHEMA_NAME,
        )
    raise ValueError(f"Compact contracts do not support stage {stage!r}")


def decision_subtask_ids(decision: object) -> Tuple[int, ...]:
    """Extract ordered ids from either existing DynaPlan Decision artifact."""

    values = getattr(decision, "subtasks", decision)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise TypeError("Decision artifact does not expose a subtask sequence")
    result: List[int] = []
    for position, item in enumerate(values, start=1):
        if isinstance(item, Mapping):
            index = item.get("subtask_index", item.get("id"))
        else:
            index = getattr(item, "index", None)
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError(f"Decision subtask {position} has no integer id")
        result.append(index)
    return tuple(result)


__all__ = [
    "COMPACT_CONTRACT_REVISION",
    "COMPACT_GENERATION_CONTRACTS_DEFAULT",
    "DECISION_KIND_HANOI",
    "DECISION_KIND_LEXICON",
    "DECISION_SCHEMA_NAME",
    "HIERARCHY_SCHEMA_NAME",
    "CompactDecodeResult",
    "CompactHierarchyVocabulary",
    "FunctionSignature",
    "configure_compact_stage_request",
    "decision_contract_prompt",
    "decision_response_schema",
    "decision_subtask_ids",
    "decode_compact_decision",
    "decode_compact_hierarchy",
    "hierarchy_contract_prompt",
    "hierarchy_response_schema",
]
