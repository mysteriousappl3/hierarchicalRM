"""DynaPlan v1.3 compact-generation and exhaustion-fallback adapters.

The registered variant keeps v1.2's success-first, transactional architecture
and adds three independently inspectable switches.  Compact model outputs are
strict JSON on the wire and are deterministically converted back into the
existing tagged representation before any established parser, compiler,
cache, or LLM audit consumes them.  Exhaustion fallback is controller-only and
never receives semantic or official-evaluator feedback during planning.
"""

from __future__ import annotations

from dataclasses import replace

from dynaplan_nlevel_compact_contracts import (
    COMPACT_CONTRACT_REVISION,
    DECISION_KIND_HANOI,
    DECISION_KIND_LEXICON,
    CompactHierarchyVocabulary,
    FunctionSignature,
    configure_compact_stage_request,
    decision_subtask_ids,
    decode_compact_decision,
    decode_compact_hierarchy,
)
from dynaplan_nlevel_checkpoint_normalization import (
    NORMALIZATION_REVISION,
    normalize_decision_checkpoint_closers,
)
from dynaplan_nlevel_localized_repair import (
    LOCALIZED_REPAIR_REVISION,
    decision_suffix_request,
    decision_suffix_spec,
    merge_decision_suffix,
)
from dynaplan_nlevel_exhaustion_fallback import (
    EXHAUSTION_FALLBACK_REVISION,
    ExhaustionCandidatePool,
)
import shared_nlevel_blocksworld as blocksworld_contract
from shared_nlevel_execution_audit_v3_3_adapter import (
    V33SuccessFirstBlocksworldAdapter,
    V33SuccessFirstFlatHanoiAdapter,
    V33SuccessFirstLexiconAdapter,
)
import shared_nlevel_lexicon as logistics_contract
from shared_nlevel_pipeline import ArtifactCheck
from scoring import PRIMITIVES as HANOI_PRIMITIVES, parse_mappings as parse_hanoi_mappings


PIPELINE_VERSION = "dynaplan_v1_3_compact_fallback"
DYNAPLAN_DISPLAY_NAME = "DynaPlan"


class _DynaPlanV12Mixin:
    """Apply safe normalization and one deterministic Decision repair."""

    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = PIPELINE_VERSION
    decision_checkpoint_normalization_revision = NORMALIZATION_REVISION
    # The InnerBot audit is probabilistic.  Its earliest failure coordinates
    # identify a symptom, not a causally safe prefix boundary.  In particular,
    # Hanoi suffixes often require changing an earlier move.  Always perform
    # full regeneration after an InnerBot rejection.
    audit_localized_suffix_repair = False
    audit_localized_suffix_repair_limit = 0
    decision_localized_suffix_repair = True
    decision_localized_suffix_repair_limit = 1
    localized_repair_revision = LOCALIZED_REPAIR_REVISION

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


