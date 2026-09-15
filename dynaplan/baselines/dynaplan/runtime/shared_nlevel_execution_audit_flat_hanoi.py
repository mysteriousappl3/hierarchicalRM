"""Flat-Hanoi port of the v5 LLM-only execution-boundary audit.

The online controller uses the same non-rejecting public-effect shadow as the
Flat-Hanoi proof-audit port.  One InnerBot sees the visible state, DecisionBot
checkpoints, composed hierarchy, and canonical H0 expansion, but receives no
deterministic legality, checkpoint, goal, or constraint verdict.  The official
Hanoi simulator is invoked exactly once by the inherited final scorer.
"""

from __future__ import annotations

from dataclasses import replace
import json
from typing import Optional

from shared_nlevel_execution_audit_adapter import (
    EXECUTION_AUDIT_SCHEMA,
    EXECUTION_AUDIT_IMPLEMENTATION_REVISION,
    PIPELINE_VERSION,
    SYSTEM_EXECUTION_AUDIT_ROUTER,
    ExecutionAuditLLMOnlyLexiconAdapter,
    _execution_boundary_payload,
    execution_audit_router_prompt,
)
from shared_nlevel_pipeline import StageRequest
from shared_nlevel_proof_audit_flat_hanoi import (
    _LLMOnlyFlatHanoiAdapter,
    _flat_public_problem_text,
)


SYSTEM_EXECUTION_AUDIT_OUTER_HANOI = (
    "OuterBot for the Flat-Hanoi v5 LLM-only execution-audit ablation: judge "
    "a subtask using public rules and unchecked shadow states."
)


class ExecutionAuditLLMOnlyFlatHanoiAdapter(_LLMOnlyFlatHanoiAdapter):
    """Composed-plus-expanded InnerBot audit for Flat-Hanoi."""

    verifier_mode = (
        "llm-only-execution-audit-online; official-hanoi-final-only"
    )
    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = (
        EXECUTION_AUDIT_IMPLEMENTATION_REVISION
    )
    transactional_candidate_execution = True

    def __init__(self) -> None:
        super().__init__()
        self.execution_audit_records: list[dict[str, object]] = []

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
        visible_descriptor = (
            f"{state_output}\n\nVISIBLE CURRENT SCENE (unchecked observation):\n"
            + json.dumps(scene, indent=2, sort_keys=True)
        )
        return StageRequest(
            stage="innerbot_router",
            system=SYSTEM_EXECUTION_AUDIT_ROUTER,
            prompt=execution_audit_router_prompt(
                problem_text=_flat_public_problem_text(task),
                descriptor_output=visible_descriptor,
                decision_output=decision_output,
                hierarchy_output=hierarchy_output,
                execution_boundary_actions=boundary,
                feedback=execution_feedback,
            ),
            response_schema=EXECUTION_AUDIT_SCHEMA,
            schema_name="n_hierarchy_execution_boundary_audit_v1",
        )

    def parse_router(self, output: str):
        return ExecutionAuditLLMOnlyLexiconAdapter.parse_router(self, output)

    def outer_request(self, *args: object, **kwargs: object) -> StageRequest:
        request = super().outer_request(*args, **kwargs)
        return replace(request, system=SYSTEM_EXECUTION_AUDIT_OUTER_HANOI)


__all__ = [
    "EXECUTION_AUDIT_IMPLEMENTATION_REVISION",
    "PIPELINE_VERSION",
    "SYSTEM_EXECUTION_AUDIT_OUTER_HANOI",
    "ExecutionAuditLLMOnlyFlatHanoiAdapter",
]
