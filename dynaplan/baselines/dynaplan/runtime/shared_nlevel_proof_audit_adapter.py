"""Proof-carrying InnerBot adapters for the v5 LLM-only ablation.

This variant exposes the same public rules, composed hierarchy, and canonical
H0 expansion as :mod:`shared_nlevel_execution_audit_adapter`, but requires the
first InnerBot call to return an explicit provenance certificate.  A second,
independent InnerBot call then tries to falsify that certificate.

The Python-side checks in this module are deliberately structural only: they
ensure that a certificate covers every compiled action/subtask/requirement and
that references point backward.  They never evaluate an action precondition,
apply a semantic transition, or decide whether a goal/constraint holds.  The
released compiled-PDDL evaluator therefore remains unavailable during planning
and is invoked exactly once at final scoring.
"""

from __future__ import annotations

import json
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import shared_nlevel_blocksworld as blocksworld
import shared_nlevel_lexicon as lexicon
from shared_nlevel_execution_audit_adapter import (
    ExecutionAuditLLMOnlyBlocksworldAdapter,
    ExecutionAuditLLMOnlyLexiconAdapter,
    _execution_boundary_payload,
)
from shared_nlevel_pipeline import RouterVerdict, StageRequest


PIPELINE_VERSION = "shared_nlevel_v5_llm_only_proof_audit_v2"
SYSTEM_PROOF_AUDIT_ROUTER = (
    "InnerBot proof-audit router: construct a provenance certificate for the "
    "composed hierarchy and canonical primitive expansion using only the "
    "supplied public rules."
)
SYSTEM_PROOF_CHALLENGE_ROUTER = (
    "InnerBot counterexample-challenge router: independently try to falsify "
    "a proposed execution certificate using only the supplied public rules."
)


_WITNESS_SCHEMA: Dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "fact",
        "source_kind",
        "source_action_global_index",
        "source_still_holds",
    ],
    "properties": {
        "fact": {"type": "string"},
        "source_kind": {
            "type": "string",
            "enum": ["candidate_start_state", "prior_action"],
        },
        "source_action_global_index": {"type": "integer", "minimum": 0},
        "source_still_holds": {"type": "boolean"},
    },
}


PROOF_AUDIT_SCHEMA: Dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict",
        "first_bad_subtask",
        "first_bad_action_in_subtask",
        "owner",
        "action_support",
        "checkpoint_support",
        "final_requirement_support",
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
        "action_support": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "global_action_index",
                    "subtask_index",
                    "action_index_in_subtask",
                    "action",
                    "precondition_witnesses",
                    "applicable",
                    "effects_applied",
                ],
                "properties": {
                    "global_action_index": {"type": "integer", "minimum": 1},
                    "subtask_index": {"type": "integer", "minimum": 1},
                    "action_index_in_subtask": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "action": {"type": "string"},
                    "precondition_witnesses": {
                        "type": "array",
                        "items": _WITNESS_SCHEMA,
                    },
                    "applicable": {"type": "boolean"},
                    "effects_applied": {"type": "boolean"},
                },
            },
        },
        "checkpoint_support": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "subtask_index",
                    "checkpoint_summary",
                    "satisfied",
                    "establishing_action_global_indices",
                    "no_later_clobber_at_boundary",
                ],
                "properties": {
                    "subtask_index": {"type": "integer", "minimum": 1},
                    "checkpoint_summary": {"type": "string"},
                    "satisfied": {"type": "boolean"},
                    "establishing_action_global_indices": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0},
                    },
                    "no_later_clobber_at_boundary": {"type": "boolean"},
                },
            },
        },
        "final_requirement_support": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "requirement_id",
                    "requirement_kind",
                    "requirement",
                    "satisfied",
                    "establishing_action_global_indices",
                    "no_later_clobber",
                ],
                "properties": {
                    "requirement_id": {"type": "string"},
                    "requirement_kind": {
                        "type": "string",
                        "enum": ["goal", "temporal_constraint"],
                    },
                    "requirement": {"type": "string"},
                    "satisfied": {"type": "boolean"},
                    "establishing_action_global_indices": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0},
                    },
                    "no_later_clobber": {"type": "boolean"},
                },
            },
        },
        "reason": {"type": "string"},
    },
}