class _DynaPlanV13Mixin:
    """Opt into the three separately recorded v1.3 changes."""

    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = PIPELINE_VERSION
    compact_generation_contracts = True
    exhaustion_candidate_fallback = True
    lenient_irrelevant_evidence_fields = True
    compact_generation_contract_revision = COMPACT_CONTRACT_REVISION
    exhaustion_candidate_fallback_revision = EXHAUSTION_FALLBACK_REVISION

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The pool defaults off in its own module.  A v1.3 adapter passes its
        # explicit feature flag, making compatibility subclasses deterministic.
        self.exhaustion_candidate_pool = ExhaustionCandidatePool(
            enabled=bool(self.exhaustion_candidate_fallback)
        )

    @property
    def decision_localized_suffix_repair(self):
        # The legacy suffix patch wire format is tagged text.  It remains
        # available when compact contracts are disabled (the exact v1.2 path),
        # while compact mode uses a clean full JSON regeneration after failure.
        return not bool(self.compact_generation_contracts)

    def _compact_decision_kind(self):
        return (
            DECISION_KIND_HANOI
            if self.comparison_domain == "flat-hanoi"
            else DECISION_KIND_LEXICON
        )

    @staticmethod
    def _hanoi_contract_fields(task):
        pegs = tuple(str(value) for value in getattr(task, "pegs", ()))
        rings = tuple(
            str(getattr(value, "name", ""))
            for value in getattr(task, "rings", ())
        )
        return pegs, rings

    def decision_request(self, task, *args, **kwargs):
        request = super().decision_request(task, *args, **kwargs)
        if not self.compact_generation_contracts:
            # Exact v1.2 compatibility: do not even derive a compact schema or
            # task-shaped vocabulary when the independent flag is disabled.
            return request
        pegs, rings = self._hanoi_contract_fields(task)
        return configure_compact_stage_request(
            request,
            enabled=bool(self.compact_generation_contracts),
            decision_kind=self._compact_decision_kind(),
            hanoi_checkpoint_fields=(
                pegs if self.comparison_domain == "flat-hanoi" else ()
            ),
            hanoi_ring_names=(
                rings if self.comparison_domain == "flat-hanoi" else ()
            ),
        )

    def _decode_compact_decision(self, task, output):
        pegs, rings = self._hanoi_contract_fields(task)
        return decode_compact_decision(
            output,
            kind=self._compact_decision_kind(),
            hanoi_checkpoint_fields=(
                pegs if self.comparison_domain == "flat-hanoi" else ()
            ),
            hanoi_ring_names=(
                rings if self.comparison_domain == "flat-hanoi" else ()
            ),
        )

    def parse_decision(self, task, output):
        if not self.compact_generation_contracts:
            return super().parse_decision(task, output)
        decoded = self._decode_compact_decision(task, output)
        if not decoded.valid or decoded.tagged_text is None:
            return ArtifactCheck.rejected(
                *decoded.errors,
                metadata={
                    **dict(decoded.metadata),
                    "compact_generation_contracts": True,
                    "compact_wire_parse_valid": False,
                },
            )
        check = super().parse_decision(task, decoded.tagged_text)
        metadata = dict(check.metadata)
        metadata.update(decoded.metadata)
        metadata.update(
            {
                "compact_generation_contracts": True,
                "compact_wire_parse_valid": True,
                "compact_raw_output_preserved": True,
            }
        )
        if check.valid and check.value is not None:
            self._compact_expected_subtask_ids = decision_subtask_ids(check.value)
        return replace(check, metadata=metadata)

    def canonicalize_decision(self, task, output, check):
        if not self.compact_generation_contracts:
            return super().canonicalize_decision(task, output, check)
        decoded = self._decode_compact_decision(task, output)
        if not decoded.valid or decoded.tagged_text is None:
            raise ValueError(decoded.reason)
        expected_hash = check.metadata.get("raw_sha256")
        if expected_hash != decoded.metadata.get("raw_sha256"):
            raise ValueError("Compact Decision changed between parse and use")
        return super().canonicalize_decision(task, decoded.tagged_text, check)

    def _compact_hierarchy_vocabulary(self, task, h1_output):
        if self.comparison_domain == "logistics":
            module = logistics_contract
            base_functions = {
                h1_name: FunctionSignature.typed(
                    *module.PRIMITIVE_SIGNATURES[primitive_name]
                )
                for h1_name, primitive_name in module._H1_TO_PRIMITIVE.items()
            }
            primitive_arities = module.PRIMITIVE_ARITIES
            object_types = module._object_type_map(task)
            type_parents = module._TYPE_PARENT
        elif self.comparison_domain == "blocksworld":
            module = blocksworld_contract
            base_functions = {
                h1_name: FunctionSignature.typed(
                    *module.PRIMITIVE_SIGNATURES[primitive_name]
                )
                for h1_name, primitive_name in module._H1_TO_PRIMITIVE.items()
            }
            primitive_arities = module.PRIMITIVE_ARITIES
            object_types = module._object_type_map(task)
            type_parents = module._TYPE_PARENT
        elif self.comparison_domain == "flat-hanoi":
            mappings, errors = parse_hanoi_mappings(h1_output)
            if errors or not mappings:
                raise ValueError(
                    "Validated Hanoi H1 could not form compact vocabulary: "
                    + "; ".join(errors or ["no mappings"])
                )
            base_functions = {
                name: FunctionSignature.typed(
                    *("peg" for _ in mapping.params)
                )
                for name, mapping in mappings.items()
            }
            primitive_arities = {
                name: (1 if name == "MoveCoroutine" else 0)
                for name in HANOI_PRIMITIVES
            }
            object_types = {
                **{str(peg): "peg" for peg in getattr(task, "pegs", ())},
                **{
                    str(getattr(ring, "name", "")): "ring"
                    for ring in getattr(task, "rings", ())
                },
            }
            type_parents = {"peg": "object", "ring": "object"}
        else:
            raise ValueError(
                f"Unsupported compact-contract domain {self.comparison_domain!r}"
            )
        return CompactHierarchyVocabulary(
            base_functions=base_functions,
            primitive_arities=primitive_arities,
            object_types=object_types,
            type_parents=type_parents,
            allow_grounded_mapping_arguments=(
                self.comparison_domain == "flat-hanoi"
            ),
        )

    def hierarchy_request(
        self,
        task,
        state,
        scene,
        state_output,
        h1_output,
        decision_output,
        feedback,
        include_code_block,
    ):
        request = super().hierarchy_request(
            task,
            state,
            scene,
            state_output,
            h1_output,
            decision_output,
            feedback,
            include_code_block,
        )
        if not self.compact_generation_contracts:
            # Avoid eager compact-vocabulary parsing in the flags-off path.
            return request
        return configure_compact_stage_request(
            request,
            enabled=bool(self.compact_generation_contracts),
            hierarchy_vocabulary=self._compact_hierarchy_vocabulary(
                task, h1_output
            ),
            expected_subtask_ids=getattr(
                self, "_compact_expected_subtask_ids", ()
            ),
        )

    def canonicalize_hierarchy(
        self,
        task,
        state,
        h1_output,
        decision_output,
        decision,
        output,
    ):
        del state, decision_output
        if not self.compact_generation_contracts:
            return ArtifactCheck.accepted(output)
        decoded = decode_compact_hierarchy(
            output,
            vocabulary=self._compact_hierarchy_vocabulary(task, h1_output),
            expected_subtask_ids=decision_subtask_ids(decision),
        )
        if not decoded.valid or decoded.tagged_text is None:
            return ArtifactCheck.rejected(
                *decoded.errors,
                metadata={
                    **dict(decoded.metadata),
                    "compact_generation_contracts": True,
                    "compact_wire_parse_valid": False,
                },
            )
        return ArtifactCheck.accepted(
            decoded.tagged_text,
            metadata={
                **dict(decoded.metadata),
                "compact_generation_contracts": True,
                "compact_wire_parse_valid": True,
                "compact_raw_output_preserved": True,
            },
        )


class DynaPlanLexiconAdapter(
    _DynaPlanV13Mixin,
    _DynaPlanV12Mixin,
    V33SuccessFirstLexiconAdapter,
):
    pass


class DynaPlanBlocksworldAdapter(
    _DynaPlanV13Mixin,
    _DynaPlanV12Mixin,
    V33SuccessFirstBlocksworldAdapter,
):
    pass


class DynaPlanFlatHanoiAdapter(
    _DynaPlanV13Mixin,
    _DynaPlanV12Mixin,
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
