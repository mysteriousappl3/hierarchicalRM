"""Domain adapters for the v5 generic verified-prefix repair controller.

The controller in :mod:`shared_nlevel_verified_repair_pipeline` owns repair
policy and artifact lifetime.  The adapters supply deterministic domain
parsing/equality plus safe failure-certificate projection, repair prompt
rendering, and transactional text-block merging.  In particular, none of
these classes monkeypatches the shared projector or stores a repair target.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import shared_nlevel_lexicon as lexicon
from flat_prompts import build_scene_description
from scoring import CALL_PATTERN, PRIMITIVES, parse_mappings
from shared_nlevel_pipeline import ArtifactCheck, StageRequest
from shared_nlevel_prefix_repair_lexicon import (
    CHECKPOINT_NOOP,
    PrefixRepairLexiconNLevelAdapter,
    _public_temporal_failures,
)
from shared_nlevel_selective_adapters import SelectiveFlatHanoiNLevelAdapter
from shared_nlevel_selective_lexicon import SelectiveLexiconNLevelAdapter
from shared_nlevel_verified_repair_pipeline import PIPELINE_VERSION


SYSTEM_VERIFIED_REPAIR_LEXICON = (
    "HierarchyPlanner verified-prefix repair (InnerBot localized controller): "
    "regenerate only the failed LexiCon hierarchy suffix from public "
    "deterministic evidence."
)
SYSTEM_VERIFIED_REPAIR_HANOI = (
    "HierarchyPlanner verified-prefix repair (InnerBot localized controller): "
    "regenerate only the failed Flat Hanoi hierarchy suffix from deterministic "
    "transition evidence."
)

# Both released domains use this common wire format, even though their
# compilers and call languages are otherwise independent.
_MAPPING_BLOCK_RE = re.compile(
    r"(?<![A-Za-z0-9_\x60])(?P<fence>```)?start_mapping\b\s*"
    r"(?P<body>.*?)\s*(?(fence)```|(?<!\x60))end_mapping\b(?!\x60)",
    re.DOTALL,
)
_SUBTASK_BLOCK_RE = re.compile(
    r"(?<![A-Za-z0-9_\x60])(?P<fence>```)?start_subtask_funcs_"
    r"(?P<index>\d+)\b\s*(?P<body>.*?)\s*"
    r"(?(fence)```|(?<!\x60))end_subtask_funcs_(?P=index)\b(?!\x60)",
    re.DOTALL,
)
_FLAG_BLOCK_RE = re.compile(
    r"(?<![A-Za-z0-9_\x60])(?P<fence>```)?start_flag\b\s*"
    r"(?P<body>.*?)\s*(?(fence)```|(?<!\x60))end_flag\b(?!\x60)",
    re.DOTALL,
)


def _strip_spans(text: str, spans: Sequence[Tuple[int, int]]) -> str:
    pieces: List[str] = []
    cursor = 0
    for start, end in sorted(spans):
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _render_subtask_block(index: int, body: str) -> str:
    return (
        f"```start_subtask_funcs_{index}\n"
        f"{body.strip()}\n"
        f"```end_subtask_funcs_{index}"
    )


def merge_numbered_suffix(
    candidate_output: str,
    patch_output: str,
    preserved_subtask_indices: Sequence[int],
    repair_subtask_indices: Sequence[int],
) -> ArtifactCheck[str]:
    """Merge an exact suffix patch while preserving candidate prefix bytes.

    This is syntax-level transaction validation.  The pipeline subsequently
    recompiles the merged artifact and independently compares the executable
    semantics of every preserved subtask, so text tricks cannot mutate a
    certified prefix unnoticed.
    """

    preserved = [int(value) for value in preserved_subtask_indices]
    repair = [int(value) for value in repair_subtask_indices]
    expected_all = [*preserved, *repair]
    errors: List[str] = []
    if not repair:
        errors.append("Repair suffix must contain at least one subtask")
    if len(set(expected_all)) != len(expected_all):
        errors.append("Preserved and repair subtask IDs must be unique")

    mappings = list(_MAPPING_BLOCK_RE.finditer(candidate_output or ""))
    if len(mappings) != 1:
        errors.append("Stored hierarchy candidate must have one mapping block")
    if _MAPPING_BLOCK_RE.search(patch_output or ""):
        errors.append("Localized patch must not redefine the frozen mapping block")

    candidate_matches = list(_SUBTASK_BLOCK_RE.finditer(candidate_output or ""))
    candidate_ids = [int(match.group("index")) for match in candidate_matches]
    if candidate_ids != expected_all:
        errors.append(
            f"Stored candidate blocks must be exactly {expected_all} in order; "
            f"got {candidate_ids}"
        )

    patch_matches = list(_SUBTASK_BLOCK_RE.finditer(patch_output or ""))
    patch_ids = [int(match.group("index")) for match in patch_matches]
    if patch_ids != repair:
        errors.append(
            f"Localized patch blocks must be exactly {repair} in order; got "
            f"{patch_ids}"
        )
    leftover = _strip_spans(
        patch_output or "", [match.span() for match in patch_matches]
    )
    if leftover.strip().strip("`").strip():
        errors.append("Localized patch contains text outside numbered blocks")
    if errors:
        return ArtifactCheck.rejected(*errors)

    candidate_bodies = {
        int(match.group("index")): match.group("body").strip()
        for match in candidate_matches
    }
    patch_bodies = {
        int(match.group("index")): match.group("body").strip()
        for match in patch_matches
    }
    blocks = [
        _render_subtask_block(
            index,
            patch_bodies[index] if index in patch_bodies else candidate_bodies[index],
        )
        for index in expected_all
    ]
    mapping = mappings[0].group(0).strip()
    return ArtifactCheck.accepted(mapping + "\n\n" + "\n\n".join(blocks))


def _safe_text_list(value: object) -> List[str]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        return []
    return [lexicon._model_safe_evaluator_text(str(item)) for item in value]


def _entry_state(
    adapter: object,
    task: object,
    current_state: object,
    projection: object,
    preserved_subtask_indices: Sequence[int],
) -> object:
    if not preserved_subtask_indices:
        return adapter.snapshot_state(task, current_state)
    preserved = set(int(value) for value in preserved_subtask_indices)
    projected = [
        item
        for item in getattr(projection, "subtasks", ())
        if int(getattr(getattr(item, "plan", None), "index", -1)) in preserved
    ]
    if not projected:
        return adapter.snapshot_state(task, current_state)
    return adapter.snapshot_state(task, projected[-1].projected_state)


def _flat_checkpoint_state(task: object, text: object) -> ArtifactCheck:
    """Parse a Flat-Hanoi checkpoint into the adapter's exact stack state."""

    try:
        payload = json.loads(str(text))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        return ArtifactCheck.rejected(f"Flat checkpoint JSON: {error}")
    if not isinstance(payload, Mapping):
        return ArtifactCheck.rejected("Flat checkpoint must be a JSON object")

    pegs = [str(value) for value in getattr(task, "pegs", ())]
    ring_objects = list(getattr(task, "rings", ()))
    ring_names = [str(getattr(ring, "name", "")) for ring in ring_objects]
    sizes = {
        str(getattr(ring, "name", "")): int(getattr(ring, "size", 0))
        for ring in ring_objects
    }
    state: Dict[str, List[str]] = {peg: [] for peg in pegs}

    if set(payload) == set(pegs):
        for peg in pegs:
            stack = payload.get(peg)
            if not isinstance(stack, list) or not all(
                isinstance(value, str) for value in stack
            ):
                return ArtifactCheck.rejected(
                    f"Flat checkpoint {peg!r} must be a list of ring names"
                )
            state[peg] = list(stack)
    else:
        relations = payload.get("spatial_relations")
        if not isinstance(relations, Mapping):
            return ArtifactCheck.rejected(
                "Flat checkpoint must be either exact peg stacks or a scene "
                "object with spatial_relations"
            )
        for ring in ring_names:
            raw_relations = relations.get(f"<{ring}>", relations.get(ring))
            if not isinstance(raw_relations, Sequence) or isinstance(
                raw_relations, (str, bytes, bytearray)
            ):
                return ArtifactCheck.rejected(
                    f"Flat checkpoint has no relations for {ring}"
                )
            locations = []
            for value in raw_relations:
                match = re.fullmatch(r"in\(<([^>]+)>\)", str(value).strip())
                if match and match.group(1) in state:
                    locations.append(match.group(1))
            if len(locations) != 1:
                return ArtifactCheck.rejected(
                    f"Flat checkpoint must place {ring} on exactly one peg"
                )
            state[locations[0]].append(ring)
        for peg in pegs:
            state[peg].sort(key=lambda ring: sizes[ring], reverse=True)
        expected_relations = build_scene_description(task, state).get(
            "spatial_relations", {}
        )
        for key, expected in expected_relations.items():
            observed = relations.get(key)
            if observed is None or set(map(str, observed)) != set(map(str, expected)):
                return ArtifactCheck.rejected(
                    f"Flat checkpoint spatial relations differ for {key}"
                )

    flattened = [ring for peg in pegs for ring in state[peg]]
    if sorted(flattened) != sorted(ring_names) or len(flattened) != len(
        set(flattened)
    ):
        return ArtifactCheck.rejected(
            "Flat checkpoint must place every known ring exactly once"
        )
    for peg, stack in state.items():
        if any(
            sizes[lower] <= sizes[upper]
            for lower, upper in zip(stack, stack[1:])
        ):
            return ArtifactCheck.rejected(
                f"Flat checkpoint has an illegal size order on {peg}"
            )
    return ArtifactCheck.accepted(state)


