"""DynaPlan final N-level hierarchy adapters.

DynaPlan currently means the complete v3.3 success-first architecture plus a
strictly syntax-only Decision normalizer and audit-guided transactional suffix
repair.  Audit localization is explicitly non-authoritative; every repaired
candidate is rechecked in full from the frozen initial state.
"""

from __future__ import annotations

from dataclasses import replace

from dynaplan_nlevel_checkpoint_normalization import (
    NORMALIZATION_REVISION,
    normalize_decision_checkpoint_closers,
)
from dynaplan_nlevel_localized_repair import (
    LOCALIZED_REPAIR_REVISION,
    audit_localization,
    decision_suffix_request,
    decision_suffix_spec,
    merge_decision_suffix,
)
from shared_nlevel_execution_audit_v3_3_adapter import (
    V33SuccessFirstBlocksworldAdapter,
    V33SuccessFirstFlatHanoiAdapter,
    V33SuccessFirstLexiconAdapter,
)


PIPELINE_VERSION = "dynaplan_final_nlevel_hierarchy_v1_1"
DYNAPLAN_DISPLAY_NAME = "DynaPlan"


class _DynaPlanV11Mixin:
    """Apply the syntax-safe normalizer and localized-repair hooks."""

    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = PIPELINE_VERSION
    decision_checkpoint_normalization_revision = NORMALIZATION_REVISION
    audit_localized_suffix_repair = True
    audit_localized_suffix_repair_limit = 2
    decision_localized_suffix_repair = True
    decision_localized_suffix_repair_limit = 2
    localized_repair_revision = LOCALIZED_REPAIR_REVISION

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dynaplan_last_audit_localization = None

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

    def parse_router(self, output):
        verdict = super().parse_router(output)
        self._dynaplan_last_audit_localization = None
        records = getattr(self, "single_innerbot_audit_records", ())
        if records:
            self._dynaplan_last_audit_localization = audit_localization(
                records[-1], verdict.owner
            )
        return verdict

    def last_audit_localization(self):
        value = self._dynaplan_last_audit_localization
        return dict(value) if value is not None else None

    def decision_suffix_repair_spec(self, candidate_output, errors):
        return decision_suffix_spec(candidate_output, errors)

    def decision_suffix_repair_request(
        self,
        base_request,
        candidate_output,
        certificate,
        preserved_subtask_indices,
        repair_subtask_indices,
    ):
        return decision_suffix_request(
            base_request,
            candidate_output=candidate_output,
            certificate=certificate,
            preserved_subtask_indices=preserved_subtask_indices,
            repair_subtask_indices=repair_subtask_indices,
        )

    def merge_decision_suffix_repair(
        self,
        candidate_output,
        patch_output,
        preserved_subtask_indices,
        repair_subtask_indices,
    ):
        return merge_decision_suffix(
            candidate_output,
            patch_output,
            preserved_subtask_indices,
            repair_subtask_indices,
        )

    def hierarchy_repair_request(self, *args, **kwargs):
        request = super().hierarchy_repair_request(*args, **kwargs)
        certificate = kwargs.get("certificate")
        if certificate is None and len(args) >= 8:
            certificate = args[7]
        if not isinstance(certificate, dict) or certificate.get(
            "certificate_source"
        ) != "llm_execution_audit":
            return request
        prompt = request.prompt
        for old in (
            "PROMPT-INDUCED JSON-RULE FAILURE CERTIFICATE",
            "PUBLIC DETERMINISTIC FAILURE CERTIFICATE",
            "DETERMINISTIC FAILURE CERTIFICATE",
        ):
            prompt = prompt.replace(
                old,
                "LLM AUDIT LOCALIZATION CERTIFICATE "
                "(SEMANTIC VERIFICATION WITHHELD)",
            )
        prompt = prompt.replace(
            "Earlier checkpoint-valid blocks", "Earlier audit-cleared blocks"
        ).replace(
            "Earlier deterministic-transition-valid blocks",
            "Earlier audit-cleared blocks",
        )
        prompt += (
            "\n\nThe preserved prefix is not semantically certified. Repair only "
            "the requested suffix; the controller will re-audit the complete "
            "merged candidate from its frozen starting state before any commit."
        )
        request = replace(
            request,
            system=(
                "HierarchyPlanner audit-localized suffix repair: the LLM "
                "localization is advisory and semantic verification is withheld."
            ),
            prompt=prompt,
        )
        return self._with_public_rules(request)


class DynaPlanLexiconAdapter(
    _DynaPlanV11Mixin,
    V33SuccessFirstLexiconAdapter,
):
    pass


class DynaPlanBlocksworldAdapter(
    _DynaPlanV11Mixin,
    V33SuccessFirstBlocksworldAdapter,
):
    pass


class DynaPlanFlatHanoiAdapter(
    _DynaPlanV11Mixin,
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
