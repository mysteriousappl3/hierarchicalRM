"""Compact, coverage-bound requirement evidence for the one-InnerBot audit.

This guard checks certificate shape, coverage, and arithmetic consistency of
the model's own reported witnesses. It never evaluates predicates, replays
actions, or certifies that a claimed witness is true. Semantic verification
therefore remains probabilistic and LLM-only.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import re
from typing import Dict, Mapping, Optional

from shared_nlevel_execution_audit_v3_adapter import SINGLE_INNERBOT_AUDIT_SCHEMA
from shared_nlevel_pipeline import RouterVerdict, StageRequest


_OBLIGATION_TYPES = (
    "final_goal", "sometime", "always", "at_most_once", "sometime_before",
    "sometime_after", "other_temporal",
)
_EVIDENCE_FIELDS = (
    "requirement_id", "obligation_type", "satisfied", "evaluated_through_state",
    "witness_states", "latest_trigger_state", "latest_response_state",
    "vacuous", "evidence",
)
_NULLABLE_INDEX = {"type": ["integer", "null"], "minimum": 0}

REQUIREMENT_EVIDENCE_AUDIT_SCHEMA = deepcopy(SINGLE_INNERBOT_AUDIT_SCHEMA)
REQUIREMENT_EVIDENCE_AUDIT_SCHEMA["required"].append("requirement_evidence")
REQUIREMENT_EVIDENCE_AUDIT_SCHEMA["properties"]["requirement_evidence"] = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": list(_EVIDENCE_FIELDS),
        "properties": {
            "requirement_id": {"type": "string"},
            "obligation_type": {"type": "string", "enum": list(_OBLIGATION_TYPES)},
            "satisfied": {"type": "boolean"},
            "evaluated_through_state": {"type": "integer", "minimum": 0},
            "witness_states": {
                "type": "array", "items": {"type": "integer", "minimum": 0},
            },
            "latest_trigger_state": deepcopy(_NULLABLE_INDEX),
            "latest_response_state": deepcopy(_NULLABLE_INDEX),
            "vacuous": {"type": "boolean"},
            "evidence": {"type": "string"},
        },
    },
}

REQUIREMENT_EVIDENCE_PROMPT = """COMPACT REQUIREMENT EVIDENCE -- SUCCESS FIRST
The existing forward legality and checkpoint checks remain mandatory. In the
same InnerBot call, add one compact `requirement_evidence` record for every
listed final requirement before returning VALID. Use the exact requirement IDs
and obligation types in the evidence manifest. Do not emit a second full
action-by-action proof or invent additional terminal conditions.

Index the supplied canonical execution-boundary actions globally, across all
subtasks. State 0 is the visible candidate-start state; state i is immediately
after canonical action i; state N is the state after the final listed action.
Use these canonical action indices, not H-level calls, semantic move counts,
or per-subtask indices. `evaluated_through_state` is how far the requirement was
checked; for VALID every row must reach N. `witness_states` names actual
supporting states. Every listed witness must follow from your forward ledger,
not the planner's intention or the unchecked shadow's appearance.

For a final_goal, explicitly test the entire goal in state N. Include N in
`witness_states`; explain the final fact and its last establishment or relevant
deletion in `evidence`. An earlier witness does not establish a final goal.
Keep `latest_trigger_state` and `latest_response_state` null and `vacuous` false.

For sometime, record a state in which the whole formula holds. For always,
check all states 0..N. For at_most_once, check the complete truth-interval
history, not just two sampled states. For sometime_before, check the public
strict-prior-witness rule at every relevant trigger. For these types, and for
other_temporal rules, keep the two latest_* fields null and explain the
relevant history compactly. Do not preserve a historical witness unnecessarily
at the terminal state, but do enforce continuing and triggered obligations.

For this benchmark's sometime_after(A, B), EVERY state where A holds requires
B at that same or a later state. This is non-strict: equal state indices count.
Repeated or persistent A creates obligations too. Report the actual LAST
state where A holds in `latest_trigger_state` and LAST state where B holds in
`latest_response_state`; put that response state in `witness_states` if one
exists. A historical B before a later A is not sufficient. If A never holds,
use a null latest_trigger_state and `vacuous: true`; B may or may not have a
witness. Otherwise use `vacuous: false`, and a satisfied requirement must have
latest_response_state >= latest_trigger_state. If A holds at N, B must hold at
N. Explain the concrete grounded predicates, last trigger, and response.

