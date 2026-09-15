"""LexiCon adapter for persistent, failure-localized N-level repair.

This v4 adapter leaves the registered v2/v3 implementations untouched.  It
adds three controller contracts on top of the v3 validated-artifact cache:

* an explicit ``CheckpointNoOp()`` for checkpoints already true at entry;
* transactional retention of checkpoint-validated hierarchy subtask blocks;
* deterministic-validity authority over advisory Router/OuterBot verdicts.

The adapter never plans with an oracle or a classical solver.  It uses the
same domain transition/checkpoint hooks as the shared N-level architecture.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import shared_nlevel_lexicon as lexicon
import shared_nlevel_pipeline as shared
from shared_nlevel_lexicon_prompts import SYSTEM_HIERARCHY
from shared_nlevel_pipeline import (
    ArtifactCheck,
    CompiledHierarchy,
    FinalScoreContext,
    OuterVerdict,
    PlannedSubtask,
    ProjectionResult,
    RouterVerdict,
    SharedLoopResult,
    StageRequest,
)
from shared_nlevel_selective_lexicon import SelectiveLexiconNLevelAdapter


PIPELINE_VERSION = "shared_nlevel_v4_prefix_repair"
CHECKPOINT_NOOP = "CheckpointNoOp()"
SYSTEM_HIERARCHY_PATCH = (
    "InnerBot localized repair controller: patch only the failed LexiCon "
    "hierarchy subtask and its suffix."
)
_NOOP_CALL_RE = re.compile(r"(?<![A-Za-z0-9_])CheckpointNoOp\s*\(")
_PRIVATE_MONITOR_INDEX_RE = re.compile(
    r"(?:hold_|seen_(?:psi_)?)(?P<index>\d+)"
)


@dataclass(frozen=True)
class _HierarchyCandidate:
    """One structurally compiled hierarchy kept transactionally for repair."""

    serial: int
    state_key: str
    h1_output: str
    decision_output: str
    decision: object
    output: str
    hierarchy: CompiledHierarchy


@dataclass(frozen=True)
class _ValidIncumbent:
    """The shortest complete candidate accepted by deterministic projection."""

    state_output: object
    h1_output: str
    decision_output: str
    hierarchy_output: str
    hierarchy: CompiledHierarchy
    projection: ProjectionResult
    # A projection can start after an earlier execution/replan cycle.  Keep the
    # authoritative complete prefix carried by the LexiCon state, rather than
    # reconstructing a plan later from only this candidate's suffix hierarchy.
    full_actions: Tuple[object, ...]


def _state_key(adapter: object, task: object, state: object) -> str:
    digest = getattr(state, "digest", None)
    if isinstance(digest, str) and digest:
        return digest
    snapshot = adapter.snapshot_state(task, state)
    return json.dumps(snapshot, sort_keys=True, default=str)


def _block_matches(text: str) -> List[re.Match[str]]:
    return list(lexicon._SUBTASK_CALLS_RE.finditer(text or ""))


def _mapping_block(text: str) -> Optional[str]:
    matches = list(lexicon._MAPPING_BLOCK_RE.finditer(text or ""))
    if len(matches) != 1:
        return None
    return matches[0].group(0).strip()


def _render_call_block(index: int, body: str) -> str:
    return (
        f"```start_subtask_funcs_{index}\n"
        f"{body.strip()}\n"
        f"```end_subtask_funcs_{index}"
    )


def _strip_spans(text: str, spans: Sequence[Tuple[int, int]]) -> str:
    pieces: List[str] = []
    cursor = 0
    for start, end in sorted(spans):
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _public_temporal_failures(
    task: object, diagnostic_values: object
) -> List[Dict[str, object]]:
    """Map private compiler-monitor references to released constraint text."""

    if not isinstance(diagnostic_values, Sequence) or isinstance(
        diagnostic_values, (str, bytes, bytearray)
    ):
        return []
    constraints = getattr(task, "constraints", ())
    if not isinstance(constraints, Sequence) or isinstance(
        constraints, (str, bytes, bytearray)
    ):
        return []
    indices = {
        int(match.group("index"))
        for value in diagnostic_values
        for match in _PRIVATE_MONITOR_INDEX_RE.finditer(str(value))
    }
    return [
        {
            "index": index + 1,
            "constraint": lexicon._model_safe_evaluator_text(
                str(constraints[index])
            ),
        }
        for index in sorted(indices)
        if 0 <= index < len(constraints)
    ]


class PrefixRepairLexiconNLevelAdapter(SelectiveLexiconNLevelAdapter):
    """Stateful v4 adapter with verified no-ops and hierarchy suffix patches."""

    pipeline_version = PIPELINE_VERSION
    state_descriptor_validation_authoritative = True
    checkpoint_backtrack_after = 2

    def __init__(self) -> None:
        super().__init__()
        self._candidate: Optional[_HierarchyCandidate] = None
        self._candidate_serial = 0
        self._active_task: Optional[object] = None
        self._active_state_key: Optional[str] = None
        self._repair_context_key: Optional[Tuple[object, ...]] = None
        self._last_analyzed_serial = -1
        self._last_failure_signature: Optional[Tuple[object, ...]] = None
        self._same_failure_count = 0
        self._pending_patch: Optional[Dict[str, object]] = None
        self._render_history: List[Dict[str, object]] = []
        self._valid_incumbent: Optional[_ValidIncumbent] = None
        self._restored_incumbent: Optional[_ValidIncumbent] = None
        self._router_projection_valid = False
        self._outer_expected_status: Optional[str] = None
        self._checkpoint_route_signature: Optional[Tuple[object, ...]] = None
        self._checkpoint_route_count = 0
        self._checkpoint_route_serials: set[int] = set()
        self._decision_escalation_evidence: Optional[Dict[str, object]] = None
        self._decision_escalation_state_key: Optional[str] = None
        self._telemetry: Dict[str, object] = {
            "checkpoint_noop_compile_count": 0,
            "localized_patch_request_count": 0,
            "localized_patch_accept_count": 0,
            "localized_patch_reject_count": 0,
            "preserved_subtask_count_total": 0,
            "backtrack_count": 0,
            "checkpoint_local_repair_count": 0,
            "checkpoint_decision_escalation_count": 0,
            "decision_escalation_certificate_count": 0,
            "failure_certificates": [],
            "router_validity_override_count": 0,
            "outerbot_validity_override_count": 0,
            "valid_incumbent_count": 0,
            "valid_incumbent_update_count": 0,
            "valid_incumbent_restored": False,
            "repair_context_reset_count": 0,
        }

    # ------------------------------------------------------------------
    # Verified no-op compilation
    # ------------------------------------------------------------------
    def _compile_with_noops(
        self,
        task: object,
        h1_output: str,
        decision: object,
        hierarchy_output: str,
    ) -> ArtifactCheck:
        if not isinstance(decision, lexicon.LexiconDecisionPlan):
            return ArtifactCheck.rejected(
                "Hierarchy received an invalid Decision artifact"
            )

        matches = _block_matches(hierarchy_output)
        noop_ids: List[int] = []
        noop_spans: List[Tuple[int, int]] = []
        errors: List[str] = []
        block_ids: List[int] = []
        for match in matches:
            index = int(match.group("index"))
            block_ids.append(index)
            body = match.group("body").strip()
            if body == CHECKPOINT_NOOP:
                noop_ids.append(index)
                noop_spans.append(match.span())
            elif _NOOP_CALL_RE.search(body):
                errors.append(
                    f"Hierarchy subtask {index}: {CHECKPOINT_NOOP} must be the "
                    "sole exact block body"
                )

        expected_ids = [subtask.index for subtask in decision.subtasks]
        if block_ids != expected_ids:
            errors.append(
                f"Hierarchy call blocks must be exactly {expected_ids} in order; "
                f"got {block_ids}"
            )
        if len(_NOOP_CALL_RE.findall(hierarchy_output or "")) != len(noop_ids):
            errors.append(
                f"{CHECKPOINT_NOOP} may appear only as the sole body of a "
                "numbered subtask block"
            )
        if errors:
            return ArtifactCheck.rejected(*errors)

        if not noop_ids:
            return lexicon._compile_hierarchy(
                task, h1_output, decision, hierarchy_output
            )

        noop_set = set(noop_ids)
        filtered_decision = lexicon.LexiconDecisionPlan(
            tuple(
                subtask
                for subtask in decision.subtasks
                if subtask.index not in noop_set
            )
        )
        filtered_output = _strip_spans(hierarchy_output, noop_spans)
        base_check = lexicon._compile_hierarchy(
            task, h1_output, filtered_decision, filtered_output
        )
        if not base_check.valid or not isinstance(
            base_check.value, CompiledHierarchy
        ):
            return base_check

        compiled = base_check.value
        compiled_by_id = {subtask.index: subtask for subtask in compiled.subtasks}
        decision_by_id = decision.by_index()
        rebuilt: List[PlannedSubtask] = []
        for index in expected_ids:
            if index not in noop_set:
                rebuilt.append(compiled_by_id[index])
                continue
            decision_subtask = decision_by_id[index]
            rebuilt.append(
                PlannedSubtask(
                    index=index,
                    description=decision_subtask.description,
                    top_level_calls=(),
                    h0_calls=(),
                    actions=(),
                    level_counts={},
                    metadata={
                        "checkpoint": decision_subtask.checkpoint.to_dict(),
                        "checkpoint_noop": True,
                    },
                )
            )

        top_level_count = sum(len(item.top_level_calls) for item in rebuilt)
        expanded_count = sum(len(item.actions) for item in rebuilt)
        stats_metadata = dict(compiled.stats.metadata)
        stats_metadata.update(
            {
                "top_level_call_count": top_level_count,
                "expanded_action_count": expanded_count,
                "checkpoint_noop_subtasks": list(noop_ids),
                "compression_ratio": (
                    round(expanded_count / top_level_count, 6)
                    if top_level_count
                    else None
                ),
            }
        )
        stats = replace(compiled.stats, metadata=stats_metadata)
        metadata = dict(compiled.metadata)
        metadata["checkpoint_noop_subtasks"] = tuple(noop_ids)
        rebuilt_hierarchy = replace(
            compiled,
            subtasks=tuple(rebuilt),
            stats=stats,
            metadata=metadata,
        )
        self._telemetry["checkpoint_noop_compile_count"] = int(
            self._telemetry["checkpoint_noop_compile_count"]
        ) + len(noop_ids)
        return ArtifactCheck.accepted(
            rebuilt_hierarchy,
            metadata={
                **dict(base_check.metadata),
                "top_level_call_count": top_level_count,
                "expanded_action_count": expanded_count,
                "checkpoint_noop_subtasks": list(noop_ids),
            },
        )

    def validate_projected_subtask(
        self,
        task: object,
        decision: object,
        subtask: PlannedSubtask,
        projected_state: object,
        is_last: bool,
    ) -> ArtifactCheck:
        check = super().validate_projected_subtask(
            task, decision, subtask, projected_state, is_last
        )
        metadata = dict(check.metadata)
        if is_last and not check.valid:
            # The base adapter intentionally redacts compiler predicate names.
            # Preserve that boundary while translating their zero-based suffix
            # only into the corresponding one-based, already-public constraint.
            verification = lexicon.verify_plan(
                task, getattr(projected_state, "executed_actions", ())
            )
            violated_temporal = _public_temporal_failures(
                task, verification.unsatisfied_constraint_goals
            )
            if violated_temporal:
                metadata["violated_temporal_constraints"] = violated_temporal
        if not bool(subtask.metadata.get("checkpoint_noop")):
            return replace(check, metadata=metadata)
        metadata.update(
            {
                "checkpoint_noop": True,
                "checkpoint_noop_verified_at_unchanged_state": check.valid,
                "state_digest": getattr(projected_state, "digest", None),
                # These remain evaluator evidence and are not inserted into a
                # later model prompt by the shared projection serializer.
                "compiler_monitor_facts": list(
                    getattr(projected_state, "monitor_facts", ())
                ),
            }
        )
        if check.valid:
            return ArtifactCheck.accepted(check.value, metadata=metadata)
        return ArtifactCheck.rejected(
            "CheckpointNoOp rejected: the unchanged state does not satisfy "
            "the checkpoint and/or final temporal obligations",
            *check.errors,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Persistent hierarchy blocks and localized suffix repair
    # ------------------------------------------------------------------
    def _candidate_compatible(
        self,
        task: object,
        state: object,
        h1_output: str,
        decision_output: str,
    ) -> bool:
        candidate = self._candidate
        return bool(
            candidate is not None
            and candidate.state_key == _state_key(self, task, state)
            and candidate.h1_output == h1_output
            and candidate.decision_output == decision_output
        )

    def _failure_signature(self, projection: ProjectionResult) -> Tuple[object, ...]:
        failed_action = projection.failed_action
        action_text = (
            self.format_action(failed_action)
            if failed_action is not None
            else None
        )
        return (
            projection.failed_subtask_index,
            projection.failed_action_index,
            action_text,
            bool(
                projection.checkpoint_failure
                or projection.metadata.get("original_checkpoint_failure")
            ),
            projection.reason,
        )

    def _activate_repair_context(
        self,
        task: object,
        state: object,
        h1_output: str,
        decision: object,
    ) -> None:
        """Reset repetition counters after a semantic planning-context change."""

        state_key = _state_key(self, task, state)
        context_key = (state_key, h1_output, decision)
        self._active_task = task
        self._active_state_key = state_key
        if context_key == self._repair_context_key:
            return
        if self._repair_context_key is not None:
            self._telemetry["repair_context_reset_count"] = int(
                self._telemetry["repair_context_reset_count"]
            ) + 1
        self._repair_context_key = context_key
        self._last_analyzed_serial = -1
        self._last_failure_signature = None
        self._same_failure_count = 0
        self._checkpoint_route_signature = None
        self._checkpoint_route_count = 0
        self._checkpoint_route_serials.clear()
        self._decision_escalation_evidence = None
        self._decision_escalation_state_key = None

    def route_projection_failure(
        self, projection: ProjectionResult
    ) -> ProjectionResult:
        """Try checkpoint failures locally twice before invalidating Decision.

        The v3 controller treats ``checkpoint_failure=True`` as joint
        Decision/Hierarchy ownership.  V4 first makes the hierarchy suffix
        prove or disprove the checkpoint, then escalates after two distinct
        compiled candidates fail at the same boundary.  Candidate serials
        prevent the controller's diagnostic re-projection from double-counting.
        """

        if not projection.checkpoint_failure or self._candidate is None:
            return projection
        signature = (
            projection.failed_subtask_index,
            projection.reason,
        )
        serial = self._candidate.serial
        new_candidate = serial not in self._checkpoint_route_serials
        if new_candidate:
            self._checkpoint_route_serials.add(serial)
            if signature == self._checkpoint_route_signature:
                self._checkpoint_route_count += 1
            else:
                self._checkpoint_route_signature = signature
                self._checkpoint_route_count = 1
        metadata = dict(projection.metadata)
        if self._active_task is not None:
            violated_temporal = _public_temporal_failures(
                self._active_task,
                metadata.get("unsatisfied_conditions", []),
            )
            if violated_temporal:
                metadata["violated_temporal_constraints"] = violated_temporal
        metadata["original_checkpoint_failure"] = True
        metadata["checkpoint_local_attempt"] = self._checkpoint_route_count
        if self._checkpoint_route_count <= 2:
            if new_candidate:
                self._telemetry["checkpoint_local_repair_count"] = int(
                    self._telemetry["checkpoint_local_repair_count"]
                ) + 1
            return replace(
                projection,
                checkpoint_failure=False,
                metadata=metadata,
            )
        if new_candidate:
            self._telemetry["checkpoint_decision_escalation_count"] = int(
                self._telemetry["checkpoint_decision_escalation_count"]
            ) + 1
            def safe_values(value: object) -> List[str]:
                if not isinstance(value, Sequence) or isinstance(
                    value, (str, bytes, bytearray)
                ):
                    return []
                return [
                    lexicon._model_safe_evaluator_text(str(item))
                    for item in value
                ]

            safe_missing = safe_values(
                metadata.get("missing_required_true", [])
            )
            safe_present = safe_values(
                metadata.get("present_required_false", [])
            )
            evidence: Dict[str, object] = {
                "failed_subtask_index": projection.failed_subtask_index,
                "reason": lexicon._model_safe_evaluator_text(projection.reason),
                "missing_required_true": safe_missing,
                "present_required_false": safe_present,
            }
            violated = metadata.get("violated_temporal_constraints")
            if isinstance(violated, Sequence) and not isinstance(
                violated, (str, bytes, bytearray)
            ):
                evidence["violated_temporal_constraints"] = list(violated)
            self._decision_escalation_evidence = evidence
            self._decision_escalation_state_key = self._active_state_key
            self._telemetry["decision_escalation_certificate_count"] = int(
                self._telemetry["decision_escalation_certificate_count"]
            ) + 1
        return replace(projection, metadata=metadata)

    def _patch_entry_state(
        self,
        task: object,
        current_state: object,
        projection: ProjectionResult,
        start_index: int,
    ) -> object:
        prior = [
            projected
            for projected in projection.subtasks
            if projected.plan.index < start_index
        ]
        if not prior:
            return self.snapshot_state(task, current_state)
        return self.snapshot_state(task, prior[-1].projected_state)

    def _patch_request(
        self,
        task: object,
        current_state: object,
        state_output: str,
        h1_output: str,
        decision_output: str,
        projection: ProjectionResult,
        feedback: str,
        include_code_block: bool,
    ) -> StageRequest:
        del state_output, include_code_block
        candidate = self._candidate
        assert candidate is not None
        decision_ids = [item.index for item in candidate.decision.subtasks]
        failed_index = int(projection.failed_subtask_index or decision_ids[0])
        signature = self._failure_signature(projection)
        if candidate.serial != self._last_analyzed_serial:
            if signature == self._last_failure_signature:
                self._same_failure_count += 1
            else:
                self._same_failure_count = 0
            self._last_failure_signature = signature
            self._last_analyzed_serial = candidate.serial

        start_index = failed_index
        if self._same_failure_count >= self.checkpoint_backtrack_after:
            position = decision_ids.index(failed_index)
            if position > 0:
                start_index = decision_ids[position - 1]
                self._telemetry["backtrack_count"] = int(
                    self._telemetry["backtrack_count"]
                ) + 1
                self._same_failure_count = 0

        suffix_ids = [index for index in decision_ids if index >= start_index]
        preserved_ids = [index for index in decision_ids if index < start_index]
        safe_projection = lexicon._projection_payload(projection)
        projection_metadata = (
            projection.metadata
            if isinstance(projection.metadata, Mapping)
            else {}
        )

        def safe_text_list(value: object) -> List[str]:
            if not isinstance(value, Sequence) or isinstance(
                value, (str, bytes, bytearray)
            ):
                return []
            return [
                lexicon._model_safe_evaluator_text(str(item)) for item in value
            ]

        # Checkpoint metadata is evaluator-generated, but expose it through an
        # explicit allow-list so a future private/oracle field cannot silently
        # enter a model prompt.  These facts are exactly the public checkpoint
        # mismatch the suffix repairer needs to address.
        safe_checkpoint: Dict[str, object] = {
            "missing_required_true": safe_text_list(
                projection_metadata.get("missing_required_true", [])
            ),
            "present_required_false": safe_text_list(
                projection_metadata.get("present_required_false", [])
            ),
        }
        raw_violated_temporal = projection_metadata.get(
            "violated_temporal_constraints", []
        )
        if not raw_violated_temporal:
            raw_violated_temporal = _public_temporal_failures(
                task, projection_metadata.get("unsatisfied_conditions", [])
            )
        safe_violated_temporal: List[Dict[str, object]] = []
        task_constraints = getattr(task, "constraints", ())
        if (
            isinstance(raw_violated_temporal, Sequence)
            and not isinstance(raw_violated_temporal, (str, bytes, bytearray))
            and isinstance(task_constraints, Sequence)
            and not isinstance(task_constraints, (str, bytes, bytearray))
        ):
            for item in raw_violated_temporal:
                if not isinstance(item, Mapping):
                    continue
                index = item.get("index")
                if (
                    not isinstance(index, int)
                    or isinstance(index, bool)
                    or not 1 <= index <= len(task_constraints)
                ):
                    continue
                safe_violated_temporal.append(
                    {
                        "index": index,
                        "constraint": lexicon._model_safe_evaluator_text(
                            str(task_constraints[index - 1])
                        ),
                    }
                )
        if safe_violated_temporal:
            safe_checkpoint["violated_temporal_constraints"] = (
                safe_violated_temporal
            )
        raw_checkpoint = projection_metadata.get("checkpoint")
        if isinstance(raw_checkpoint, Mapping):
            safe_checkpoint["checkpoint"] = {
                "required_true": safe_text_list(
                    raw_checkpoint.get("required_true", [])
                ),
                "required_false": safe_text_list(
                    raw_checkpoint.get("required_false", [])
                ),
                "constraints_addressed": [
                    item
                    for item in raw_checkpoint.get("constraints_addressed", [])
                    if isinstance(item, int) and not isinstance(item, bool)
                ]
                if isinstance(
                    raw_checkpoint.get("constraints_addressed", []), Sequence
                )
                else [],
            }

        raw_final_verification = projection_metadata.get("final_verification")
        if isinstance(raw_final_verification, Mapping):
            safe_final: Dict[str, object] = {}
            for key in (
                "valid",
                "goal_and_constraints_satisfied",
                "submitted_length",
                "goal_failure",
                "constraint_failure",
                "first_failed_action_index",
            ):
                value = raw_final_verification.get(key)
                if isinstance(value, (bool, int)) or value is None:
                    safe_final[key] = value
            for key in (
                "failure_kind",
                "failure_message",
                "first_failed_action",
            ):
                value = raw_final_verification.get(key)
                safe_final[key] = (
                    lexicon._model_safe_evaluator_text(str(value))
                    if value is not None
                    else None
                )
            for key in (
                "unsatisfied_preconditions",
                "unsatisfied_task_goals",
                "unsatisfied_constraint_goals",
            ):
                safe_final[key] = safe_text_list(
                    raw_final_verification.get(key, [])
                )
            safe_checkpoint["final_verification"] = safe_final

        certificate = {
            "failed_subtask_index": projection.failed_subtask_index,
            "failed_action_index": projection.failed_action_index,
            "failed_action": safe_projection.get("failed_action"),
            "failure_kind": safe_projection.get("failure_kind"),
            "reason": safe_projection.get("reason"),
            "unsatisfied_conditions": safe_projection.get(
                "unsatisfied_conditions", []
            ),
            "checkpoint_failure": bool(
                projection.checkpoint_failure
                or projection.metadata.get("original_checkpoint_failure")
            ),
            "preserved_checkpoint_valid_subtasks": preserved_ids,
            "repair_subtasks": suffix_ids,
            "repair_start_subtask": start_index,
            "repair_entry_state": self._patch_entry_state(
                task, current_state, projection, start_index
            ),
            "state_before_failed_action": self.snapshot_state(
                task, projection.final_state
            ),
            "failed_action_index_within_subtask": (
                int(projection.failed_action_index)
                - sum(len(item.plan.actions) for item in projection.subtasks)
                if projection.failed_action_index is not None
                else None
            ),
            **safe_checkpoint,
        }
        failure_certificates = self._telemetry["failure_certificates"]
        assert isinstance(failure_certificates, list)
        failure_certificates.append(certificate)
        self._telemetry["localized_patch_request_count"] = int(
            self._telemetry["localized_patch_request_count"]
        ) + 1
        self._telemetry["preserved_subtask_count_total"] = int(
            self._telemetry["preserved_subtask_count_total"]
        ) + len(preserved_ids)
        self._pending_patch = {
            "candidate_serial": candidate.serial,
            "start_index": start_index,
            "suffix_ids": tuple(suffix_ids),
            "preserved_ids": tuple(preserved_ids),
            "previous_output": candidate.output,
            "certificate": certificate,
        }

        task_text = lexicon._model_task_text(task)
        return StageRequest(
            stage="hierarchy_planner",
            system=SYSTEM_HIERARCHY_PATCH,
            prompt=f"""You are the InnerBot localized hierarchy repair controller.