PROOF_CHALLENGE_SCHEMA: Dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "counterexample_found",
        "earliest_bad_subtask",
        "earliest_bad_action_in_subtask",
        "owner",
        "category",
        "challenged_claim",
        "reason",
    ],
    "properties": {
        "counterexample_found": {"type": "boolean"},
        "earliest_bad_subtask": {"type": "integer", "minimum": 0},
        "earliest_bad_action_in_subtask": {"type": "integer", "minimum": 0},
        "owner": {
            "type": "string",
            "enum": ["NA", "DecisionBot", "HierarchyPlanner", "both"],
        },
        "category": {
            "type": "string",
            "enum": [
                "NONE",
                "UNSUPPORTED_PRECONDITION",
                "INVALID_STATE_UPDATE",
                "CHECKPOINT_FAILURE",
                "CLOBBERED_GOAL",
                "UNMET_GOAL",
                "UNMET_CONSTRAINT",
                "OTHER",
            ],
        },
        "challenged_claim": {"type": "string"},
        "reason": {"type": "string"},
    },
}


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


def proof_audit_router_prompt(
    *,
    problem_text: str,
    descriptor_output: str,
    decision_output: str,
    hierarchy_output: str,
    execution_boundary_actions: Sequence[Mapping[str, object]],
    final_requirements: Sequence[Mapping[str, str]],
    feedback: Optional[str],
) -> str:
    """Build the proof-producing audit request without verifier evidence."""

    total_actions = sum(
        len(item.get("expanded_execution_actions", ()))
        for item in execution_boundary_actions
    )
    withheld = {
        "semantic_verification": "WITHHELD",
        "structural_compilation_succeeded": True,
        "compiled_subtask_count": len(execution_boundary_actions),
        "candidate_execution_action_count": total_actions,
        "official_evaluator_available_during_planning": False,
    }
    return f"""You are the InnerBot proof-audit router.

DecisionBot supplied semantic checkpoints but no actions. HierarchyPlanner
supplied composed mappings and calls. A deterministic structural compiler
expanded those calls into the canonical H0 sequence below. Structural
expansion proves only that the call graph is representable; it does not prove
action applicability, state transitions, checkpoints, goals, or constraints.

Using only the public rules, reconstruct the complete state trace mentally.
Produce a proof certificate with these obligations:

1. Include exactly one `action_support` item for every H0 action, in global
   execution order. For every explicit precondition, cite either the current
   candidate-start state (source index 0) or the exact earlier global action
   that established it in `precondition_witnesses`. Confirm that no
   intervening delete effect clobbered that fact.
2. Apply every explicit add/delete effect before considering the next action.
3. Include exactly one `checkpoint_support` item per DecisionBot subtask and
   check its entire checkpoint at that boundary.
4. Include exactly one `final_requirement_support` item for every listed final
   obligation. Cite the establishing action(s), or index 0 for initial-state
   support, and check for later clobbering. Temporal constraints must be checked
   against the complete trace, not merely the final state.
5. Return VALID only if every action, checkpoint, goal, and temporal constraint
   is supported. Otherwise localize the earliest failure. Do not repair or
   optimize the plan.

PUBLIC TASK AND ACTION RULES:
{problem_text}

CURRENT STATE DESCRIPTOR:
{descriptor_output}

DECISIONBOT CHECKPOINTS:
{decision_output}

COMPOSED HIERARCHY:
{hierarchy_output}

CANONICAL EXECUTION-BOUNDARY ACTIONS BY SUBTASK:
{_json(execution_boundary_actions)}

FINAL AUDIT OBLIGATIONS:
{_json(final_requirements)}

SEMANTIC-VERIFICATION RECORD:
{_json(withheld)}

ADDITIONAL FEEDBACK:
{feedback or 'N/A'}

For VALID, both failure indices must be 0 and owner must be NA. For INVALID,
use a one-based subtask index, a one-based action-within-subtask index (or 0 for
a checkpoint/final-requirement failure), and assign ownership to DecisionBot,
HierarchyPlanner, or both. Return only the object required by the schema.
"""


