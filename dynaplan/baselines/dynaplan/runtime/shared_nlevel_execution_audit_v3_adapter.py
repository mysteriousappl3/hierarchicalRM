"""Coverage-guarded, single-InnerBot execution audit.

This is a deliberately small successor to the transactional v2 execution
audit.  It keeps the same hierarchy compiler, unchecked public-effect shadow,
transaction boundary, OuterBot, and exact-once final evaluator.  The only
semantic-planning change is the InnerBot contract: one call must perform both
a forward trace simulation and a backward requirement-support check.

The Python guard checks certificate shape and coverage only.  It does not
interpret domain semantics, so this remains an LLM-only verifier ablation.
"""

from __future__ import annotations

import json
from typing import Dict, List, Mapping, Optional, Sequence

import shared_nlevel_blocksworld as blocksworld
import shared_nlevel_lexicon as lexicon
from shared_nlevel_execution_audit_adapter import (
    ExecutionAuditLLMOnlyBlocksworldAdapter,
    ExecutionAuditLLMOnlyLexiconAdapter,
    _execution_boundary_payload,
)
from shared_nlevel_execution_audit_flat_hanoi import (
    ExecutionAuditLLMOnlyFlatHanoiAdapter,
)
from shared_nlevel_pipeline import RouterVerdict, StageRequest
from shared_nlevel_proof_audit_flat_hanoi import (
    _flat_final_requirements,
    _flat_public_problem_text,
)


PIPELINE_VERSION = (
    "shared_nlevel_v5_llm_only_execution_audit_single_innerbot_dual_pass"
)
SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION = (
    "shared_nlevel_v5_llm_only_execution_audit_v3_single_innerbot_dual_pass"
)
SYSTEM_SINGLE_INNERBOT_AUDIT_ROUTER = (
    "InnerBot router, single-call dual-pass execution auditor: independently perform "
    "a forward state simulation and backward requirement-support check using "
    "only the supplied public rules."
)


_COVERAGE_FIELDS = (
    "expected_actions",
    "checked_actions",
    "expected_checkpoints",
    "checked_checkpoints",
    "expected_final_requirements",
    "checked_final_requirements",
    "forward_check_complete",
    "backward_check_complete",
)


SINGLE_INNERBOT_AUDIT_SCHEMA: Dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict",
        "first_bad_subtask",
        "first_bad_action_in_subtask",
        "owner",
        "coverage",
        "final_state_facts",
        "outstanding_requirements",
        "reason",
    ],
    "properties": {
        "verdict": {"type": "string", "enum": ["VALID", "INVALID"]},
        "first_bad_subtask": {"type": "integer", "minimum": 0},
        "first_bad_action_in_subtask": {"type": "integer", "minimum": 0},
        "owner": {
            "type": "string",
            "enum": ["NA", "DecisionBot", "HierarchyPlanner", "both"],
        },
        "coverage": {
            "type": "object",
            "additionalProperties": False,
            "required": list(_COVERAGE_FIELDS),
            "properties": {
                "expected_actions": {"type": "integer", "minimum": 0},
                "checked_actions": {"type": "integer", "minimum": 0},
                "expected_checkpoints": {"type": "integer", "minimum": 0},
                "checked_checkpoints": {"type": "integer", "minimum": 0},
                "expected_final_requirements": {
                    "type": "integer",
                    "minimum": 0,
                },
                "checked_final_requirements": {
                    "type": "integer",
                    "minimum": 0,
                },
                "forward_check_complete": {"type": "boolean"},
                "backward_check_complete": {"type": "boolean"},
            },
        },
        "final_state_facts": {
            "type": "array",
            "items": {"type": "string"},
        },
        "outstanding_requirements": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reason": {"type": "string"},
    },
}


class _CoverageGuardError(ValueError):
    """A syntactically valid audit failed a deterministic coverage guard."""


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _final_requirements(task: object) -> List[Dict[str, str]]:
    requirements: List[Dict[str, str]] = []
    for index, goal in enumerate(getattr(task, "goals", ()), start=1):
        requirements.append(
            {
                "requirement_id": f"goal_{index}",
                "requirement_kind": "goal",
                "requirement": str(goal),
            }
        )
    for index, constraint in enumerate(
        getattr(task, "constraints", ()), start=1
    ):
        requirements.append(
            {
                "requirement_id": f"constraint_{index}",
                "requirement_kind": "temporal_constraint",
                "requirement": str(constraint),
            }
        )
    return requirements