Repair only the failed hierarchy subtask and its downstream suffix.  The
earlier checkpoint-valid subtask blocks are frozen and will be inserted by the
controller; do not reproduce or modify them.  The generic mapping block is
also frozen.  Suffix blocks may call the frozen custom mappings or the verified
H1 functions directly.

LEXICON TASK:
{task_text}

VERIFIED H1 MAPPINGS:
{h1_output}

DECISIONBOT CHECKPOINT PLAN:
{decision_output}

PREVIOUS COMPILED HIERARCHY:
{candidate.output}

DETERMINISTIC FAILURE CERTIFICATE:
{json.dumps(certificate, indent=2, sort_keys=True)}

STAGE-LOCAL FEEDBACK:
{feedback or 'N/A'}

Return exactly these numbered blocks, in this order: {suffix_ids}.
Do not return a mapping block, the frozen prefix blocks, prose, pseudocode, or
Markdown outside those blocks.  Each block may contain H1/custom calls.  Use
the sole exact token {CHECKPOINT_NOOP} only when its checkpoint is already true
at that block's entry state; the controller verifies this deterministically.
""",
        )

    def decision_request(
        self,
        task: object,
        state: object,
        scene: object,
        state_output: str,
        h1_output: str,
        feedback: str,
    ) -> StageRequest:
        request = super().decision_request(
            task,
            state,
            scene,
            state_output,
            h1_output,
            feedback,
        )
        evidence = self._decision_escalation_evidence
        if (
            evidence is None
            or self._decision_escalation_state_key
            != _state_key(self, task, state)
        ):
            return request
        return replace(
            request,
            prompt=(
                request.prompt.rstrip()
                + "\n\nDETERMINISTIC CHECKPOINT ESCALATION EVIDENCE:\n"
                + json.dumps(evidence, indent=2, sort_keys=True)
                + "\nRevise the semantic checkpoints to address this exact "
                "public failure evidence. Return no actions or function calls.\n"
            ),
        )

    def hierarchy_request(
        self,
        task: object,
        state: object,
        scene: object,
        state_output: str,
        h1_output: str,
        decision_output: str,
        feedback: str,
        include_code_block: bool,
    ) -> StageRequest:
        if self._candidate_compatible(
            task, state, h1_output, decision_output
        ):
            assert self._candidate is not None
            projection = shared.project_compiled_hierarchy(
                task,
                self,
                state,
                self._candidate.decision,
                self._candidate.hierarchy,
            )
            if not projection.valid and projection.failed_subtask_index is not None:
                return self._patch_request(
                    task,
                    state,
                    state_output,
                    h1_output,
                    decision_output,
                    projection,
                    feedback,
                    include_code_block,
                )

        self._pending_patch = None
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
        return replace(
            request,
            prompt=(
                request.prompt.rstrip()
                + "\n\nA numbered subtask whose checkpoint is already true may "
                f"contain the sole exact token `{CHECKPOINT_NOOP}`. It represents "
                "zero calls and zero actions and will be accepted only if the "
                "unchanged state passes deterministic checkpoint validation.\n"
            ),
        )

    def _merge_patch(self, raw_patch: str) -> ArtifactCheck[str]:
        pending = self._pending_patch
        candidate = self._candidate
        if pending is None or candidate is None:
            return ArtifactCheck.rejected("No active hierarchy suffix patch")
        if pending["candidate_serial"] != candidate.serial:
            return ArtifactCheck.rejected("Hierarchy patch target is stale")
        if _mapping_block(raw_patch) is not None:
            return ArtifactCheck.rejected(
                "Localized patch must not redefine the frozen mapping block"
            )

        matches = _block_matches(raw_patch)
        ids = [int(match.group("index")) for match in matches]
        expected = list(pending["suffix_ids"])
        errors: List[str] = []
        if ids != expected:
            errors.append(
                f"Localized patch blocks must be exactly {expected} in order; got {ids}"
            )
        leftover = _strip_spans(raw_patch, [match.span() for match in matches])
        if leftover.strip().strip("`").strip():
            errors.append("Localized patch contains text outside numbered blocks")
        if errors:
            return ArtifactCheck.rejected(*errors)

        mapping = _mapping_block(candidate.output)
        if mapping is None:
            return ArtifactCheck.rejected(
                "Stored hierarchy candidate has no unique mapping block"
            )
        previous_bodies = {
            int(match.group("index")): match.group("body").strip()
            for match in _block_matches(candidate.output)
        }
        patch_bodies = {
            int(match.group("index")): match.group("body").strip()
            for match in matches
        }
        all_ids = [item.index for item in candidate.decision.subtasks]
        bodies: List[str] = []
        for index in all_ids:
            source = patch_bodies if index in patch_bodies else previous_bodies
            if index not in source:
                errors.append(f"No hierarchy block body available for subtask {index}")
                continue
            bodies.append(_render_call_block(index, source[index]))
        if errors:
            return ArtifactCheck.rejected(*errors)
        return ArtifactCheck.accepted(mapping + "\n\n" + "\n\n".join(bodies))

    def compile_hierarchy(
        self,
        task: object,
        state: object,
        h1_output: str,
        decision_output: str,
        decision: object,
        hierarchy_output: str,
    ) -> ArtifactCheck:
        raw_output = hierarchy_output
        repair_mode = self._pending_patch is not None
        preserved_ids: Sequence[int] = ()
        if repair_mode:
            assert self._pending_patch is not None
            preserved_ids = tuple(self._pending_patch["preserved_ids"])
            merged = self._merge_patch(raw_output)
            if not merged.valid or not isinstance(merged.value, str):
                self._telemetry["localized_patch_reject_count"] = int(
                    self._telemetry["localized_patch_reject_count"]
                ) + 1
                self._render_history.append(
                    {
                        "raw": raw_output,
                        "resolved": None,
                        "repair_mode": True,
                        "errors": list(merged.errors),
                    }
                )
                return ArtifactCheck.rejected(*merged.errors)
            hierarchy_output = merged.value

        check = self._compile_with_noops(
            task, h1_output, decision, hierarchy_output
        )
        if (
            repair_mode
            and check.valid
            and isinstance(check.value, CompiledHierarchy)
            and self._candidate is not None
        ):
            previous = {
                item.index: item for item in self._candidate.hierarchy.subtasks
            }
            current = {item.index: item for item in check.value.subtasks}
            prefix_errors: List[str] = []
            for index in preserved_ids:
                old = previous.get(index)
                new = current.get(index)
                if old is None or new is None:
                    prefix_errors.append(
                        f"Certified prefix subtask {index} disappeared during merge"
                    )
                    continue
                if (
                    old.top_level_calls != new.top_level_calls
                    or old.h0_calls != new.h0_calls
                    or old.actions != new.actions
                ):
                    prefix_errors.append(
                        f"Certified prefix subtask {index} changed during merge"
                    )
            if prefix_errors:
                check = ArtifactCheck.rejected(*prefix_errors)
        self._render_history.append(
            {
                "raw": raw_output,
                "resolved": hierarchy_output,
                "repair_mode": repair_mode,
                "preserved_subtasks": list(preserved_ids),
                "errors": list(check.errors),
            }
        )
        if not check.valid or not isinstance(check.value, CompiledHierarchy):
            if repair_mode:
                self._telemetry["localized_patch_reject_count"] = int(
                    self._telemetry["localized_patch_reject_count"]
                ) + 1
            return check

        if repair_mode:
            self._telemetry["localized_patch_accept_count"] = int(
                self._telemetry["localized_patch_accept_count"]
            ) + 1
        self._activate_repair_context(task, state, h1_output, decision)
        self._candidate_serial += 1
        self._candidate = _HierarchyCandidate(
            serial=self._candidate_serial,
            state_key=_state_key(self, task, state),
            h1_output=h1_output,
            decision_output=decision_output,
            decision=decision,
            output=hierarchy_output,
            hierarchy=check.value,
        )
        self._pending_patch = None
        return check

    # ------------------------------------------------------------------
    # A valid candidate is authoritative; LLM bots remain advisory.
    # ------------------------------------------------------------------
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
        if isinstance(projection, ProjectionResult) and projection.valid:
            candidate_output = (
                self._candidate.output
                if self._candidate is not None
                else hierarchy_output
            )
            self._router_projection_valid = bool(
                self.goal_reached(task, projection.final_state)
            )
            if self._router_projection_valid and self._candidate is not None:
                projected_actions = getattr(
                    projection.final_state, "executed_actions", None
                )
                if isinstance(projected_actions, Sequence) and not isinstance(
                    projected_actions, (str, bytes, bytearray)
                ):
                    full_actions = tuple(projected_actions)
                else:
                    committed_actions = getattr(state, "executed_actions", ())
                    if not isinstance(committed_actions, Sequence) or isinstance(
                        committed_actions, (str, bytes, bytearray)
                    ):
                        committed_actions = ()
                    suffix_actions = tuple(
                        action
                        for subtask in self._candidate.hierarchy.subtasks
                        for action in subtask.actions
                    )
                    full_actions = (*tuple(committed_actions), *suffix_actions)
                self._telemetry["valid_incumbent_count"] = int(
                    self._telemetry["valid_incumbent_count"]
                ) + 1
                if (
                    self._valid_incumbent is None
                    or len(full_actions) < len(self._valid_incumbent.full_actions)
                ):
                    # This is a public, candidate-intrinsic comparison only.
                    # Never consult the released optimal plan/length oracle.
                    self._valid_incumbent = _ValidIncumbent(
                        state_output,
                        self._candidate.h1_output,
                        self._candidate.decision_output,
                        candidate_output,
                        self._candidate.hierarchy,
                        projection,
                        full_actions,
                    )
                    self._telemetry["valid_incumbent_update_count"] = int(
                        self._telemetry["valid_incumbent_update_count"]
                    ) + 1
            return super().router_request(
                task,
                state,
                scene,
                state_output,
                decision_output,
                candidate_output,
                projection,
                execution_feedback=execution_feedback,
            )
        self._router_projection_valid = False
        return super().router_request(
            task,
            state,
            scene,
            state_output,
            decision_output,
            hierarchy_output,
            projection,
            execution_feedback=execution_feedback,
        )

    def parse_router(self, output: str) -> RouterVerdict:
        verdict = super().parse_router(output)
        if self._router_projection_valid and not verdict.no_mistake:
            self._telemetry["router_validity_override_count"] = int(
                self._telemetry["router_validity_override_count"]
            ) + 1
            return RouterVerdict(
                True,
                "NA",
                "Deterministic complete-plan validity overrides advisory rejection: "
                + verdict.reason,
            )
        return verdict

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
        self._outer_expected_status = (
            "TASK SUCCESS" if is_last else "SUBTASK SUCCESS"
        )
        return super().outer_request(
            task,
            decision,
            hierarchy,
            subtask,
            previous_state,
            current_state,
            is_last,
        )

    def parse_outer(self, output: str) -> OuterVerdict:
        verdict = super().parse_outer(output)
        expected = self._outer_expected_status
        self._outer_expected_status = None
        if expected is not None and verdict.status != expected:
            self._telemetry["outerbot_validity_override_count"] = int(
                self._telemetry["outerbot_validity_override_count"]
            ) + 1
            return OuterVerdict(
                expected,
                "Deterministic projected transition overrides advisory verdict: "
                + verdict.reason,
            )
        return verdict

    # ------------------------------------------------------------------
    # Result normalization and incumbent fallback
    # ------------------------------------------------------------------
    def _restore_valid_incumbent(
        self, task: object, result: SharedLoopResult
    ) -> SharedLoopResult:
        incumbent = self._valid_incumbent
        if incumbent is None or bool(getattr(result.score, "valid", False)):
            return result
        hierarchy = incumbent.hierarchy
        actions = incumbent.full_actions
        candidate_high_level = tuple(
            self.format_call(call)
            for subtask in hierarchy.subtasks
            for call in subtask.top_level_calls
        )
        prior_high_level = tuple(result.high_level_plan)
        overlap = 0
        for size in range(
            min(len(prior_high_level), len(candidate_high_level)), 0, -1
        ):
            if prior_high_level[-size:] == candidate_high_level[:size]:
                overlap = size
                break
        high_level = (
            *prior_high_level,
            *candidate_high_level[overlap:],
        )
        # H0 is the primitive expansion.  Rendering the incumbent's complete
        # action history keeps this trace aligned even when the hierarchy was
        # planned from a noninitial state and therefore contains only a suffix.
        expanded = tuple(
            self.format_action(action) for action in incumbent.full_actions
        )
        level_totals: Dict[int, int] = {}
        for subtask in hierarchy.subtasks:
            for level, count in subtask.level_counts.items():
                level_totals[int(level)] = level_totals.get(int(level), 0) + int(count)
        context = FinalScoreContext(
            task=task,
            final_state=incumbent.projection.final_state,
            executed_actions=actions,
            high_level_plan=high_level,
            expanded_h0_plan=expanded,
            parse_errors=tuple(result.parse_errors),
            last_illegal_reason=None,
            total_top_level_count=len(high_level),
            total_h0_count=len(expanded),
            level_totals=level_totals,
            max_level_seen=hierarchy.stats.max_level,
            base_valid_any=hierarchy.stats.base_pattern_valid,
            hierarchy_valid_any=hierarchy.stats.hierarchy_valid,
            last_mapping_count_by_level=hierarchy.stats.mapping_count_by_level,
            hierarchy_errors_seen=hierarchy.stats.errors,
        )
        score = self.final_score(context)
        if not bool(getattr(score, "valid", False)):
            return result
        self._telemetry["valid_incumbent_restored"] = True
        self._restored_incumbent = incumbent
        return replace(
            result,
            termination_reason="deterministic_valid_incumbent_restored",
            score=score,
            final_state=incumbent.projection.final_state,
            executed_actions=actions,
            high_level_plan=high_level,
            expanded_h0_plan=expanded,
        )

    def finalize_prefix_repair_result(
        self, task: object, result: SharedLoopResult
    ) -> SharedLoopResult:
        result = self._restore_valid_incumbent(task, result)

        history = iter(self._render_history)
        attempts: List[Mapping[str, object]] = []
        for original in result.attempts:
            attempt = dict(original)
            outputs = dict(attempt.get("stage_outputs", {}))
            cache_hits = attempt.get("cache_hits", ())
            generated_hierarchy = (
                "hierarchy_output" in outputs
                and not (
                    isinstance(cache_hits, Sequence)
                    and "hierarchy" in cache_hits
                )
            )
            if generated_hierarchy:
                try:
                    record = next(history)
                except StopIteration:
                    record = None
                if record is not None:
                    raw = outputs["hierarchy_output"]
                    resolved = record.get("resolved")
                    if record.get("repair_mode"):
                        outputs["hierarchy_patch_output"] = raw
                        attempt["repair_mode"] = "certified_suffix_patch"
                        attempt["preserved_subtasks"] = record.get(
                            "preserved_subtasks", []
                        )
                    if isinstance(resolved, str):
                        outputs["hierarchy_output"] = resolved
            attempt["stage_outputs"] = outputs
            attempts.append(attempt)

        outputs = dict(result.outputs)
        raw_hierarchy = outputs.get("hierarchy_output")
        if isinstance(raw_hierarchy, str):
            # Resolve only the artifact that actually appears in the terminal
            # attempt.  Blindly publishing the latest compiled candidate can
            # mismatch a later malformed attempt or an older restored incumbent.
            for record in reversed(self._render_history):
                if record.get("raw") != raw_hierarchy:
                    continue
                resolved = record.get("resolved")
                if record.get("repair_mode"):
                    outputs["hierarchy_patch_output"] = raw_hierarchy
                if isinstance(resolved, str):
                    outputs["hierarchy_output"] = resolved
                break
        if self._restored_incumbent is not None:
            outputs["state_output"] = self._restored_incumbent.state_output
            outputs["h1_output"] = self._restored_incumbent.h1_output
            outputs["plan_output"] = self._restored_incumbent.decision_output
            outputs["decision_output"] = (
                self._restored_incumbent.decision_output
            )
            outputs["hierarchy_output"] = (
                self._restored_incumbent.hierarchy_output
            )
        extra = dict(result.extra_metrics)
        extra.update(
            {
                "shared_pipeline_version": PIPELINE_VERSION,
                "prefix_repair": True,
                "repair_boundary": "checkpoint-validated-subtask",
                "deterministic_validity_authoritative": True,
                "classical_planner_used": False,
                **self._telemetry,
            }
        )
        return replace(
            result,
            outputs=outputs,
            attempts=tuple(attempts),
            extra_metrics=extra,
        )


__all__ = [
    "CHECKPOINT_NOOP",
    "PIPELINE_VERSION",
    "PrefixRepairLexiconNLevelAdapter",
    "SYSTEM_HIERARCHY_PATCH",
]
