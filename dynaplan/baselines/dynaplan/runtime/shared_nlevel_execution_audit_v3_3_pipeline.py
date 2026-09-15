"""Versioned telemetry wrapper; same single InnerBot and final-only evaluator."""

from dataclasses import replace

from shared_nlevel_execution_audit_v3_1_pipeline import run_shared_nlevel_loop as run_v31
from shared_nlevel_execution_audit_v3_3_adapter import (
    PIPELINE_VERSION,
    V33SuccessFirstBlocksworldAdapter,
    V33SuccessFirstFlatHanoiAdapter,
    V33SuccessFirstLexiconAdapter,
)


def run_shared_nlevel_loop(*args, **kwargs):
    adapter = kwargs.get("adapter") if "adapter" in kwargs else args[2]
    if not isinstance(adapter, (V33SuccessFirstBlocksworldAdapter,
                                V33SuccessFirstFlatHanoiAdapter,
                                V33SuccessFirstLexiconAdapter)):
        raise TypeError("v3.3 requires a versioned success-first adapter")
    result = run_v31(*args, **kwargs)
    extra = dict(result.extra_metrics)
    extra.update({
        "shared_pipeline_version": PIPELINE_VERSION,
        "execution_audit_implementation_revision": PIPELINE_VERSION,
        "success_first_checkpoint_review": True,
        "explicit_public_action_effects": True,
        "structured_requirement_evidence_required": True,
        "full_candidate_recheck_uses_frozen_start": True,
        "checkpoint_noop_extension": False,
        "requirement_evidence_guard_failure_count": sum(
            record.get("requirement_evidence_guard_passed") is False
            for record in adapter.single_innerbot_audit_records
        ),
    })
    return replace(result, extra_metrics=extra)
