"""Checkpoint-only no-op support for Flat Hanoi hierarchy adapters.

Compose :class:`FlatHanoiCheckpointNoOpMixin` before a v5-derived Flat Hanoi
adapter.  The ordinary compiler remains authoritative for candidates without
the reserved token.  A numbered block whose sole exact body is
``CheckpointNoOp()`` is retained as an empty :class:`PlannedSubtask`; projection
therefore still visits its checkpoint boundary at the unchanged state.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Dict, List, Mapping, Sequence, Tuple

from dynamic_scoring import analyze_hierarchy, count_calls_by_level, expand_hierarchy
from scoring import (
    CALL_PATTERN,
    PRIMITIVES,
    extract_moves_from_h0,
    parse_calls,
    parse_mappings,
)
from shared_nlevel_pipeline import (
    ArtifactCheck,
    CompiledHierarchy,
    HierarchyStats,
    PlannedSubtask,
    StageRequest,
)
from shared_nlevel_verified_repair_adapters import (
    _FLAG_BLOCK_RE,
    _MAPPING_BLOCK_RE,
    _SUBTASK_BLOCK_RE,
    _strip_spans,
)


FLAT_CHECKPOINT_NOOP = "CheckpointNoOp()"
_NOOP_CALL_RE = re.compile(r"\bCheckpointNoOp\s*\(\s*\)")


def _errors(prefix: str, values: Sequence[str]) -> List[str]:
    return [f"{prefix}: {value}" for value in values]


def _with_noop_instruction(request: StageRequest) -> StageRequest:
    instruction = (
        "\n\nA numbered subtask whose checkpoint is already true may contain "
        f"the sole exact token `{FLAT_CHECKPOINT_NOOP}`. It represents zero "
        "calls/actions. Keep the numbered subtask: its checkpoint must still "
        "be checked at the unchanged state by the configured checkpoint or "
        "execution-audit verifier. Do not define this reserved token in the "
        "mapping block.\n"
    )
    return replace(request, prompt=request.prompt.rstrip() + instruction)


class FlatHanoiCheckpointNoOpMixin:
    """Add one reserved checkpoint no-op to a strict Flat Hanoi adapter.

    Put this mixin before the concrete adapter in the MRO.  No-op-free
    candidates delegate directly to ``super().compile_hierarchy`` so their
    parsing, expansion, statistics, and errors remain unchanged.
    """

    def hierarchy_request(self, *args: object, **kwargs: object) -> StageRequest:
        return _with_noop_instruction(super().hierarchy_request(*args, **kwargs))

    def hierarchy_repair_request(
        self, *args: object, **kwargs: object
    ) -> StageRequest:
        return _with_noop_instruction(
            super().hierarchy_repair_request(*args, **kwargs)
        )

    def compile_hierarchy(
        self,
        task: object,
        state: object,
        h1_output: str,
        decision_output: str,
        decision: Sequence[Mapping[str, object]],
        hierarchy_output: str,
    ) -> ArtifactCheck:
        text = hierarchy_output or ""
        matches = list(_SUBTASK_BLOCK_RE.finditer(text))
        noop_ids: List[int] = []
        errors: List[str] = []

        for match in matches:
            index = int(match.group("index"))
            body = match.group("body").strip()
            if body == FLAT_CHECKPOINT_NOOP:
                noop_ids.append(index)
            elif _NOOP_CALL_RE.search(body):
                errors.append(
                    f"V5 Flat hierarchy subtask {index}: "
                    f"{FLAT_CHECKPOINT_NOOP} must be the sole exact block body"
                )

        if len(_NOOP_CALL_RE.findall(text)) != len(noop_ids):
            errors.append(
                f"{FLAT_CHECKPOINT_NOOP} may appear only as the sole exact body "
                "of a numbered Flat hierarchy subtask"
            )
        if errors:
            return ArtifactCheck.rejected(*errors)
        if not noop_ids:
            return super().compile_hierarchy(
                task,
                state,
                h1_output,
                decision_output,
                decision,
                hierarchy_output,
            )

        mapping_matches = list(_MAPPING_BLOCK_RE.finditer(text))
        if len(mapping_matches) != 1:
            errors.append("V5 Flat hierarchy must contain exactly one mapping block")

        actual_ids = [int(match.group("index")) for match in matches]
        expected_ids = [
            int(item["subtask_index"])
            for item in decision
            if isinstance(item, Mapping) and "subtask_index" in item
        ]
        if actual_ids != expected_ids:
            errors.append(
                f"V5 Flat hierarchy blocks must be exactly {expected_ids} in "
                f"order; got {actual_ids}"
            )

        noop_set = set(noop_ids)
        for match in matches:
            index = int(match.group("index"))
            if index in noop_set:
                continue
            body = match.group("body")
            calls = list(CALL_PATTERN.finditer(body))
            residue = _strip_spans(body, [call.span() for call in calls])
            if not calls or re.sub(r"[\s,;]", "", residue):
                errors.append(
                    f"V5 Flat hierarchy subtask {index} must contain only "
                    "function calls"
                )

        allowed_spans = [match.span() for match in mapping_matches]
        allowed_spans.extend(match.span() for match in matches)
        flag_matches = list(_FLAG_BLOCK_RE.finditer(text))
        if len(flag_matches) > 1:
            errors.append("V5 Flat hierarchy may contain at most one code block")
        allowed_spans.extend(match.span() for match in flag_matches)
        leftover = _strip_spans(text, allowed_spans)
        if leftover.strip().strip("`").strip():
            errors.append("V5 Flat hierarchy contains text outside declared blocks")

        h1_mappings: Dict[str, object] = {}
        custom_mappings: Dict[str, object] = {}
        if len(mapping_matches) == 1:
            h1_mappings, h1_errors = parse_mappings(h1_output)
            custom_mappings, custom_errors = parse_mappings(
                mapping_matches[0].group(0)
            )
            errors.extend(_errors("V5 Flat H1", h1_errors))
            errors.extend(_errors("V5 Flat hierarchy mapping", custom_errors))
            collisions = sorted(set(h1_mappings) & set(custom_mappings))
            primitive_collisions = sorted(set(PRIMITIVES) & set(custom_mappings))
            if collisions:
                errors.append(
                    "V5 Flat hierarchy shadows verified H1 mappings: "
                    + ", ".join(collisions)
                )
            if primitive_collisions:
                errors.append(
                    "V5 Flat hierarchy shadows H0 primitives: "
                    + ", ".join(primitive_collisions)
                )
        if errors:
            return ArtifactCheck.rejected(*errors)

        mappings = {**h1_mappings, **custom_mappings}
        analysis = analyze_hierarchy(mappings)
        errors.extend(_errors("Hierarchy", analysis.errors))

        descriptions = {
            int(item["subtask_index"]): str(item.get("description", ""))
            for item in decision
            if isinstance(item, Mapping) and "subtask_index" in item
        }
        checkpoint_states = {
            int(item["subtask_index"]): item.get("v5_checkpoint_state")
            for item in decision
            if isinstance(item, Mapping) and "subtask_index" in item
        }
        planned: List[PlannedSubtask] = []
        if not errors:
            for match in matches:
                index = int(match.group("index"))
                if index in noop_set:
                    planned.append(
                        PlannedSubtask(
                            index=index,
                            description=descriptions.get(index, ""),
                            top_level_calls=(),
                            h0_calls=(),
                            actions=(),
                            level_counts={},
                            metadata={
                                "checkpoint": checkpoint_states.get(index),
                                "checkpoint_noop": True,
                            },
                        )
                    )
                    continue

                # The strict residue check above guarantees that these are all
                # of the non-separator contents in the block.
                calls = parse_calls(match.group("body"))
                level_counts = count_calls_by_level(calls, mappings, analysis.levels)
                h0_calls, expand_errors = expand_hierarchy(calls, mappings)
                errors.extend(_errors("Expand", expand_errors))
                actions, action_errors = extract_moves_from_h0(h0_calls)
                errors.extend(_errors("H0", action_errors))
                planned.append(
                    PlannedSubtask(
                        index=index,
                        description=descriptions.get(
                            index,
                            "Execute subtask "
                            f"{index} with calls: "
                            + ", ".join(str(call) for call in calls),
                        ),
                        top_level_calls=tuple(calls),
                        h0_calls=tuple(h0_calls),
                        actions=tuple(actions),
                        level_counts=dict(level_counts),
                    )
                )

        top_level_count = sum(len(item.top_level_calls) for item in planned)
        expanded_action_count = sum(len(item.actions) for item in planned)
        expanded_h0_count = sum(len(item.h0_calls) for item in planned)
        stats_metadata = {
            "top_level_call_count": top_level_count,
            "expanded_action_count": expanded_action_count,
            "expanded_h0_call_count": expanded_h0_count,
            "checkpoint_noop_subtasks": list(noop_ids),
            "compression_ratio": (
                round(expanded_action_count / top_level_count, 6)
                if top_level_count
                else None
            ),
        }
        stats = HierarchyStats(
            max_level=analysis.max_level,
            base_pattern_valid=analysis.base_pattern_valid,
            hierarchy_valid=analysis.valid and analysis.max_level >= 2,
            mapping_count_by_level=dict(analysis.mapping_count_by_level),
            errors=tuple(analysis.errors),
            metadata=stats_metadata,
        )
        compiled = CompiledHierarchy(
            subtasks=tuple(planned),
            stats=stats,
            metadata={"checkpoint_noop_subtasks": tuple(noop_ids)},
        )
        if errors:
            return ArtifactCheck.rejected(*errors, value=compiled)
        return ArtifactCheck.accepted(
            compiled,
            metadata={
                "mappings": mappings,
                "levels": dict(analysis.levels),
                **stats_metadata,
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
        if not bool(subtask.metadata.get("checkpoint_noop")):
            return check
        metadata = dict(check.metadata)
        metadata.update(
            {
                "checkpoint_noop": True,
                "checkpoint_noop_zero_actions": not (
                    subtask.top_level_calls or subtask.h0_calls or subtask.actions
                ),
            }
        )
        if bool(getattr(self, "llm_only_online", False)):
            metadata["checkpoint_noop_semantic_verification"] = "WITHHELD"
        else:
            metadata["checkpoint_noop_verified_at_unchanged_state"] = check.valid
        return replace(check, metadata=metadata)


__all__ = ["FLAT_CHECKPOINT_NOOP", "FlatHanoiCheckpointNoOpMixin"]