For VALID, every row must say satisfied=true, with nonempty factual evidence,
and IDs must cover the manifest exactly once. For INVALID, stop at the earliest
failure as before: `requirement_evidence` may be [] or contain only records
actually checked. Do not fabricate completed evidence to satisfy the schema.
All fields are still required in any emitted record; use null where specified.

The Python guard checks only IDs, index bounds, complete coverage, and
consistency of your own reported evidence. It does NOT check witness truth,
execute the domain, or supply simulator feedback. You remain responsible for
all semantic reasoning; a well-shaped certificate alone is not evidence.
"""


class _RequirementEvidenceGuardError(ValueError):
    """A well-shaped certificate contradicts its own acceptance claim."""


def _obligation_type(requirement: Mapping[str, object]) -> str:
    """Read a public operator label, without interpreting its formula."""
    if requirement.get("requirement_kind") == "goal":
        return "final_goal"
    match = re.match(r"\s*\(\s*([\w-]+)(?:\s|\))", str(requirement.get("requirement", "")))
    operator = match.group(1).replace("-", "_") if match else "other_temporal"
    return operator if operator in _OBLIGATION_TYPES[1:] else "other_temporal"


def _state_index(value: object, label: str, terminal_state: int, *, nullable=False):
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer state index")
    if not 0 <= value <= terminal_state:
        raise _RequirementEvidenceGuardError(
            f"{label} is outside the candidate trace 0..{terminal_state}"
        )
    return value


class StructuredRequirementEvidenceMixin:
    """Opt-in response-schema extension; mix before the v3.1 domain adapter."""

    requirement_evidence_revision = "compact_requirement_evidence_v1"

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
        request = super().router_request(
            task, state, scene, state_output, decision_output, hierarchy_output,
            projection, execution_feedback=execution_feedback,
        )
        self._pending_evidence_manifest = {
            str(item["requirement_id"]): _obligation_type(item)
            for item in self._requirements(task)
        }
        manifest = {
            "terminal_state_index": self._pending_audit_manifest["expected_actions"],
            "requirements": [
                {"requirement_id": key, "obligation_type": value}
                for key, value in self._pending_evidence_manifest.items()
            ],
        }
        return replace(
            request,
            prompt=request.prompt + "\n\n" + REQUIREMENT_EVIDENCE_PROMPT
            + "\nREQUIREMENT EVIDENCE MANIFEST:\n" + json.dumps(manifest, sort_keys=True),
            response_schema=REQUIREMENT_EVIDENCE_AUDIT_SCHEMA,
            schema_name="n_hierarchy_single_innerbot_requirement_evidence_v3_3",
        )

    def _validate_requirement_evidence(self, payload: Mapping[str, object]) -> None:
        if set(payload) != set(REQUIREMENT_EVIDENCE_AUDIT_SCHEMA["required"]):
            raise ValueError("requirement-evidence audit has incorrect fields")
        manifest = getattr(self, "_pending_evidence_manifest", None)
        if manifest is None:
            raise ValueError("no pending requirement evidence manifest")
        rows = payload["requirement_evidence"]
        if not isinstance(rows, list):
            raise ValueError("requirement_evidence must be an array")
        terminal = self._pending_audit_manifest["expected_actions"]
        accepting = payload.get("verdict") == "VALID"
        seen = set()
        for index, row in enumerate(rows):
            label = f"requirement_evidence[{index}]"
            if not isinstance(row, dict) or set(row) != set(_EVIDENCE_FIELDS):
                raise ValueError(f"{label} has incorrect fields")
            identity = row["requirement_id"]
            if not isinstance(identity, str) or identity not in manifest:
                raise _RequirementEvidenceGuardError(f"{label} has an unknown requirement ID")
            if identity in seen:
                raise _RequirementEvidenceGuardError(f"duplicate requirement ID {identity}")
            seen.add(identity)
            kind = row["obligation_type"]
            if kind != manifest[identity]:
                raise _RequirementEvidenceGuardError(
                    f"{identity} obligation_type must be {manifest[identity]}"
                )
            if not isinstance(row["satisfied"], bool) or not isinstance(row["vacuous"], bool):
                raise ValueError(f"{identity} satisfied and vacuous must be boolean")
            if not isinstance(row["evidence"], str) or not row["evidence"].strip():
                raise ValueError(f"{identity} requires nonempty textual evidence")
            through = _state_index(row["evaluated_through_state"], f"{identity}.evaluated_through_state", terminal)
            witnesses = row["witness_states"]
            if not isinstance(witnesses, list):
                raise ValueError(f"{identity}.witness_states must be an array")
            for witness in witnesses:
                _state_index(witness, f"{identity}.witness_states", terminal)
            trigger = _state_index(row["latest_trigger_state"], f"{identity}.latest_trigger_state", terminal, nullable=True)
            response = _state_index(row["latest_response_state"], f"{identity}.latest_response_state", terminal, nullable=True)
            if not accepting:
                continue  # Early INVALID reports do not need completed support.
            if row["satisfied"] is not True or through != terminal:
                raise _RequirementEvidenceGuardError(
                    f"VALID requires {identity} satisfied and checked through terminal state {terminal}"
                )
            if kind == "sometime_after":
                if row["vacuous"] != (trigger is None):
                    raise _RequirementEvidenceGuardError(
                        f"{identity} vacuity must agree with absence of a trigger"
                    )
                if trigger is not None and (response is None or response < trigger):
                    raise _RequirementEvidenceGuardError(
                        f"{identity} latest response must be at or after its latest trigger"
                    )
                if response is not None and response not in witnesses:
                    raise _RequirementEvidenceGuardError(
                        f"{identity} latest response must be included in witness_states"
                    )
            else:
                if trigger is not None or response is not None:
                    raise _RequirementEvidenceGuardError(
                        f"{identity} latest_* fields are reserved for sometime_after"
                    )
                if kind == "final_goal" and (terminal not in witnesses or row["vacuous"]):
                    raise _RequirementEvidenceGuardError(
                        f"{identity} requires a non-vacuous terminal-state witness"
                    )
                if kind == "sometime" and (not witnesses or row["vacuous"]):
                    raise _RequirementEvidenceGuardError(
                        f"{identity} requires a non-vacuous witness"
                    )
        if accepting and seen != set(manifest):
            missing = sorted(set(manifest) - seen)
            raise _RequirementEvidenceGuardError(
                f"VALID requires exactly one evidence row per requirement; missing {missing}"
            )

    def parse_router(self, output: str) -> RouterVerdict:
        try:
            payload = json.loads(output)
        except (TypeError, ValueError):
            payload = None
        stripped = (
            {key: value for key, value in payload.items() if key != "requirement_evidence"}
            if isinstance(payload, dict) else payload
        )
        verdict = super().parse_router(json.dumps(stripped) if isinstance(payload, dict) else output)
        record: Dict[str, object] = self.single_innerbot_audit_records[-1]
        if isinstance(payload, dict):
            record["requirement_evidence"] = payload.get("requirement_evidence")
        record["requirement_evidence_revision"] = self.requirement_evidence_revision
        if record.get("parse_valid") is not True:
            record["requirement_evidence_guard_passed"] = False
            return verdict
        try:
            self._validate_requirement_evidence(payload)
        except (TypeError, ValueError) as error:
            record.update({
                "effective_verdict": "INVALID",
                "requirement_evidence_guard_passed": False,
                "requirement_evidence_guard_reason": str(error),
            })
            if not isinstance(error, _RequirementEvidenceGuardError):
                record["parse_valid"] = False
                # Preserve the established telemetry invariant: an unparsed
                # certificate cannot claim to have passed coverage validation.
                record["coverage_guard_passed"] = False
            return RouterVerdict(False, "both", f"Requirement evidence guard rejected audit: {error}")
        record["requirement_evidence_guard_passed"] = True
        return verdict


__all__ = [
    "REQUIREMENT_EVIDENCE_AUDIT_SCHEMA", "REQUIREMENT_EVIDENCE_PROMPT",
    "StructuredRequirementEvidenceMixin",
]