def _strict_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _string_array(value: object, label: str) -> List[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise ValueError(f"{label} must be an array of strings")
    return [str(item) for item in value]


def single_innerbot_audit_prompt(
    *,
    problem_text: str,
    descriptor_output: str,
    decision_output: str,
    hierarchy_output: str,
    execution_boundary_actions: Sequence[Mapping[str, object]],
    final_requirements: Sequence[Mapping[str, str]],
    feedback: Optional[str],
) -> str:
    """Build the compact two-pass audit request for one InnerBot call."""

    manifest = {
        "expected_actions": sum(
            len(item.get("expanded_execution_actions", ()))
            for item in execution_boundary_actions
        ),
        "expected_checkpoints": len(execution_boundary_actions),
        "expected_final_requirements": len(final_requirements),
    }
    withheld = {
        "semantic_verification": "WITHHELD",
        "structural_compilation_succeeded": True,
        "official_evaluator_available_during_planning": False,
    }
    return f"""You are the only InnerBot execution-boundary auditor for this
candidate. Complete two distinct checks inside this one call. Do not repair or
optimize the plan, and do not treat the hierarchy text, prior feedback, or a
plausible final state as evidence that the primitive sequence is legal.

PASS A -- FORWARD STATE SIMULATION
1. Initialize a compact typed ledger from the visible candidate-start state.
2. Visit every canonical H0 action in exact global order. Check its operator,
   arguments, and every public precondition against the current ledger.
3. Only after an action is applicable, apply all of its public effects and
   update any temporal obligation. Detect duplicate loads/unloads, absent
   containment, wrong locations, non-clear blocks, hand-state errors, empty
   Hanoi sources, and illegal ring placement whenever the public rules imply
   those checks.
4. At each subtask boundary, check the complete DecisionBot checkpoint.
5. Record how many actions and checkpoints were actually checked. If a check
   fails, stop at the earliest failure and return INVALID.

PASS B -- BACKWARD SUPPORT / ADVERSARIAL CHECK
Begin only after Pass A reaches the end. Start independently from every listed
final goal and temporal constraint. Trace each obligation backward to the
candidate-start state or to an action that establishes it, and make sure no
later action clobbers it. For temporal constraints, verify the required event
order over the whole trace. Actively search for a counterexample to Pass A's
apparent conclusion. Record how many final requirements were checked.

ACCEPTANCE RULE
Return VALID only if every expected action, checkpoint, and final requirement
was checked; both passes completed; the compact final ledger supports every
goal; and `outstanding_requirements` is empty. If context or confidence is
insufficient to finish either pass, return INVALID rather than guessing.

The controller deterministically compares every `expected_*` and `checked_*`
field with the manifest below. Invented counts, partial coverage, a nonempty
outstanding list, or an incomplete pass cannot be accepted as VALID.

PUBLIC TASK AND ACTION RULES:
{problem_text}

VISIBLE CANDIDATE-START STATE:
{descriptor_output}

DECISIONBOT CHECKPOINTS:
{decision_output}

UNTRUSTED COMPOSED HIERARCHY (use for error ownership only):
{hierarchy_output}

CANONICAL EXECUTION-BOUNDARY ACTIONS BY SUBTASK:
{_json(execution_boundary_actions)}

FINAL REQUIREMENTS TO CHECK:
{_json(final_requirements)}

AUDIT COVERAGE MANIFEST:
{_json(manifest)}

SEMANTIC-VERIFICATION RECORD:
{_json(withheld)}

UNTRUSTED REPAIR FEEDBACK:
{feedback or 'N/A'}

Keep `final_state_facts` compact but sufficient to decide all final
requirements. For VALID, use zero failure indices and owner NA. For INVALID,
give the earliest one-based subtask and one-based action within it; use action
0 for a checkpoint or final-requirement failure. Assign DecisionBot for a bad
checkpoint/decomposition, HierarchyPlanner for bad calls/actions, or both when
both must change. Return only the response-schema object.
"""


class _SingleInnerBotDualPassMixin:
    """Prompt, structural guard, and telemetry shared by all three domains."""

    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = (
        SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION
    )

    def _init_single_innerbot_audit(self) -> None:
        self.single_innerbot_audit_records: List[Dict[str, object]] = []
        # Retain the established metric/property name for controller tooling.
        self.execution_audit_records = self.single_innerbot_audit_records
        self._pending_audit_manifest: Dict[str, int] = {}
        self._pending_subtask_action_counts: Dict[int, int] = {}

    def _problem_text(self, task: object) -> str:
        raise NotImplementedError

    def _requirements(self, task: object) -> List[Dict[str, str]]:
        return _final_requirements(task)

    def _descriptor_text(
        self, state_output: str, scene: object
    ) -> str:
        del scene
        return state_output

    def router_request(
        self,
        task: object,
        state: object,
        scene: object,
        state_output: str,
        decision_output: str,
        hierarchy_output: str,
        projection: object,
        execution_feedback: Optional[str] = None,
    ) -> StageRequest:
        del state
        boundary = _execution_boundary_payload(self, projection)
        requirements = self._requirements(task)
        self._pending_audit_manifest = {
            "expected_actions": sum(
                len(item.get("expanded_execution_actions", ()))
                for item in boundary
            ),
            "expected_checkpoints": len(boundary),
            "expected_final_requirements": len(requirements),
        }
        self._pending_subtask_action_counts = {
            int(item["subtask_index"]): len(
                item.get("expanded_execution_actions", ())
            )
            for item in boundary
        }
        return StageRequest(
            stage="innerbot_router",
            system=SYSTEM_SINGLE_INNERBOT_AUDIT_ROUTER,
            prompt=single_innerbot_audit_prompt(
                problem_text=self._problem_text(task),
                descriptor_output=self._descriptor_text(state_output, scene),
                decision_output=decision_output,
                hierarchy_output=hierarchy_output,
                execution_boundary_actions=boundary,
                final_requirements=requirements,
                feedback=execution_feedback,
            ),
            response_schema=SINGLE_INNERBOT_AUDIT_SCHEMA,
            schema_name="n_hierarchy_single_innerbot_dual_pass_audit_v1",
        )

    def _validate_coverage(
        self, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        coverage = payload.get("coverage")
        if not isinstance(coverage, dict) or set(coverage) != set(
            _COVERAGE_FIELDS
        ):
            raise ValueError("coverage has incorrect fields")
        if not self._pending_audit_manifest:
            raise ValueError("no pending audit manifest")

        numeric_fields = _COVERAGE_FIELDS[:6]
        observed = {
            field: _strict_integer(coverage[field], f"coverage.{field}")
            for field in numeric_fields
        }
        for label, expected in self._pending_audit_manifest.items():
            if observed[label] != expected:
                raise _CoverageGuardError(
                    f"coverage.{label} does not match manifest "
                    f"({observed[label]} != {expected})"
                )
        for checked, expected in (
            ("checked_actions", "expected_actions"),
            ("checked_checkpoints", "expected_checkpoints"),
            ("checked_final_requirements", "expected_final_requirements"),
        ):
            if observed[checked] > observed[expected]:
                raise _CoverageGuardError(
                    f"coverage.{checked} exceeds coverage.{expected}"
                )
        for field in _COVERAGE_FIELDS[6:]:
            if not isinstance(coverage[field], bool):
                raise ValueError(f"coverage.{field} must be boolean")
        return coverage

    def parse_router(self, output: str) -> RouterVerdict:
        parsed_payload: Optional[Mapping[str, object]] = None
        try:
            payload = json.loads(output)
            if not isinstance(payload, dict) or set(payload) != set(
                SINGLE_INNERBOT_AUDIT_SCHEMA["required"]
            ):
                raise ValueError("single-InnerBot audit has incorrect fields")
            parsed_payload = payload
            coverage = self._validate_coverage(payload)
            final_state_facts = _string_array(
                payload["final_state_facts"], "final_state_facts"
            )
            outstanding = _string_array(
                payload["outstanding_requirements"],
                "outstanding_requirements",
            )
            verdict = str(payload["verdict"])
            subtask = _strict_integer(
                payload["first_bad_subtask"], "first_bad_subtask"
            )
            action = _strict_integer(
                payload["first_bad_action_in_subtask"],
                "first_bad_action_in_subtask",
            )
            owner_text = str(payload["owner"])
            reason = str(payload["reason"]).strip() or "N/A"
            if owner_text not in {
                "NA",
                "DecisionBot",
                "HierarchyPlanner",
                "both",
            }:
                raise ValueError("audit owner is invalid")

            if verdict == "VALID":
                if subtask != 0 or action != 0 or owner_text != "NA":
                    raise ValueError("VALID requires zero indices and owner NA")
                for checked, expected in (
                    ("checked_actions", "expected_actions"),
                    ("checked_checkpoints", "expected_checkpoints"),
                    (
                        "checked_final_requirements",
                        "expected_final_requirements",
                    ),
                ):
                    if coverage[checked] != coverage[expected]:
                        raise _CoverageGuardError(
                            f"VALID requires complete {checked} coverage"
                        )
                if coverage["forward_check_complete"] is not True:
                    raise _CoverageGuardError(
                        "VALID requires a complete forward check"
                    )
                if coverage["backward_check_complete"] is not True:
                    raise _CoverageGuardError(
                        "VALID requires a complete backward check"
                    )
                if outstanding:
                    raise _CoverageGuardError(
                        "VALID requires no outstanding requirements"
                    )
                if (
                    self._pending_audit_manifest[
                        "expected_final_requirements"
                    ]
                    and not final_state_facts
                ):
                    raise _CoverageGuardError(
                        "VALID requires task-relevant final-state evidence"
                    )
                self.single_innerbot_audit_records.append(
                    {
                        **payload,
                        "raw_verdict": "VALID",
                        "effective_verdict": "VALID",
                        "parse_valid": True,
                        "coverage_guard_passed": True,
                    }
                )
                return RouterVerdict(True, "both", reason)

            if verdict != "INVALID":
                raise ValueError(f"unknown verdict {verdict!r}")
            if subtask not in self._pending_subtask_action_counts:
                raise ValueError("INVALID must name an existing subtask")
            if action > self._pending_subtask_action_counts[subtask]:
                raise ValueError("INVALID action index is outside its subtask")
            if owner_text == "NA":
                raise ValueError("INVALID requires a non-NA owner")
            normalized_owner = {
                "DecisionBot": "decision",
                "HierarchyPlanner": "hierarchy",
                "both": "both",
            }[owner_text]
            localized = (
                f"Subtask {subtask}, action {action}: {reason}"
                if action
                else f"Subtask {subtask}, boundary/final requirement: {reason}"
            )
            self.single_innerbot_audit_records.append(
                {
                    **payload,
                    "raw_verdict": "INVALID",
                    "effective_verdict": "INVALID",
                    "parse_valid": True,
                    "coverage_guard_passed": True,
                }
            )
            return RouterVerdict(False, normalized_owner, localized)
        except _CoverageGuardError as error:
            record: Dict[str, object] = dict(parsed_payload or {})
            record.update(
                {
                    "raw_verdict": record.get("verdict", "UNKNOWN"),
                    "effective_verdict": "INVALID",
                    "parse_valid": True,
                    "coverage_guard_passed": False,
                    "guard_reason": str(error),
                }
            )
            self.single_innerbot_audit_records.append(record)
            return RouterVerdict(
                False,
                "both",
                f"Single-InnerBot coverage guard rejected audit: {error}",
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            self.single_innerbot_audit_records.append(
                {
                    "raw_verdict": (
                        parsed_payload.get("verdict", "UNKNOWN")
                        if parsed_payload is not None
                        else "UNKNOWN"
                    ),
                    "effective_verdict": "INVALID",
                    "parse_valid": False,
                    "coverage_guard_passed": False,
                    "reason": f"Malformed single-InnerBot audit: {error}",
                }
            )
            return RouterVerdict(
                False,
                "both",
                f"Malformed single-InnerBot audit: {error}",
            )


class SingleInnerBotDualPassLexiconAdapter(
    _SingleInnerBotDualPassMixin, ExecutionAuditLLMOnlyLexiconAdapter
):
    """Logistics transactional audit with one internally dual-pass critic."""

    verifier_mode = (
        "llm-only-single-innerbot-dual-pass-online; official-pddl-final-only"
    )
    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = (
        SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION
    )

    def __init__(self) -> None:
        super().__init__()
        self._init_single_innerbot_audit()

    def _problem_text(self, task: object) -> str:
        return lexicon._model_task_text(task)


class SingleInnerBotDualPassBlocksworldAdapter(
    _SingleInnerBotDualPassMixin, ExecutionAuditLLMOnlyBlocksworldAdapter
):
    """Blocksworld transactional audit with one dual-pass InnerBot call."""

    verifier_mode = (
        "llm-only-single-innerbot-dual-pass-online; official-pddl-final-only"
    )
    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = (
        SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION
    )

    def __init__(self) -> None:
        super().__init__()
        self._init_single_innerbot_audit()

    def _problem_text(self, task: object) -> str:
        return blocksworld._model_task_text(task)


class SingleInnerBotDualPassFlatHanoiAdapter(
    _SingleInnerBotDualPassMixin, ExecutionAuditLLMOnlyFlatHanoiAdapter
):
    """Flat-Hanoi transactional audit with one dual-pass InnerBot call."""

    verifier_mode = (
        "llm-only-single-innerbot-dual-pass-online; official-hanoi-final-only"
    )
    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = (
        SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION
    )

    def __init__(self) -> None:
        super().__init__()
        self._init_single_innerbot_audit()

    def _problem_text(self, task: object) -> str:
        return _flat_public_problem_text(task)

    def _requirements(self, task: object) -> List[Dict[str, str]]:
        return _flat_final_requirements(task)

    def _descriptor_text(
        self, state_output: str, scene: object
    ) -> str:
        return (
            f"{state_output}\n\nVISIBLE CURRENT SCENE (unchecked observation):\n"
            + json.dumps(scene, indent=2, sort_keys=True)
        )


__all__ = [
    "PIPELINE_VERSION",
    "SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION",
    "SINGLE_INNERBOT_AUDIT_SCHEMA",
    "SYSTEM_SINGLE_INNERBOT_AUDIT_ROUTER",
    "SingleInnerBotDualPassBlocksworldAdapter",
    "SingleInnerBotDualPassFlatHanoiAdapter",
    "SingleInnerBotDualPassLexiconAdapter",
    "single_innerbot_audit_prompt",
]