def proof_challenge_router_prompt(
    *,
    problem_text: str,
    descriptor_output: str,
    decision_output: str,
    hierarchy_output: str,
    execution_boundary_actions: Sequence[Mapping[str, object]],
    final_requirements: Sequence[Mapping[str, str]],
    proof_output: str,
    feedback: Optional[str],
) -> str:
    """Build the independent falsification request for an accepted proof."""

    return f"""You are an independent InnerBot counterexample challenger.

The first auditor returned VALID. Treat its certificate as an untrusted claim,
not as evidence. Independently reconstruct the state trace from the public
rules and search aggressively for the earliest counterexample in this order:

1. an action with an unsupported or clobbered precondition;
2. an incorrectly applied add/delete effect;
3. a failed DecisionBot checkpoint at its boundary;
4. a final goal that is absent or later clobbered; or
5. a temporal constraint not witnessed by the complete trace.

Do not reject a valid plan merely because it is long or non-optimal. Report no
counterexample only after checking every H0 action and every final obligation.
No deterministic semantic result or official score is available to you.

PUBLIC TASK AND ACTION RULES:
{problem_text}

CURRENT STATE DESCRIPTOR:
{descriptor_output}

DECISIONBOT CHECKPOINTS:
{decision_output}

COMPOSED HIERARCHY:
{hierarchy_output}

CANONICAL EXECUTION-BOUNDARY ACTIONS BY SUBTASK:
{_json(execution_boundary_actions)}

FINAL AUDIT OBLIGATIONS:
{_json(final_requirements)}

UNTRUSTED FIRST-AUDITOR CERTIFICATE:
{proof_output}

SEMANTIC-VERIFICATION RECORD:
{_json({'semantic_verification': 'WITHHELD', 'official_evaluator_available_during_planning': False})}

ADDITIONAL FEEDBACK:
{feedback or 'N/A'}

If no counterexample exists, return false, zero indices, owner NA, category
NONE, and challenged_claim `N/A`. If one exists, return true, the earliest
one-based subtask/action indices (action 0 for a boundary/final failure), a
non-NA owner, and a non-NONE category. Return only the schema object.
"""


def _normalize_owner(owner_text: str) -> str:
    return {
        "DecisionBot": "decision",
        "HierarchyPlanner": "hierarchy",
        "both": "both",
    }.get(owner_text, "both")


def _strict_integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _exact_fields(
    value: object, expected: Sequence[str], label: str
) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{label} has incorrect fields")
    return value


