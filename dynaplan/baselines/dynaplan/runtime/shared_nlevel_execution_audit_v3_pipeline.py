"""Shared loop wrapper for the single-InnerBot dual-pass audit variant."""

from __future__ import annotations

from dataclasses import replace
from typing import Dict

from shared_nlevel_execution_audit_v3_adapter import (
    PIPELINE_VERSION,
    SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION,
    SingleInnerBotDualPassBlocksworldAdapter,
    SingleInnerBotDualPassFlatHanoiAdapter,
    SingleInnerBotDualPassLexiconAdapter,
)
from shared_nlevel_llm_only_pipeline import run_shared_nlevel_loop as run_llm_only


_ADAPTER_TYPES = (
    SingleInnerBotDualPassLexiconAdapter,
    SingleInnerBotDualPassBlocksworldAdapter,
    SingleInnerBotDualPassFlatHanoiAdapter,
)


def run_shared_nlevel_loop(*args: object, **kwargs: object):
    adapter = kwargs.get("adapter")
    if adapter is None and len(args) >= 3:
        adapter = args[2]
    if not isinstance(adapter, _ADAPTER_TYPES):
        raise TypeError(
            "single-InnerBot dual-pass execution audit requires its "
            "domain-specific adapter"
        )

    result = run_llm_only(*args, **kwargs)
    if adapter.official_final_evaluator_call_count != 1:
        raise RuntimeError(
            "single-InnerBot audit must invoke the official evaluator "
            "exactly once"
        )

    records = list(adapter.single_innerbot_audit_records)
    extra: Dict[str, object] = dict(result.extra_metrics)
    calls_by_stage = extra.get("model_calls_by_stage", {})
    router_call_count = int(
        calls_by_stage.get("innerbot_router", 0)
        if isinstance(calls_by_stage, dict)
        else 0
    )
    extra.update(
        {
            "shared_pipeline_version": PIPELINE_VERSION,
            "execution_audit_implementation_revision": (
                SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION
            ),
            "innerbot_audit_mode": (
                "single-call-forward-simulation-plus-backward-support"
            ),
            "single_innerbot_role_count": 1,
            "primary_audit_calls_per_candidate": 1,
            "post_outer_recheck_uses_same_innerbot": True,
            "independent_challenge_call_count": 0,
            "innerbot_receives_composed_hierarchy": True,
            "innerbot_receives_expanded_execution_actions": True,
            "innerbot_receives_semantic_verifier_results": False,
            "execution_boundary_level": "H0",
            "execution_audit_router_call_count": router_call_count,
            "execution_audit_parsed_record_count": len(records),
            "execution_audit_parse_failure_count": sum(
                record.get("parse_valid") is not True for record in records
            ),
            "execution_audit_coverage_guard_failure_count": sum(
                record.get("coverage_guard_passed") is not True
                for record in records
            ),
            "execution_audit_effective_rejection_count": sum(
                record.get("effective_verdict") == "INVALID"
                for record in records
            ),
            "execution_audit_records": records,
            "compiled_pddl_available_online": False,
            "online_semantic_verifier": "none",
            "official_final_evaluator_call_count": (
                adapter.official_final_evaluator_call_count
            ),
        }
    )
    return replace(
        result,
        verifier_mode=adapter.verifier_mode,
        extra_metrics=extra,
    )


__all__ = ["PIPELINE_VERSION", "run_shared_nlevel_loop"]
