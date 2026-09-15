"""Flat-Hanoi port of the v5 LLM-only proof-plus-challenge audit.

Planning uses a non-rejecting shadow reducer over the public Hanoi effects.
The proof auditor and independent challenger see the current visible state,
the composed hierarchy, and every expanded H0 primitive, but no deterministic
legality, checkpoint, or goal verdict.  The deterministic Hanoi simulator is
invoked exactly once, from :meth:`final_score`.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from dynamic_scoring import legacy_call_counts
from flat_hanoi_scoring import score_from_execution
from flat_prompts import build_goal_description, task_spec_for_prompt
from scoring import simulate_hanoi
from shared_nlevel_execution_audit_adapter import _execution_boundary_payload
from shared_nlevel_pipeline import (
    ArtifactCheck,
    FinalScoreContext,
    StageRequest,
    TransitionResult,
)
from shared_nlevel_proof_audit_adapter import (
    PIPELINE_VERSION,
    PROOF_AUDIT_SCHEMA,
    SYSTEM_PROOF_AUDIT_ROUTER,
    _ProofAuditMixin,
    proof_audit_router_prompt,
)
from shared_nlevel_verified_repair_adapters import (
    VerifiedRepairFlatHanoiNLevelAdapter,
)


SYSTEM_PROOF_AUDIT_OUTER_HANOI = (
    "OuterBot for the Flat-Hanoi v5 LLM-only proof-audit ablation: judge a "
    "subtask using public rules and unchecked shadow states."
)

_HANOI_TRACE_REQUIREMENTS: Tuple[str, ...] = (
    "Move one ring at a time.",
    "Only move the top ring of a peg.",
    "Never place a larger ring on top of a smaller ring.",
)


def _copy_stacks(
    state: Mapping[str, Sequence[str]],
) -> Dict[str, List[str]]:
    return {str(peg): [str(ring) for ring in stack] for peg, stack in state.items()}


def _flat_final_requirements(task: object) -> List[Dict[str, str]]:
    requirements = [
        {
            "requirement_id": "goal_1",
            "requirement_kind": "goal",
            "requirement": (
                "The final peg stacks, listed bottom-to-top, must equal "
                + json.dumps(getattr(task, "goal"), sort_keys=True)
            ),
        }
    ]
    requirements.extend(
        {
            "requirement_id": f"constraint_{index}",
            "requirement_kind": "temporal_constraint",
            "requirement": text,
        }
        for index, text in enumerate(_HANOI_TRACE_REQUIREMENTS, start=1)
    )
    return requirements


def _flat_public_problem_text(task: object) -> str:
    return f"""FLAT-HANOI TASK SPECIFICATION
{task_spec_for_prompt(task)}

PUBLIC H0 EXECUTION RULES
- Peg stacks are listed bottom-to-top; the last ring is the movable top ring.
- Ring size is the numeric `size` in the task specification. A larger numeric
  size may never be dropped on a smaller numeric size.
- MoveCoroutine(peg) moves the arm to that named reachable peg. It changes no
  ring relation. When a ring is held, it carries that one ring to the peg.
- GrabCoroutine() requires the arm to be over a nonempty peg and no ring to be
  held. It removes and holds exactly that peg's top ring.
- DropCoroutine() requires one held ring and the arm over a named peg. It may
  append that ring only when the peg is empty or its top ring is larger.
- One logical ring move is the canonical ordered group
  MoveCoroutine(source), GrabCoroutine(), MoveCoroutine(target),
  DropCoroutine(). Every expanded H0 primitive must nevertheless receive its
  own proof record.
- The complete trace must satisfy all three instruction constraints and end
  at the exact target stacks. No shortest-path or optimal-length information
  is available during planning.