class VerifiedRepairLexiconNLevelAdapter(SelectiveLexiconNLevelAdapter):
    """Stateless-controller LexiCon hooks with v4's verified no-op compiler.

    A short-lived v4 helper supplies its deterministic ``CheckpointNoOp``
    compiler; the long-lived v5 adapter has no v4 controller state.  V5 owns
    repair and deterministic-verdict authority in its generic controller.
    """

    pipeline_version = PIPELINE_VERSION
    checkpoint_local_repair_limit = 2
    repair_backtrack_after = 2

    def states_equivalent(
        self, task: object, left: object, right: object
    ) -> bool:
        del task
        # LexiconExecutionState equality includes executed actions, public
        # fluents, private temporal-monitor fluents, and their digest.
        return bool(left == right)

    def hierarchy_request(self, *args: object, **kwargs: object) -> StageRequest:
        request = SelectiveLexiconNLevelAdapter.hierarchy_request(
            self, *args, **kwargs
        )
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
        # V4's compiler increments an adapter-local diagnostic counter.  Run
        # it on an ephemeral helper so a reusable v5 adapter remains free of
        # repair/controller state across rollouts.
        compiler = PrefixRepairLexiconNLevelAdapter()
        return compiler._compile_with_noops(
            task, h1_output, decision, hierarchy_output
        )


    def validate_projected_subtask(
        self,
        task: object,
        decision: object,
        subtask: object,
        projected_state: object,
        is_last: bool,
    ) -> ArtifactCheck:
        # This is the only other v4 behavior retained: it annotates verified
        # no-ops and maps any private monitor name to released constraint text.
        helper = PrefixRepairLexiconNLevelAdapter()
        return helper.validate_projected_subtask(
            task, decision, subtask, projected_state, is_last
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
        public = lexicon._projection_payload(projection)
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
            certificate["checkpoint"] = {
                "required_true": _safe_text_list(
                    checkpoint.get("required_true", [])
                ),
                "required_false": _safe_text_list(
                    checkpoint.get("required_false", [])
                ),
                "constraints_addressed": [
                    value
                    for value in checkpoint.get("constraints_addressed", [])
                    if isinstance(value, int) and not isinstance(value, bool)
                ]
                if isinstance(
                    checkpoint.get("constraints_addressed", []), Sequence
                )
                else [],
            }
        violated = _public_temporal_failures(
            task, metadata.get("unsatisfied_conditions", [])
        )
        if violated:
            certificate["violated_temporal_constraints"] = violated
        certificate["preserved_subtask_indices"] = [
            int(value) for value in preserved_subtask_indices
        ]
        certificate["repair_subtask_indices"] = [
            int(value) for value in repair_subtask_indices
        ]
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
            system=SYSTEM_VERIFIED_REPAIR_LEXICON,
            prompt=f"""Repair only the failed hierarchy subtask and its suffix.

Earlier checkpoint-valid blocks {list(preserved_subtask_indices)} and the
mapping block are frozen by the controller. Do not reproduce or modify them.

LEXICON TASK:
{lexicon._model_task_text(task)}

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


class VerifiedRepairFlatHanoiNLevelAdapter(SelectiveFlatHanoiNLevelAdapter):
    """Flat-Hanoi v5 hooks with strict hierarchy and checkpoint contracts."""

    pipeline_version = PIPELINE_VERSION
    checkpoint_local_repair_limit = 2
    repair_backtrack_after = 2

    def states_equivalent(
        self, task: object, left: object, right: object
    ) -> bool:
        return self.copy_state(task, left) == self.copy_state(task, right)

    def parse_decision(self, task: object, output: str) -> ArtifactCheck:
        base = super().parse_decision(task, output)
        if not base.valid or not isinstance(base.value, Sequence):
            return base
        parsed: List[Dict[str, object]] = []
        errors: List[str] = []
        for item in base.value:
            if not isinstance(item, Mapping):
                errors.append("Flat Decision contains a non-object subtask")
                continue
            index = item.get("subtask_index")
            checkpoint = _flat_checkpoint_state(task, item.get("goal_state_text", ""))
            if not checkpoint.valid:
                errors.extend(
                    f"Subtask {index} checkpoint: {error}"
                    for error in checkpoint.errors
                )
                continue
            enriched = dict(item)
            enriched["v5_checkpoint_state"] = checkpoint.value
            parsed.append(enriched)
        if parsed and parsed[-1].get("v5_checkpoint_state") != getattr(
            task, "goal", None
        ):
            errors.append("Final Flat Decision checkpoint must equal the task goal")
        if errors:
            return ArtifactCheck.rejected(*errors)
        return ArtifactCheck.accepted(tuple(parsed))

    def compile_hierarchy(
        self,
        task: object,
        state: object,
        h1_output: str,
        decision_output: str,
        decision: Sequence[Mapping[str, object]],
        hierarchy_output: str,
    ) -> ArtifactCheck:
        """Require the same transaction grammar used by suffix merging."""

        errors: List[str] = []
        mapping_matches = list(_MAPPING_BLOCK_RE.finditer(hierarchy_output or ""))
        if len(mapping_matches) != 1:
            errors.append(
                "V5 Flat hierarchy must contain exactly one mapping block"
            )
        subtask_matches = list(_SUBTASK_BLOCK_RE.finditer(hierarchy_output or ""))
        actual_ids = [int(match.group("index")) for match in subtask_matches]
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

        for match in subtask_matches:
            body = match.group("body")
            calls = list(CALL_PATTERN.finditer(body))
            residue = _strip_spans(body, [call.span() for call in calls])
            if not calls or re.sub(r"[\s,;]", "", residue):
                errors.append(
                    "V5 Flat hierarchy subtask "
                    f"{match.group('index')} must contain only function calls"
                )

        allowed_spans = [match.span() for match in mapping_matches]
        allowed_spans.extend(match.span() for match in subtask_matches)
        flag_matches = list(_FLAG_BLOCK_RE.finditer(hierarchy_output or ""))
        if len(flag_matches) > 1:
            errors.append("V5 Flat hierarchy may contain at most one code block")
        allowed_spans.extend(match.span() for match in flag_matches)
        leftover = _strip_spans(hierarchy_output or "", allowed_spans)
        if leftover.strip().strip("`").strip():
            errors.append("V5 Flat hierarchy contains text outside declared blocks")

        if len(mapping_matches) == 1:
            h1_mappings, h1_errors = parse_mappings(h1_output)
            custom_mappings, custom_errors = parse_mappings(
                mapping_matches[0].group(0)
            )
            errors.extend(f"V5 Flat H1: {error}" for error in h1_errors)
            errors.extend(
                f"V5 Flat hierarchy mapping: {error}" for error in custom_errors
            )
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
        return super().compile_hierarchy(
            task,
            state,
            h1_output,
            decision_output,
            decision,
            hierarchy_output,
        )

    def validate_projected_subtask(
        self,
        task: object,
        decision: Sequence[Mapping[str, object]],
        subtask: object,
        projected_state: object,
        is_last: bool,
    ) -> ArtifactCheck:
        del is_last
        index = int(getattr(subtask, "index", -1))
        matching = [
            item
            for item in decision
            if isinstance(item, Mapping) and item.get("subtask_index") == index
        ]
        if len(matching) != 1:
            return ArtifactCheck.rejected(
                f"No unique Flat Decision checkpoint for subtask {index}"
            )
        expected = matching[0].get("v5_checkpoint_state")
        observed = self.copy_state(task, projected_state)
        if expected != observed:
            return ArtifactCheck.rejected(
                f"Subtask {index} does not satisfy its exact Flat checkpoint",
                metadata={
                    "expected_checkpoint": expected,
                    "observed_state": observed,
                },
            )
        return ArtifactCheck.accepted(
            observed,
            metadata={"checkpoint_state": expected},
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
        failed_action = getattr(projection, "failed_action", None)
        return {
            "valid": bool(getattr(projection, "valid", False)),
            "reason": str(getattr(projection, "reason", "N/A")),
            "failed_subtask_index": getattr(
                projection, "failed_subtask_index", None
            ),
            "failed_action_index": getattr(
                projection, "failed_action_index", None
            ),
            "failed_action": (
                self.format_action(failed_action)
                if failed_action is not None
                else None
            ),
            "checkpoint_failure": bool(
                getattr(projection, "checkpoint_failure", False)
            ),
            "prefix_certificate_semantics": (
                "exact legal deterministic transition prefix with a parsed "
                "and exactly matched Decision checkpoint"
            ),
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
            "preserved_subtask_indices": [
                int(value) for value in preserved_subtask_indices
            ],
            "repair_subtask_indices": [
                int(value) for value in repair_subtask_indices
            ],
        }

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
        del current_state, include_code_block
        return StageRequest(
            stage="hierarchy_planner",
            system=SYSTEM_VERIFIED_REPAIR_HANOI,
            prompt=f"""Repair only the failed Flat Hanoi hierarchy suffix.

Earlier deterministic-transition-valid blocks {list(preserved_subtask_indices)}
and the mapping block are frozen. Do not reproduce or modify them.

TASK: {getattr(task, 'id', 'flat-hanoi')}
CURRENT SCENE:
{json.dumps(scene, indent=2, sort_keys=True)}

STATE/GOAL DESCRIPTION:
{state_output}

VERIFIED H1 MAPPING:
{h1_output}

DECISIONBOT PLAN:
{decision_output}

PREVIOUS COMPILED HIERARCHY:
{candidate_output}

DETERMINISTIC FAILURE CERTIFICATE:
{json.dumps(dict(certificate), indent=2, sort_keys=True)}

STAGE-LOCAL FEEDBACK:
{feedback or 'N/A'}

Return exactly these numbered blocks in this order:
{list(repair_subtask_indices)}
Do not return a mapping block, frozen prefix, prose, pseudocode, or Markdown
outside those blocks. Calls must resolve through the frozen mappings/H1.
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
                + "\n\nDETERMINISTIC FAILURE CERTIFICATE:\n"
                + json.dumps(dict(certificate), indent=2, sort_keys=True)
                + "\nRevise only the subtask/checkpoint plan. Return no "
                "actions/function calls.\n"
            ),
        )


__all__ = [
    "SYSTEM_VERIFIED_REPAIR_HANOI",
    "SYSTEM_VERIFIED_REPAIR_LEXICON",
    "VerifiedRepairFlatHanoiNLevelAdapter",
    "VerifiedRepairLexiconNLevelAdapter",
    "merge_numbered_suffix",
]