class _ProofAuditMixin:
    """Shared proof/challenge behavior for Logistics and Blocksworld."""

    verifier_mode = "llm-only-proof-plus-challenge-online; official-pddl-final-only"
    architecture_mode = PIPELINE_VERSION

    def _init_proof_audit(self) -> None:
        self.proof_audit_records: List[Dict[str, object]] = []
        self.proof_challenge_records: List[Dict[str, object]] = []
        self._pending_proof_boundary: List[Dict[str, object]] = []
        self._pending_final_requirements: List[Dict[str, str]] = []
        self._pending_challenge_context: Dict[str, object] = {}
        self._pending_challenge_output: Optional[str] = None

    def _problem_text(self, task: object) -> str:
        raise NotImplementedError

    def reasoning_effort_for(
        self, stage: str, base_effort: Optional[str]
    ) -> Optional[str]:
        if base_effort is None:
            return None
        if stage in {"innerbot_router", "innerbot_challenge"}:
            return base_effort
        return super().reasoning_effort_for(stage, base_effort)

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
        del state, scene
        boundary = _execution_boundary_payload(self, projection)
        requirements = _final_requirements(task)
        self._pending_proof_boundary = boundary
        self._pending_final_requirements = requirements
        self._pending_challenge_context = {
            "problem_text": self._problem_text(task),
            "descriptor_output": state_output,
            "decision_output": decision_output,
            "hierarchy_output": hierarchy_output,
            "execution_boundary_actions": boundary,
            "final_requirements": requirements,
            "feedback": execution_feedback,
        }
        self._pending_challenge_output = None
        return StageRequest(
            stage="innerbot_router",
            system=SYSTEM_PROOF_AUDIT_ROUTER,
            prompt=proof_audit_router_prompt(
                problem_text=self._problem_text(task),
                descriptor_output=state_output,
                decision_output=decision_output,
                hierarchy_output=hierarchy_output,
                execution_boundary_actions=boundary,
                final_requirements=requirements,
                feedback=execution_feedback,
            ),
            response_schema=PROOF_AUDIT_SCHEMA,
            schema_name="n_hierarchy_proof_audit_v1",
        )

    def _expected_actions(self) -> List[Tuple[int, int, int, str]]:
        expected: List[Tuple[int, int, int, str]] = []
        global_index = 0
        for subtask in self._pending_proof_boundary:
            subtask_index = int(subtask["subtask_index"])
            for local_index, action in enumerate(
                subtask.get("expanded_execution_actions", ()), start=1
            ):
                global_index += 1
                expected.append(
                    (global_index, subtask_index, local_index, str(action))
                )
        return expected

    def _validate_proof_coverage(self, payload: Mapping[str, object]) -> None:
        action_support = payload.get("action_support")
        if not isinstance(action_support, list):
            raise ValueError("action_support must be an array")
        expected_actions = self._expected_actions()
        if len(action_support) != len(expected_actions):
            raise ValueError(
                "action_support does not cover every compiled H0 action "
                f"({len(action_support)} != {len(expected_actions)})"
            )
        for item, expected in zip(action_support, expected_actions):
            item = _exact_fields(
                item,
                (
                    "global_action_index",
                    "subtask_index",
                    "action_index_in_subtask",
                    "action",
                    "precondition_witnesses",
                    "applicable",
                    "effects_applied",
                ),
                "action_support entry",
            )
            observed = (
                _strict_integer(
                    item["global_action_index"],
                    "global_action_index",
                    minimum=1,
                ),
                _strict_integer(
                    item["subtask_index"], "subtask_index", minimum=1
                ),
                _strict_integer(
                    item["action_index_in_subtask"],
                    "action_index_in_subtask",
                    minimum=1,
                ),
                str(item["action"]),
            )
            if observed != expected:
                raise ValueError(
                    f"action_support coverage mismatch: {observed!r} != {expected!r}"
                )
            witnesses = item.get("precondition_witnesses")
            if not isinstance(witnesses, list):
                raise ValueError("precondition_witnesses must be an array")
            for witness in witnesses:
                witness = _exact_fields(
                    witness,
                    (
                        "fact",
                        "source_kind",
                        "source_action_global_index",
                        "source_still_holds",
                    ),
                    "precondition witness",
                )
                if not isinstance(witness["fact"], str) or not witness["fact"].strip():
                    raise ValueError("precondition witness fact must be non-empty")
                source_kind = str(witness["source_kind"])
                if source_kind not in {"candidate_start_state", "prior_action"}:
                    raise ValueError("precondition witness has unknown source_kind")
                source_index = _strict_integer(
                    witness["source_action_global_index"],
                    "source_action_global_index",
                )
                if source_kind == "candidate_start_state" and source_index != 0:
                    raise ValueError(
                        "candidate-start-state witness must use source index 0"
                    )
                if source_kind == "prior_action" and not (
                    1 <= source_index < expected[0]
                ):
                    raise ValueError(
                        "prior-action witness must point to an earlier global action"
                    )
                if not isinstance(witness["source_still_holds"], bool):
                    raise ValueError("source_still_holds must be boolean")
            if not isinstance(item["applicable"], bool):
                raise ValueError("applicable must be boolean")
            if not isinstance(item["effects_applied"], bool):
                raise ValueError("effects_applied must be boolean")

        checkpoint_support = payload.get("checkpoint_support")
        if not isinstance(checkpoint_support, list):
            raise ValueError("checkpoint_support must be an array")
        expected_subtasks = [
            int(item["subtask_index"]) for item in self._pending_proof_boundary
        ]
        observed_subtasks: List[int] = []
        action_boundary_by_subtask: Dict[int, int] = {}
        for global_index, subtask_index, _, _ in expected_actions:
            action_boundary_by_subtask[subtask_index] = global_index
        previous_boundary = 0
        for raw_item, expected_subtask in zip(
            checkpoint_support, expected_subtasks
        ):
            item = _exact_fields(
                raw_item,
                (
                    "subtask_index",
                    "checkpoint_summary",
                    "satisfied",
                    "establishing_action_global_indices",
                    "no_later_clobber_at_boundary",
                ),
                "checkpoint_support entry",
            )
            subtask_index = _strict_integer(
                item["subtask_index"], "checkpoint subtask_index", minimum=1
            )
            observed_subtasks.append(subtask_index)
            boundary = action_boundary_by_subtask.get(
                expected_subtask, previous_boundary
            )
            previous_boundary = boundary
            references = item["establishing_action_global_indices"]
            if not isinstance(references, list):
                raise ValueError(
                    "checkpoint establishing_action_global_indices must be an array"
                )
            for reference in references:
                index = _strict_integer(
                    reference, "checkpoint establishing action index"
                )
                if index > boundary:
                    raise ValueError(
                        "checkpoint witness cannot reference an action after its boundary"
                    )
            if not isinstance(item["checkpoint_summary"], str):
                raise ValueError("checkpoint_summary must be a string")
            if not isinstance(item["satisfied"], bool):
                raise ValueError("checkpoint satisfied must be boolean")
            if not isinstance(item["no_later_clobber_at_boundary"], bool):
                raise ValueError(
                    "no_later_clobber_at_boundary must be boolean"
                )
        if observed_subtasks != expected_subtasks:
            raise ValueError(
                "checkpoint_support must contain exactly one ordered entry per subtask"
            )

        final_support = payload.get("final_requirement_support")
        if not isinstance(final_support, list):
            raise ValueError("final_requirement_support must be an array")
        expected_requirements = [
            (
                item["requirement_id"],
                item["requirement_kind"],
                item["requirement"],
            )
            for item in self._pending_final_requirements
        ]
        observed_requirements: List[Tuple[str, str, str]] = []
        final_action_index = len(expected_actions)
        for raw_item in final_support:
            item = _exact_fields(
                raw_item,
                (
                    "requirement_id",
                    "requirement_kind",
                    "requirement",
                    "satisfied",
                    "establishing_action_global_indices",
                    "no_later_clobber",
                ),
                "final_requirement_support entry",
            )
            observed_requirements.append(
                (
                    str(item["requirement_id"]),
                    str(item["requirement_kind"]),
                    str(item["requirement"]),
                )
            )
            references = item["establishing_action_global_indices"]
            if not isinstance(references, list):
                raise ValueError(
                    "final establishing_action_global_indices must be an array"
                )
            for reference in references:
                index = _strict_integer(
                    reference, "final establishing action index"
                )
                if index > final_action_index:
                    raise ValueError(
                        "final witness references an action outside the candidate"
                    )
            if not isinstance(item["satisfied"], bool):
                raise ValueError("final requirement satisfied must be boolean")
            if not isinstance(item["no_later_clobber"], bool):
                raise ValueError("no_later_clobber must be boolean")
        if observed_requirements != expected_requirements:
            raise ValueError(
                "final_requirement_support must exactly cover the listed obligations"
            )

    def parse_router(self, output: str) -> RouterVerdict:
        try:
            payload = json.loads(output)
            if not isinstance(payload, dict) or set(payload) != set(
                PROOF_AUDIT_SCHEMA["required"]
            ):
                raise ValueError("proof-audit response has incorrect fields")
            self._validate_proof_coverage(payload)
            verdict = str(payload["verdict"])
            subtask = int(payload["first_bad_subtask"])
            action = int(payload["first_bad_action_in_subtask"])
            owner_text = str(payload["owner"])
            reason = str(payload["reason"]).strip() or "N/A"
            if verdict == "VALID":
                if subtask != 0 or action != 0 or owner_text != "NA":
                    raise ValueError("VALID requires zero indices and owner NA")
                if any(
                    item.get("applicable") is not True
                    or item.get("effects_applied") is not True
                    or any(
                        witness.get("source_still_holds") is not True
                        for witness in item.get("precondition_witnesses", ())
                    )
                    for item in payload["action_support"]
                ):
                    raise ValueError("VALID action certificate contains a false claim")
                if any(
                    item.get("satisfied") is not True
                    or item.get("no_later_clobber_at_boundary") is not True
                    for item in payload["checkpoint_support"]
                ):
                    raise ValueError("VALID checkpoint certificate contains a false claim")
                if any(
                    item.get("satisfied") is not True
                    or item.get("no_later_clobber") is not True
                    for item in payload["final_requirement_support"]
                ):
                    raise ValueError("VALID final certificate contains a false claim")
                parsed = RouterVerdict(True, "both", reason)
            elif verdict == "INVALID":
                if subtask <= 0 or action < 0 or owner_text == "NA":
                    raise ValueError(
                        "INVALID requires a positive subtask and non-NA owner"
                    )
                reason = (
                    f"Subtask {subtask}, action {action}: {reason}"
                    if action
                    else f"Subtask {subtask}, boundary/final requirement: {reason}"
                )
                parsed = RouterVerdict(
                    False, _normalize_owner(owner_text), reason
                )
            else:
                raise ValueError(f"unknown verdict {verdict!r}")
            self.proof_audit_records.append(
                {**payload, "parse_valid": True}
            )
            if not parsed.no_mistake:
                self._pending_challenge_output = None
                return parsed
            if self._pending_challenge_output is None:
                self.proof_challenge_records.append(
                    {
                        "counterexample_found": True,
                        "reason": "VALID proof was not independently challenged",
                        "parse_valid": False,
                    }
                )
                return RouterVerdict(
                    False,
                    "both",
                    "VALID proof was not independently challenged",
                )
            challenge_output = self._pending_challenge_output
            self._pending_challenge_output = None
            return self.parse_router_challenge(challenge_output)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            self._pending_challenge_output = None
            self.proof_audit_records.append(
                {
                    "verdict": "INVALID",
                    "reason": f"Malformed proof audit: {error}",
                    "parse_valid": False,
                }
            )
            return RouterVerdict(
                False, "both", f"Malformed proof audit: {error}"
            )

    def proof_claim_requires_challenge(self, output: str) -> bool:
        """Return whether ``output`` is a structurally acceptable VALID claim.

        This is a dispatch guard for the dedicated client proxy.  It records no
        verdict and performs no semantic check.
        """

        try:
            payload = json.loads(output)
            if not isinstance(payload, dict) or set(payload) != set(
                PROOF_AUDIT_SCHEMA["required"]
            ):
                return False
            self._validate_proof_coverage(payload)
            if (
                payload.get("verdict") != "VALID"
                or int(payload.get("first_bad_subtask", -1)) != 0
                or int(payload.get("first_bad_action_in_subtask", -1)) != 0
                or payload.get("owner") != "NA"
            ):
                return False
            if any(
                item.get("applicable") is not True
                or item.get("effects_applied") is not True
                or any(
                    witness.get("source_still_holds") is not True
                    for witness in item.get("precondition_witnesses", ())
                )
                for item in payload["action_support"]
            ):
                return False
            if any(
                item.get("satisfied") is not True
                or item.get("no_later_clobber_at_boundary") is not True
                for item in payload["checkpoint_support"]
            ):
                return False
            return not any(
                item.get("satisfied") is not True
                or item.get("no_later_clobber") is not True
                for item in payload["final_requirement_support"]
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return False

    def pending_router_challenge_request(self, proof_output: str) -> StageRequest:
        """Construct a challenge for the most recently requested proof audit."""

        if not self._pending_challenge_context:
            raise RuntimeError("no proof-audit context is pending")
        return StageRequest(
            stage="innerbot_challenge",
            system=SYSTEM_PROOF_CHALLENGE_ROUTER,
            prompt=proof_challenge_router_prompt(
                proof_output=proof_output,
                **self._pending_challenge_context,
            ),
            response_schema=PROOF_CHALLENGE_SCHEMA,
            schema_name="n_hierarchy_proof_challenge_v1",
        )

    def install_router_challenge_output(self, output: str) -> None:
        """Bind one independently generated challenge to the pending proof."""

        if self._pending_challenge_output is not None:
            raise RuntimeError("a challenge output is already pending")
        self._pending_challenge_output = output

    def router_challenge_request(
        self,
        task: object,
        state: object,
        scene: object,
        state_output: str,
        decision_output: str,
        hierarchy_output: str,
        projection: object,
        proof_output: str,
        execution_feedback: Optional[str] = None,
    ) -> StageRequest:
        del task, state, scene, state_output, decision_output, hierarchy_output
        del projection, execution_feedback
        return self.pending_router_challenge_request(proof_output)

    def parse_router_challenge(self, output: str) -> RouterVerdict:
        try:
            payload = json.loads(output)
            if not isinstance(payload, dict) or set(payload) != set(
                PROOF_CHALLENGE_SCHEMA["required"]
            ):
                raise ValueError("proof-challenge response has incorrect fields")
            found = payload["counterexample_found"]
            if not isinstance(found, bool):
                raise ValueError("counterexample_found must be boolean")
            subtask = int(payload["earliest_bad_subtask"])
            action = int(payload["earliest_bad_action_in_subtask"])
            owner_text = str(payload["owner"])
            category = str(payload["category"])
            reason = str(payload["reason"]).strip() or "N/A"
            if found:
                if subtask <= 0 or action < 0 or owner_text == "NA":
                    raise ValueError(
                        "counterexample requires positive subtask and non-NA owner"
                    )
                if category == "NONE":
                    raise ValueError("counterexample requires a non-NONE category")
                parsed = RouterVerdict(
                    False,
                    _normalize_owner(owner_text),
                    (
                        f"Challenge found {category} at subtask {subtask}, "
                        f"action {action}: {reason}"
                    ),
                )
            else:
                if (
                    subtask != 0
                    or action != 0
                    or owner_text != "NA"
                    or category != "NONE"
                    or str(payload["challenged_claim"]) != "N/A"
                ):
                    raise ValueError(
                        "no-counterexample response requires zero indices, owner NA, "
                        "category NONE, and challenged_claim N/A"
                    )
                parsed = RouterVerdict(True, "both", reason)
            self.proof_challenge_records.append(
                {**payload, "parse_valid": True}
            )
            return parsed
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            self.proof_challenge_records.append(
                {
                    "counterexample_found": True,
                    "reason": f"Malformed proof challenge: {error}",
                    "parse_valid": False,
                }
            )
            return RouterVerdict(
                False, "both", f"Malformed proof challenge: {error}"
            )


class ProofAuditLLMOnlyLexiconAdapter(
    _ProofAuditMixin, ExecutionAuditLLMOnlyLexiconAdapter
):
    """Logistics adapter for proof-carrying LLM-only verification."""

    def __init__(self) -> None:
        super().__init__()
        self._init_proof_audit()

    def _problem_text(self, task: object) -> str:
        return lexicon._model_task_text(task)


class ProofAuditLLMOnlyBlocksworldAdapter(
    _ProofAuditMixin, ExecutionAuditLLMOnlyBlocksworldAdapter
):
    """Blocksworld adapter for proof-carrying LLM-only verification."""

    def __init__(self) -> None:
        super().__init__()
        self._init_proof_audit()

    def _problem_text(self, task: object) -> str:
        return blocksworld._model_task_text(task)


__all__ = [
    "PIPELINE_VERSION",
    "PROOF_AUDIT_SCHEMA",
    "PROOF_CHALLENGE_SCHEMA",
    "SYSTEM_PROOF_AUDIT_ROUTER",
    "SYSTEM_PROOF_CHALLENGE_ROUTER",
    "ProofAuditLLMOnlyBlocksworldAdapter",
    "ProofAuditLLMOnlyLexiconAdapter",
    "proof_audit_router_prompt",
    "proof_challenge_router_prompt",
]
