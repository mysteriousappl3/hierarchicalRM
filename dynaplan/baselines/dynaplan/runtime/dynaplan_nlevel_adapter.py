"""DynaPlan final N-level hierarchy adapters.

DynaPlan currently means the complete v3.3 success-first architecture plus a
strictly syntax-only, domain-neutral Decision checkpoint closer normalizer.
"""

from __future__ import annotations

from dataclasses import replace

from dynaplan_nlevel_checkpoint_normalization import (
    NORMALIZATION_REVISION,
    normalize_decision_checkpoint_closers,
)
from shared_nlevel_execution_audit_v3_3_adapter import (
    V33SuccessFirstBlocksworldAdapter,
    V33SuccessFirstFlatHanoiAdapter,
    V33SuccessFirstLexiconAdapter,
)


PIPELINE_VERSION = "dynaplan_final_nlevel_hierarchy_v1"
DYNAPLAN_DISPLAY_NAME = "DynaPlan"


class _DynaPlanDecisionNormalizationMixin:
    """Parse a safely normalized copy and preserve normal validation."""

    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = PIPELINE_VERSION
    decision_checkpoint_normalization_revision = NORMALIZATION_REVISION

    def parse_decision(self, task, output):
        normalization = normalize_decision_checkpoint_closers(output)
        check = super().parse_decision(task, normalization.normalized_output)
        metadata = dict(check.metadata)
        metadata.update(
            {
                "decision_checkpoint_tag_normalization_revision": (
                    NORMALIZATION_REVISION
                ),
                "decision_checkpoint_tag_normalized": normalization.changed,
                "decision_checkpoint_tag_repair_count": (
                    normalization.repair_count
                ),
                "decision_checkpoint_tag_repaired_ids": list(
                    normalization.repaired_ids
                ),
                "decision_raw_sha256": normalization.raw_sha256,
                "decision_normalized_sha256": normalization.normalized_sha256,
                "decision_body_semantics_changed": False,
            }
        )
        return replace(check, metadata=metadata)

    def canonicalize_decision(self, task, output, check):
        del task
        normalization = normalize_decision_checkpoint_closers(output)
        expected_hash = check.metadata.get("decision_normalized_sha256")
        if expected_hash != normalization.normalized_sha256:
            raise ValueError("Decision normalization changed between parse and use")
        return normalization.normalized_output


class DynaPlanLexiconAdapter(
    _DynaPlanDecisionNormalizationMixin,
    V33SuccessFirstLexiconAdapter,
):
    pass


class DynaPlanBlocksworldAdapter(
    _DynaPlanDecisionNormalizationMixin,
    V33SuccessFirstBlocksworldAdapter,
):
    pass


class DynaPlanFlatHanoiAdapter(
    _DynaPlanDecisionNormalizationMixin,
    V33SuccessFirstFlatHanoiAdapter,
):
    pass


__all__ = [
    "DYNAPLAN_DISPLAY_NAME",
    "DynaPlanBlocksworldAdapter",
    "DynaPlanFlatHanoiAdapter",
    "DynaPlanLexiconAdapter",
    "PIPELINE_VERSION",
]
