"""Thin, auditable v5 wrapper for the no-online-semantic-verifier ablation."""

from __future__ import annotations

from dataclasses import replace
from typing import Dict

from shared_nlevel_verified_repair_pipeline import run_shared_nlevel_loop as run_v5
from shared_nlevel_verifier_ablation_adapters import (
    LLM_ONLY_PIPELINE_VERSION,
    LLMOnlyLexiconAdapter,
)


PIPELINE_VERSION = LLM_ONLY_PIPELINE_VERSION


def run_shared_nlevel_loop(*args: object, **kwargs: object):
    adapter = kwargs.get("adapter")
    if adapter is None and len(args) >= 3:
        adapter = args[2]
    if not isinstance(adapter, LLMOnlyLexiconAdapter) and not bool(
        getattr(adapter, "llm_only_online", False)
    ):
        raise TypeError("v5-LLM-only requires an LLM-only domain adapter")
    result = run_v5(*args, **kwargs)
    if adapter.official_final_evaluator_call_count != 1:
        raise RuntimeError("v5-LLM-only must invoke the official evaluator exactly once")
    extra: Dict[str, object] = dict(result.extra_metrics)
    extra.update(
        {
            "shared_pipeline_version": PIPELINE_VERSION,
            "verified_prefix_repair": False,
            "transactional_syntax_prefix_preservation": True,
            "repair_boundary": "llm-attributed-unverified-subtask",
            "deterministic_projection_authoritative": False,
            "online_verification_feedback": False,
            "online_semantic_verifier": "none",
            "shadow_state_kind": "non-rejecting-public-effect-reducer",
            "shadow_state_authoritative": False,
            "compiled_pddl_available_online": False,
            "shortest_valid_incumbent_retained": False,
            "official_final_evaluator_call_count": adapter.official_final_evaluator_call_count,
        }
    )
    return replace(
        result,
        verifier_mode=adapter.verifier_mode,
        extra_metrics=extra,
    )


__all__ = ["PIPELINE_VERSION", "run_shared_nlevel_loop"]
