"""DynaPlan N-level telemetry wrapper over the frozen v3.3 architecture."""

from __future__ import annotations

from dataclasses import replace

from dynaplan_nlevel_adapter import (
    PIPELINE_VERSION,
    DynaPlanBlocksworldAdapter,
    DynaPlanFlatHanoiAdapter,
    DynaPlanLexiconAdapter,
)
from dynaplan_nlevel_checkpoint_normalization import NORMALIZATION_REVISION
from shared_nlevel_execution_audit_v3_3_pipeline import (
    run_shared_nlevel_loop as run_v33,
)


_DYNAPLAN_ADAPTERS = (
    DynaPlanBlocksworldAdapter,
    DynaPlanFlatHanoiAdapter,
    DynaPlanLexiconAdapter,
)


def _decision_normalization_records(result):
    for attempt_index, attempt in enumerate(result.attempts):
        validation = attempt.get("decision_validation", {})
        metadata = validation.get("metadata", {})
        count = metadata.get("decision_checkpoint_tag_repair_count", 0)
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            continue
        yield {
            "attempt_index": attempt_index,
            "repair_count": count,
            "repaired_ids": list(
                metadata.get("decision_checkpoint_tag_repaired_ids", [])
            ),
            "decision_valid_after_normalization": bool(validation.get("valid")),
            "raw_sha256": metadata.get("decision_raw_sha256"),
            "normalized_sha256": metadata.get("decision_normalized_sha256"),
            "raw_output_preserved": (
                "decision_raw_output" in attempt.get("stage_outputs", {})
            ),
        }


def run_shared_nlevel_loop(*args, **kwargs):
    adapter = kwargs.get("adapter") if "adapter" in kwargs else args[2]
    if not isinstance(adapter, _DYNAPLAN_ADAPTERS):
        raise TypeError("DynaPlan requires a versioned DynaPlan adapter")

    result = run_v33(*args, **kwargs)
    normalization_records = list(_decision_normalization_records(result))
    extra = dict(result.extra_metrics)
    extra.update(
        {
            "shared_pipeline_version": PIPELINE_VERSION,
            "execution_audit_implementation_revision": PIPELINE_VERSION,
            "framework_name": "DynaPlan",
            "decision_checkpoint_tag_normalization": True,
            "decision_checkpoint_tag_normalization_revision": (
                NORMALIZATION_REVISION
            ),
            "decision_checkpoint_tag_normalized_attempt_count": len(
                normalization_records
            ),
            "decision_checkpoint_tag_repair_count": sum(
                record["repair_count"] for record in normalization_records
            ),
            "decision_checkpoint_tag_normalization_records": (
                normalization_records
            ),
            "decision_checkpoint_body_semantics_changed": False,
        }
    )
    return replace(result, extra_metrics=extra)


__all__ = ["run_shared_nlevel_loop"]
