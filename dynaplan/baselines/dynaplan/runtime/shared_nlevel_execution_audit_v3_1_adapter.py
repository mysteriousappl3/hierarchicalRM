"""Evidence-complete OuterBot handoff for the single-InnerBot audit.

This is a versioned, prompt-only successor to the v3 single-InnerBot dual-pass
audit.  It leaves the frozen v3 implementation untouched and applies the same
OuterBot handoff contract to Logistics, Blocksworld, and Flat Hanoi.

The handoff exposes only information already visible inside the LLM-only
pipeline: the exact attempted semantic actions, compiler-expanded H0 calls,
public before/after shadow states, and whether this is the final subtask.  It
does not expose an InnerBot verdict or deterministic semantic feedback.
"""

from __future__ import annotations

from dataclasses import replace
import json
from typing import Mapping, Sequence

from shared_nlevel_execution_audit_v3_adapter import (
    SINGLE_INNERBOT_AUDIT_SCHEMA,
    SYSTEM_SINGLE_INNERBOT_AUDIT_ROUTER,
    SingleInnerBotDualPassBlocksworldAdapter,
    SingleInnerBotDualPassFlatHanoiAdapter,
    SingleInnerBotDualPassLexiconAdapter,
    single_innerbot_audit_prompt,
)
from shared_nlevel_pipeline import StageRequest


PIPELINE_VERSION = (
    "shared_nlevel_v5_llm_only_execution_audit_single_innerbot_"
    "dual_pass_outer_trace"
)
SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION = (
    "shared_nlevel_v5_llm_only_execution_audit_v3_1_"
    "single_innerbot_dual_pass_outer_trace"
)
OUTERBOT_TRACE_HANDOFF_REVISION = "shared_outerbot_exact_trace_handoff_v1"


def _safe_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()


class _EvidenceCompleteOuterBotMixin:
    """Add one domain-neutral exact-trace block to every OuterBot request."""

    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = (
        SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION
    )
    outerbot_trace_handoff_revision = OUTERBOT_TRACE_HANDOFF_REVISION
    outerbot_receives_innerbot_verdict = False

    def _outerbot_state_convention(self) -> str:
        domain = (
            str(getattr(self, "name", ""))
            + " "
            + type(self).__name__
        ).lower()
        if "hanoi" in domain:
            return (
                "Peg arrays are bottom-to-top. The final array item is the "
                "only movable top ring. Ring identity is determined by "
                "replaying the listed moves; never infer a different ring."
            )
        if "blocksworld" in domain:
            return (
                "Use the named blocks and the public on/ontable/clear/holding/"
                "handempty facts exactly as shown."
            )
        return (
            "Use the named packages, vehicles, and locations plus the public "
            "at/inside facts exactly as shown."
        )

    def outer_request(
        self,
        task: object,
        decision: object,
        hierarchy: object,
        subtask: object,
        previous_state: object,
        current_state: object,
        is_last: bool,
    ) -> StageRequest:
        request = super().outer_request(
            task,
            decision,
            hierarchy,
            subtask,
            previous_state,
            current_state,
            is_last,
        )
        plan = getattr(subtask, "plan", subtask)
        semantic_actions = [
            {
                "action_index_in_subtask": index,
                "action": self.format_action(action),
            }
            for index, action in enumerate(
                _safe_sequence(getattr(plan, "actions", ())), start=1
            )
        ]
        expanded_h0 = [
            {
                "h0_index_in_subtask": index,
                "call": self.format_call(call),
            }
            for index, call in enumerate(
                _safe_sequence(getattr(plan, "h0_calls", ())), start=1
            )
        ]
        handoff = {
            "handoff_revision": OUTERBOT_TRACE_HANDOFF_REVISION,
            "semantic_verification": "WITHHELD",
            "innerbot_verdict_included": False,
            "subtask_index": int(getattr(plan, "index", 0)),
            "is_final_subtask": bool(is_last),
            "state_convention": self._outerbot_state_convention(),
            "public_state_before": self.snapshot_state(task, previous_state),
            "public_state_after": self.snapshot_state(task, current_state),
            "executed_semantic_actions": semantic_actions,
            "expanded_h0_trace": expanded_h0,
        }
        instructions = """SHARED OUTERBOT EXACT-TRACE HANDOFF
The JSON block below has the same fields in every supported domain. It is an
authoritative record of which actions were attempted and in what order, but it
is not proof that those actions were legal or that their shadow effects are
valid. Independently replay the listed path using the public task rules.

- Judge only the listed path. Do not invent, omit, reorder, or substitute an
  intermediate action.
- Track object identity through every listed action; do not infer identity
  solely from the endpoint snapshots.
- Use `is_final_subtask` explicitly. If it is true, the listed trace is legal,
  all obligations hold, and the resulting public state matches the final goal,
  the required verdict is TASK SUCCESS, never SUBTASK SUCCESS.
- If it is false, do not emit TASK SUCCESS merely because this checkpoint was
  achieved.
- The InnerBot verdict is deliberately absent so this remains a separate
  judgment. Semantic verifier and official-evaluator feedback remain withheld.
"""
        return replace(
            request,
            system=(
                request.system.rstrip()
                + " Use the supplied exact action trace and final-subtask marker; "
                "never infer an unlisted transition."
            ),
            prompt=(
                instructions
                + "\nEXACT-TRACE JSON:\n"
                + json.dumps(handoff, indent=2, sort_keys=True)
                + "\n\nORIGINAL OUTERBOT REVIEW:\n"
                + request.prompt
            ),
        )


class SingleInnerBotDualPassOuterTraceLexiconAdapter(
    _EvidenceCompleteOuterBotMixin, SingleInnerBotDualPassLexiconAdapter
):
    """Logistics v3.1 adapter with the shared exact-trace handoff."""

    verifier_mode = (
        "llm-only-single-innerbot-dual-pass-outer-trace-online; "
        "official-pddl-final-only"
    )


class SingleInnerBotDualPassOuterTraceBlocksworldAdapter(
    _EvidenceCompleteOuterBotMixin, SingleInnerBotDualPassBlocksworldAdapter
):
    """Blocksworld v3.1 adapter with the shared exact-trace handoff."""

    verifier_mode = (
        "llm-only-single-innerbot-dual-pass-outer-trace-online; "
        "official-pddl-final-only"
    )


class SingleInnerBotDualPassOuterTraceFlatHanoiAdapter(
    _EvidenceCompleteOuterBotMixin, SingleInnerBotDualPassFlatHanoiAdapter
):
    """Flat-Hanoi v3.1 adapter with the shared exact-trace handoff."""

    verifier_mode = (
        "llm-only-single-innerbot-dual-pass-outer-trace-online; "
        "official-hanoi-final-only"
    )


__all__ = [
    "OUTERBOT_TRACE_HANDOFF_REVISION",
    "PIPELINE_VERSION",
    "SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION",
    "SINGLE_INNERBOT_AUDIT_SCHEMA",
    "SYSTEM_SINGLE_INNERBOT_AUDIT_ROUTER",
    "SingleInnerBotDualPassOuterTraceBlocksworldAdapter",
    "SingleInnerBotDualPassOuterTraceFlatHanoiAdapter",
    "SingleInnerBotDualPassOuterTraceLexiconAdapter",
    "single_innerbot_audit_prompt",
]
