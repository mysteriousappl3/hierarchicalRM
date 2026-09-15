"""Regular-v3 audit adapters with coherent full-candidate start context.

The shared controller may ask InnerBot to audit the same complete candidate a
second time after tentative execution reaches an OuterBot rejection.  The
candidate-start descriptor and scene are the authoritative start for both
calls.  A scene rendered after tentative execution is diagnostic feedback,
not another candidate start, so this variant replaces it with the frozen
primary-audit scene before constructing a recheck request.

Flat Hanoi additionally composes the shared ``CheckpointNoOp()`` compiler
contract so an already-satisfied numbered checkpoint has a legal zero-action
representation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Optional

from shared_nlevel_execution_audit_v3_adapter import (
    SingleInnerBotDualPassBlocksworldAdapter,
    SingleInnerBotDualPassFlatHanoiAdapter,
    SingleInnerBotDualPassLexiconAdapter,
)
from shared_nlevel_flat_hanoi_checkpoint_noop import (
    FlatHanoiCheckpointNoOpMixin,
)


PIPELINE_VERSION = (
    "shared_nlevel_v5_llm_only_execution_audit_v3_2_checkpoint_contract"
)
V3_2_IMPLEMENTATION_REVISION = (
    "shared_nlevel_v5_llm_only_execution_audit_v3_2_checkpoint_noop_frozen_start"
)
TENTATIVE_RECHECK_FEEDBACK_HEADER = (
    "TENTATIVE POST-SUBTASK FAILURE CONTEXT (not the candidate start):"
)


class _FrozenCandidateStartContextMixin:
    """Reuse the primary audit's complete start context during a recheck."""

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
    ):
        if execution_feedback is None:
            self._v3_2_candidate_start_state = deepcopy(state)
            self._v3_2_candidate_start_scene = deepcopy(scene)
            self._v3_2_candidate_start_descriptor = state_output
        elif hasattr(self, "_v3_2_candidate_start_scene"):
            state = deepcopy(self._v3_2_candidate_start_state)
            scene = deepcopy(self._v3_2_candidate_start_scene)
            state_output = self._v3_2_candidate_start_descriptor
        else:
            # Defensive support for a direct recheck request outside the
            # controller's normal primary-audit-before-recheck lifecycle.
            self._v3_2_candidate_start_state = deepcopy(state)
            self._v3_2_candidate_start_scene = deepcopy(scene)
            self._v3_2_candidate_start_descriptor = state_output

        if execution_feedback is not None:
            execution_feedback = (
                f"{TENTATIVE_RECHECK_FEEDBACK_HEADER}\n{execution_feedback}"
            )

        return super().router_request(
            task,
            state,
            scene,
            state_output,
            decision_output,
            hierarchy_output,
            projection,
            execution_feedback=execution_feedback,
        )


class V32SingleInnerBotDualPassLexiconAdapter(
    _FrozenCandidateStartContextMixin,
    SingleInnerBotDualPassLexiconAdapter,
):
    """Regular-v3 Logistics adapter with coherent candidate-start context."""

    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = V3_2_IMPLEMENTATION_REVISION


class V32SingleInnerBotDualPassBlocksworldAdapter(
    _FrozenCandidateStartContextMixin,
    SingleInnerBotDualPassBlocksworldAdapter,
):
    """Regular-v3 Blocksworld adapter with coherent candidate-start context."""

    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = V3_2_IMPLEMENTATION_REVISION


class V32SingleInnerBotDualPassFlatHanoiAdapter(
    FlatHanoiCheckpointNoOpMixin,
    _FrozenCandidateStartContextMixin,
    SingleInnerBotDualPassFlatHanoiAdapter,
):
    """Regular-v3 Flat-Hanoi adapter with both v3.2 contract corrections."""

    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = V3_2_IMPLEMENTATION_REVISION


__all__ = [
    "PIPELINE_VERSION",
    "TENTATIVE_RECHECK_FEEDBACK_HEADER",
    "V3_2_IMPLEMENTATION_REVISION",
    "V32SingleInnerBotDualPassBlocksworldAdapter",
    "V32SingleInnerBotDualPassFlatHanoiAdapter",
    "V32SingleInnerBotDualPassLexiconAdapter",
]