"""


class _LLMOnlyFlatHanoiAdapter(VerifiedRepairFlatHanoiNLevelAdapter):
    """Flat-Hanoi controller with no online deterministic semantic authority."""

    verifier_mode = (
        "llm-only-proof-plus-challenge-online; official-hanoi-final-only"
    )
    architecture_mode = PIPELINE_VERSION
    llm_only_online = True
    online_verification_authoritative = False

    def __init__(self) -> None:
        self.official_final_evaluator_call_count = 0

    def goal_reached(self, task: object, state: object) -> bool:
        del task, state
        return False

    is_goal = goal_reached

    def apply_action(
        self,
        task: object,
        state: Mapping[str, Sequence[str]],
        action: Tuple[str, str],
        action_index: int,
    ) -> TransitionResult:
        del task, action_index
        next_state = _copy_stacks(state)
        try:
            source, target = (str(action[0]), str(action[1]))
        except (IndexError, TypeError):
            source, target = "", ""

        # Apply only the visible public effect. Missing preconditions, unknown
        # pegs, empty sources, size ordering, checkpoints, and the goal are not
        # checked and can never reject a candidate during planning.
        if source in next_state and target in next_state and next_state[source]:
            ring = next_state[source].pop()
            next_state[target].append(ring)
        return TransitionResult(
            True,
            next_state,
            "semantic verification withheld",
            {
                "semantic_verification": "WITHHELD",
                "state_kind": "non-rejecting-public-effect-shadow",
                "shadow_state_authoritative": False,
            },
        )

    def validate_projected_subtask(
        self,
        task: object,
        decision: object,
        subtask: object,
        projected_state: object,
        is_last: bool,
    ) -> ArtifactCheck:
        del task, decision, subtask, projected_state, is_last
        return ArtifactCheck.accepted(
            None,
            metadata={
                "semantic_verification": "WITHHELD",
                "checkpoint_checked": False,
                "goal_checked": False,
            },
        )

    def outer_request(self, *args: object, **kwargs: object) -> StageRequest:
        request = super().outer_request(*args, **kwargs)
        warning = (
            "SEMANTIC VERIFICATION IS WITHHELD. The displayed current state is "
            "an unchecked public-effect shadow, not simulator evidence. Judge "
            "applicability, checkpoint achievement, constraints, and completion "
            "yourself from the public task rules.\n\n"
        )
        return replace(
            request,
            system=SYSTEM_PROOF_AUDIT_OUTER_HANOI,
            prompt=warning + request.prompt,
        )

    def final_score(self, context: FinalScoreContext):
        self.official_final_evaluator_call_count += 1
        if self.official_final_evaluator_call_count != 1:
            raise RuntimeError(
                "proof-audit ablation attempted to call the official Hanoi "
                "evaluator more than once"
            )

        moves = [
            (str(action[0]), str(action[1]))
            for action in context.executed_actions
        ]
        legal, illegal_reason, final_state = simulate_hanoi(context.task, moves)
        h1_call_count, h2_call_count = legacy_call_counts(context.level_totals)
        return score_from_execution(
            task=context.task,
            final_state=final_state,
            moves=moves,
            high_level_plan=list(context.high_level_plan),
            expanded_h0_plan=list(context.expanded_h0_plan),
            h1_valid=context.base_valid_any,
            h2_valid=context.hierarchy_valid_any,
            h1_call_count=h1_call_count,
            h2_call_count=h2_call_count,
            h0_call_count=context.total_h0_count,
            top_level_call_count=context.total_top_level_count,
            parse_errors=list(context.parse_errors),
            illegal_reason=illegal_reason,
        )


class ProofAuditLLMOnlyFlatHanoiAdapter(
    _ProofAuditMixin, _LLMOnlyFlatHanoiAdapter
):
    """Proof-carrying, independently challenged Flat-Hanoi LLM-only verifier."""

    def __init__(self) -> None:
        super().__init__()
        self._init_proof_audit()

    def _problem_text(self, task: object) -> str:
        return _flat_public_problem_text(task)

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
        requirements = _flat_final_requirements(task)
        visible_descriptor = (
            f"{state_output}\n\nVISIBLE CURRENT SCENE (unchecked observation):\n"
            + json.dumps(scene, indent=2, sort_keys=True)
        )
        context = {
            "problem_text": self._problem_text(task),
            "descriptor_output": visible_descriptor,
            "decision_output": decision_output,
            "hierarchy_output": hierarchy_output,
            "execution_boundary_actions": boundary,
            "final_requirements": requirements,
            "feedback": execution_feedback,
        }
        self._pending_proof_boundary = boundary
        self._pending_final_requirements = requirements
        self._pending_challenge_context = context
        self._pending_challenge_output = None
        return StageRequest(
            stage="innerbot_router",
            system=SYSTEM_PROOF_AUDIT_ROUTER,
            prompt=proof_audit_router_prompt(**context),
            response_schema=PROOF_AUDIT_SCHEMA,
            schema_name="n_hierarchy_proof_audit_v1",
        )


__all__ = [
    "PIPELINE_VERSION",
    "SYSTEM_PROOF_AUDIT_OUTER_HANOI",
    "ProofAuditLLMOnlyFlatHanoiAdapter",
]
