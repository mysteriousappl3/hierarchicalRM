"""V5 verified-prefix/suffix repair hooks for LexiCon Blocksworld."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Dict, List, Mapping, Sequence, Tuple

import shared_nlevel_blocksworld as blocks
from lexicon_blocksworld_task import verify_plan
from shared_nlevel_pipeline import (
    ArtifactCheck,
    CompiledHierarchy,
    HierarchyStats,
    PlannedSubtask,
    StageRequest,
)
from shared_nlevel_verified_repair_adapters import merge_numbered_suffix
from shared_nlevel_verified_repair_pipeline import PIPELINE_VERSION


CHECKPOINT_NOOP = "CheckpointNoOp()"
SYSTEM_VERIFIED_REPAIR_BLOCKSWORLD = (
    "HierarchyPlanner verified-prefix repair (InnerBot localized controller): "
    "regenerate only the failed LexiCon Blocksworld hierarchy suffix from "
    "public deterministic evidence."
)
_NOOP_CALL_RE = re.compile(r"(?<![A-Za-z0-9_])CheckpointNoOp\s*\(")
_PRIVATE_MONITOR_INDEX_RE = re.compile(r"(?:hold_|seen_(?:psi_)?)(?P<index>\d+)")


def _public_temporal_failures(
    task: object, diagnostic_values: object
) -> List[Dict[str, object]]:
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
            "constraint": blocks._model_safe_evaluator_text(constraints[index]),
        }
        for index in sorted(indices)
        if 0 <= index < len(constraints)
    ]


def _safe_text_list(value: object) -> List[str]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        return []
    return [blocks._model_safe_evaluator_text(item) for item in value]


def _entry_state(
    adapter: object,
    task: object,
    current_state: object,
    projection: object,
    preserved_subtask_indices: Sequence[int],
) -> object:
    if not preserved_subtask_indices:
        return adapter.snapshot_state(task, current_state)
    preserved = set(map(int, preserved_subtask_indices))
    projected = [
        item
        for item in getattr(projection, "subtasks", ())
        if int(getattr(getattr(item, "plan", None), "index", -1)) in preserved
    ]
    if not projected:
        return adapter.snapshot_state(task, current_state)
    return adapter.snapshot_state(task, projected[-1].projected_state)


def _compile_with_noops(
    task: object,
    h1_output: str,
    decision: object,
    hierarchy_output: str,
) -> ArtifactCheck:
    """Compile the normal Blocks grammar plus deterministically checked no-ops."""

    if not isinstance(decision, blocks.LexiconDecisionPlan):
        return ArtifactCheck.rejected("Hierarchy received an invalid Decision artifact")
    matches = list(blocks._SUBTASK_CALLS_RE.finditer(hierarchy_output or ""))
    noop_ids: List[int] = []
    noop_spans: List[Tuple[int, int]] = []
    block_ids: List[int] = []
    errors: List[str] = []
    for match in matches:
        index = int(match.group("index"))
        block_ids.append(index)
        body = match.group("body").strip()
        if body == CHECKPOINT_NOOP:
            noop_ids.append(index)
            noop_spans.append(match.span())
        elif _NOOP_CALL_RE.search(body):
            errors.append(
                f"Hierarchy subtask {index}: {CHECKPOINT_NOOP} must be the sole "
                "exact block body"
            )
    expected_ids = [subtask.index for subtask in decision.subtasks]
    if block_ids != expected_ids:
        errors.append(
            f"Hierarchy call blocks must be exactly {expected_ids} in order; "
            f"got {block_ids}"
        )
    if len(_NOOP_CALL_RE.findall(hierarchy_output or "")) != len(noop_ids):
        errors.append(
            f"{CHECKPOINT_NOOP} may appear only as the sole body of a numbered block"
        )
    if errors:
        return ArtifactCheck.rejected(*errors)
    if not noop_ids:
        return blocks._compile_hierarchy(task, h1_output, decision, hierarchy_output)

    pieces: List[str] = []
    cursor = 0
    for start, end in sorted(noop_spans):
        pieces.append(hierarchy_output[cursor:start])
        cursor = end
    pieces.append(hierarchy_output[cursor:])
    filtered_output = "".join(pieces)
    noop_set = set(noop_ids)
    filtered_decision = blocks.LexiconDecisionPlan(
        tuple(item for item in decision.subtasks if item.index not in noop_set)
    )
    base = blocks._compile_hierarchy(
        task, h1_output, filtered_decision, filtered_output
    )
    if not base.valid or not isinstance(base.value, CompiledHierarchy):
        return base

    compiled = base.value
    compiled_by_id = {subtask.index: subtask for subtask in compiled.subtasks}
    decision_by_id = decision.by_index()
    rebuilt: List[PlannedSubtask] = []
    for index in expected_ids:
        if index not in noop_set:
            rebuilt.append(compiled_by_id[index])
            continue
        item = decision_by_id[index]
        rebuilt.append(
            PlannedSubtask(
                index=index,
                description=item.description,
                top_level_calls=(),
                h0_calls=(),
                actions=(),
                level_counts={},
                metadata={
                    "checkpoint": item.checkpoint.to_dict(),
                    "checkpoint_noop": True,
                },
            )
        )
    top_count = sum(len(item.top_level_calls) for item in rebuilt)
    expanded_count = sum(len(item.actions) for item in rebuilt)
    stats_metadata = dict(compiled.stats.metadata)
    stats_metadata.update(
        {
            "top_level_call_count": top_count,
            "expanded_action_count": expanded_count,
            "checkpoint_noop_subtasks": list(noop_ids),
            "compression_ratio": (
                round(expanded_count / top_count, 6) if top_count else None
            ),
        }
    )
    stats: HierarchyStats = replace(compiled.stats, metadata=stats_metadata)
    metadata = dict(compiled.metadata)
    metadata["checkpoint_noop_subtasks"] = tuple(noop_ids)
    result = replace(
        compiled,
        subtasks=tuple(rebuilt),
        stats=stats,
        metadata=metadata,
    )
    return ArtifactCheck.accepted(
        result,
        metadata={
            **dict(base.metadata),
            "top_level_call_count": top_count,
            "expanded_action_count": expanded_count,
            "checkpoint_noop_subtasks": list(noop_ids),
        },
    )


class VerifiedRepairBlocksworldNLevelAdapter(
    blocks.SharedNLevelBlocksworldAdapter
):
    """Blocksworld domain hooks for the unchanged domain-generic v5 loop."""

    pipeline_version = PIPELINE_VERSION
    checkpoint_local_repair_limit = 2
    repair_backtrack_after = 2

    def states_equivalent(self, task: object, left: object, right: object) -> bool:
        del task
        return bool(left == right)

    def hierarchy_request(self, *args: object, **kwargs: object) -> StageRequest:
        request = super().hierarchy_request(*args, **kwargs)
        return replace(
            request,
            prompt=(
                request.prompt.rstrip()
                + "\n\nA numbered subtask whose checkpoint is already true may "
                f"contain the sole exact token `{CHECKPOINT_NOOP}`. It represents "
                "zero calls/actions and is accepted only when deterministic "
                "checkpoint validation succeeds at the unchanged state.\n"
            ),
        )

    def compile_hierarchy(
        self,
        task: object,
        state: object,
        h1_output: str,
        decision_output: str,
        decision: object,
        hierarchy_output: str,
    ) -> ArtifactCheck:
        del state, decision_output
        return _compile_with_noops(task, h1_output, decision, hierarchy_output)

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
            verification = verify_plan(
                task, getattr(projected_state, "executed_actions", ())
            )
            violated = _public_temporal_failures(
                task, verification.unsatisfied_constraint_goals
            )
            if violated:
                metadata["violated_temporal_constraints"] = violated
        if not bool(subtask.metadata.get("checkpoint_noop")):
            return replace(check, metadata=metadata)
        metadata.update(
            {
                "checkpoint_noop": True,
                "checkpoint_noop_verified_at_unchanged_state": check.valid,
                "state_digest": getattr(projected_state, "digest", None),
                "compiler_monitor_facts": list(
                    getattr(projected_state, "monitor_facts", ())
                ),
            }
        )
        if check.valid:
            return ArtifactCheck.accepted(check.value, metadata=metadata)
        return ArtifactCheck.rejected(
            "CheckpointNoOp rejected: unchanged state does not satisfy the "
            "checkpoint and/or final temporal obligations",
            *check.errors,
            metadata=metadata,
        )

    def build_repair_certificate(
        self,
        task: object,
        current_state: object,
        decision: object,
        hierarchy: object,
        projection: object,
        preserved_subtask_indices: Sequence[int],
        repair_subtask_indices: Sequence[int],
    ) -> Mapping[str, object]:
        del decision, hierarchy
        public = blocks._projection_payload(projection)
        metadata = getattr(projection, "metadata", {})
        metadata = metadata if isinstance(metadata, Mapping) else {}
        certificate: Dict[str, object] = {
            **public,
            "repair_entry_state": _entry_state(
                self,
                task,
                current_state,
                projection,
                preserved_subtask_indices,
            ),
            "state_before_failure": self.snapshot_state(
                task, getattr(projection, "final_state", current_state)
            ),
            "missing_required_true": _safe_text_list(
                metadata.get("missing_required_true", [])
            ),
            "present_required_false": _safe_text_list(
                metadata.get("present_required_false", [])
            ),
            "checkpoint": {},
        }
        checkpoint = metadata.get("checkpoint")
        if isinstance(checkpoint, Mapping):
            raw_indices = checkpoint.get("constraints_addressed", [])
            certificate["checkpoint"] = {
                "required_true": _safe_text_list(
                    checkpoint.get("required_true", [])
                ),
                "required_false": _safe_text_list(
                    checkpoint.get("required_false", [])
                ),
                "constraints_addressed": [
                    value
                    for value in raw_indices
                    if isinstance(value, int) and not isinstance(value, bool)
                ]
                if isinstance(raw_indices, Sequence)
                else [],
            }
        violated = _public_temporal_failures(
            task, metadata.get("unsatisfied_conditions", [])
        )
        if violated:
            certificate["violated_temporal_constraints"] = violated
        certificate["preserved_subtask_indices"] = list(
            map(int, preserved_subtask_indices)
        )
        certificate["repair_subtask_indices"] = list(map(int, repair_subtask_indices))
        return certificate

    def hierarchy_repair_request(
        self,
        task: object,
        current_state: object,
        scene: object,
        state_output: object,
        h1_output: str,
        decision_output: str,
        candidate_output: str,
        certificate: Mapping[str, object],
        preserved_subtask_indices: Sequence[int],
        repair_subtask_indices: Sequence[int],
        feedback: str,
        include_code_block: bool,
    ) -> StageRequest:
        del current_state, scene, state_output, include_code_block
        return StageRequest(
            stage="hierarchy_planner",
            system=SYSTEM_VERIFIED_REPAIR_BLOCKSWORLD,
            prompt=f"""Repair only the failed hierarchy subtask and its suffix.

