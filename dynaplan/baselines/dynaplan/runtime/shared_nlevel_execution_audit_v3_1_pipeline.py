"""Pipeline metadata wrapper for the shared OuterBot trace handoff."""

from __future__ import annotations

from dataclasses import replace
from typing import Dict

from shared_nlevel_execution_audit_v3_1_adapter import (
    OUTERBOT_TRACE_HANDOFF_REVISION,
    PIPELINE_VERSION,
    SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION,
    SingleInnerBotDualPassOuterTraceBlocksworldAdapter,
    SingleInnerBotDualPassOuterTraceFlatHanoiAdapter,
    SingleInnerBotDualPassOuterTraceLexiconAdapter,
)
from shared_nlevel_execution_audit_v3_pipeline import (
    run_shared_nlevel_loop as run_v3_loop,
)


_ADAPTER_TYPES = (
    SingleInnerBotDualPassOuterTraceLexiconAdapter,
    SingleInnerBotDualPassOuterTraceBlocksworldAdapter,
    SingleInnerBotDualPassOuterTraceFlatHanoiAdapter,
)


def run_shared_nlevel_loop(*args: object, **kwargs: object):
    adapter = kwargs.get("adapter")
    if adapter is None and len(args) >= 3:
        adapter = args[2]
    if not isinstance(adapter, _ADAPTER_TYPES):
        raise TypeError(
            "single-InnerBot outer-trace audit requires its versioned "
            "domain-specific adapter"
        )

    result = run_v3_loop(*args, **kwargs)
    extra: Dict[str, object] = dict(result.extra_metrics)
    extra.update(
        {
            "shared_pipeline_version": PIPELINE_VERSION,
            "execution_audit_implementation_revision": (
                SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION
            ),
            "outerbot_trace_handoff_revision": (
                OUTERBOT_TRACE_HANDOFF_REVISION
            ),
            "outerbot_receives_exact_semantic_actions": True,
            "outerbot_receives_expanded_h0_trace": True,
            "outerbot_receives_public_before_after_state": True,
            "outerbot_receives_is_final_subtask_marker": True,
            "outerbot_receives_innerbot_verdict": False,
            "outerbot_semantic_verifier_feedback": False,
        }
    )
    return replace(
        result,
        verifier_mode=adapter.verifier_mode,
        extra_metrics=extra,
    )


__all__ = ["PIPELINE_VERSION", "run_shared_nlevel_loop"]