Earlier checkpoint-valid blocks {list(preserved_subtask_indices)} and the
mapping block are frozen by the controller. Do not reproduce or modify them.

LEXICON BLOCKSWORLD TASK:
{blocks._model_task_text(task)}

VERIFIED H1 MAPPINGS:
{h1_output}

DECISIONBOT CHECKPOINT PLAN:
{decision_output}

PREVIOUS COMPILED HIERARCHY:
{candidate_output}

PUBLIC DETERMINISTIC FAILURE CERTIFICATE:
{json.dumps(dict(certificate), indent=2, sort_keys=True)}

STAGE-LOCAL FEEDBACK:
{feedback or 'N/A'}

Return exactly these numbered blocks in this order:
{list(repair_subtask_indices)}
Do not return a mapping block, frozen prefix, prose, pseudocode, or Markdown
outside those blocks. Each block may use verified H1/custom calls. Use the sole
exact token {CHECKPOINT_NOOP} only when its checkpoint already holds at entry.
""",
        )

    def merge_hierarchy_repair(
        self,
        task: object,
        candidate_output: str,
        patch_output: str,
        preserved_subtask_indices: Sequence[int],
        repair_subtask_indices: Sequence[int],
    ) -> ArtifactCheck:
        del task
        return merge_numbered_suffix(
            candidate_output,
            patch_output,
            preserved_subtask_indices,
            repair_subtask_indices,
        )

    def augment_decision_repair_request(
        self,
        task: object,
        current_state: object,
        base_request: StageRequest,
        certificate: Mapping[str, object],
    ) -> StageRequest:
        del task, current_state
        return replace(
            base_request,
            prompt=(
                base_request.prompt.rstrip()
                + "\n\nPUBLIC DETERMINISTIC CHECKPOINT FAILURE CERTIFICATE:\n"
                + json.dumps(dict(certificate), indent=2, sort_keys=True)
                + "\nRevise checkpoint semantics for this exact failure. "
                "Return no actions/function calls.\n"
            ),
        )


__all__ = [
    "CHECKPOINT_NOOP",
    "SYSTEM_VERIFIED_REPAIR_BLOCKSWORLD",
    "VerifiedRepairBlocksworldNLevelAdapter",
]
