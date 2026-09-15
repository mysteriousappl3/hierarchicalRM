"""Small, syntax-safe repair helpers for DynaPlan v1.1.

The shared v5 controller already knows how to merge a hierarchy suffix.  This
module supplies the corresponding DecisionBot block transaction and converts
the existing InnerBot audit record into an explicitly *unverified*
localization certificate.  It never evaluates action semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re
from typing import Mapping, Optional, Sequence, Tuple

from shared_nlevel_pipeline import ArtifactCheck, StageRequest


LOCALIZED_REPAIR_REVISION = "dynaplan_audit_guided_suffix_repair_v1"

_DESCRIPTION_RE = re.compile(
    r"(?<![A-Za-z0-9_\x60])(?P<fence>```)?start_subtask_"
    r"(?P<index>\d+)\b\s*(?P<body>.*?)\s*"
    r"(?(fence)```|(?<!\x60))end_subtask_(?P=index)\b(?!\x60)",
    re.DOTALL,
)
_CHECKPOINT_RE = re.compile(
    r"(?<![A-Za-z0-9_\x60])(?P<fence>```)?start_subtask_goalstate_"
    r"(?P<index>\d+)\b\s*(?P<body>.*?)\s*"
    r"(?(fence)```|(?<!\x60))end_subtask_goalstate_(?P=index)\b(?!\x60)",
    re.DOTALL,
)
_SUBTASK_ERROR_RE = re.compile(r"\bSubtask\s+(?P<index>\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class DecisionSuffixSpec:
    """One complete Decision output split at its earliest localized error."""

    failed_subtask_index: int
    preserved_subtask_indices: Tuple[int, ...]
    repair_subtask_indices: Tuple[int, ...]


def _numbered_blocks(
    text: str,
) -> Optional[Tuple[dict[int, str], dict[int, str], Tuple[int, ...]]]:
    descriptions: dict[int, str] = {}
    checkpoints: dict[int, str] = {}
    for match in _DESCRIPTION_RE.finditer(text or ""):
        index = int(match.group("index"))
        if index in descriptions:
            return None
        descriptions[index] = match.group(0).strip()
    for match in _CHECKPOINT_RE.finditer(text or ""):
        index = int(match.group("index"))
        if index in checkpoints:
            return None
        checkpoints[index] = match.group(0).strip()
    indices = tuple(sorted(set(descriptions) | set(checkpoints)))
    if not indices or indices != tuple(range(indices[0], indices[-1] + 1)):
        return None
    if set(descriptions) != set(checkpoints):
        return None
    return descriptions, checkpoints, indices


def decision_suffix_spec(
    candidate_output: str,
    errors: Sequence[str],
) -> Optional[DecisionSuffixSpec]:
    """Locate a safe Decision suffix only when every error names a subtask.

    Global numbering, missing-block, truncation, and final-plan errors are not
    guessed at.  Those continue through the established full-regeneration
    path.
    """

    if not errors:
        return None
    error_indices = []
    for error in errors:
        match = _SUBTASK_ERROR_RE.search(str(error))
        if match is None:
            return None
        error_indices.append(int(match.group("index")))
    blocks = _numbered_blocks(candidate_output)
    if blocks is None:
        return None
    _descriptions, _checkpoints, indices = blocks
    if indices[0] != 1:
        return None
    failed = min(error_indices)
    if failed not in indices:
        return None
    return DecisionSuffixSpec(
        failed_subtask_index=failed,
        preserved_subtask_indices=tuple(index for index in indices if index < failed),
        repair_subtask_indices=tuple(index for index in indices if index >= failed),
    )


def _strip_spans(text: str, spans: Sequence[Tuple[int, int]]) -> str:
    pieces = []
    cursor = 0
    for start, end in sorted(spans):
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def merge_decision_suffix(
    candidate_output: str,
    patch_output: str,
    preserved_subtask_indices: Sequence[int],
    repair_subtask_indices: Sequence[int],
) -> ArtifactCheck[str]:
    """Merge exact numbered Decision blocks while preserving the prefix."""

    preserved = tuple(int(value) for value in preserved_subtask_indices)
    repair = tuple(int(value) for value in repair_subtask_indices)
    expected = (*preserved, *repair)
    errors = []
    candidate = _numbered_blocks(candidate_output)
    patch = _numbered_blocks(patch_output)
    if not repair:
        errors.append("Decision repair suffix must contain at least one subtask")
    if len(set(expected)) != len(expected):
        errors.append("Preserved and repaired Decision IDs must be unique")
    if candidate is None:
        errors.append("Stored Decision candidate lacks complete numbered blocks")
    elif candidate[2] != expected:
        errors.append(
            f"Stored Decision blocks must be exactly {list(expected)}; "
            f"got {list(candidate[2])}"
        )
    if patch is None:
        errors.append("Decision patch lacks complete numbered blocks")
    elif patch[2] != repair:
        errors.append(
            f"Decision patch blocks must be exactly {list(repair)}; "
            f"got {list(patch[2])}"
        )
    patch_matches = [
        *_DESCRIPTION_RE.finditer(patch_output or ""),
        *_CHECKPOINT_RE.finditer(patch_output or ""),
    ]
    leftover = _strip_spans(
        patch_output or "", [match.span() for match in patch_matches]
    )
    if leftover.strip().strip("`").strip():
        errors.append("Decision patch contains text outside numbered blocks")
    if errors:
        return ArtifactCheck.rejected(*errors)

    assert candidate is not None and patch is not None
    candidate_descriptions, candidate_checkpoints, _ = candidate
    patch_descriptions, patch_checkpoints, _ = patch
    rendered = []
    for index in expected:
        if index in preserved:
            rendered.extend(
                (candidate_descriptions[index], candidate_checkpoints[index])
            )
        else:
            rendered.extend((patch_descriptions[index], patch_checkpoints[index]))
    return ArtifactCheck.accepted("\n\n".join(rendered))


def decision_suffix_request(
    base_request: StageRequest,
    *,
    candidate_output: str,
    certificate: Mapping[str, object],
    preserved_subtask_indices: Sequence[int],
    repair_subtask_indices: Sequence[int],
) -> StageRequest:
    """Turn the normal Decision request into an exact suffix-patch request."""

    return replace(
        base_request,
        prompt=(
            base_request.prompt.rstrip()
            + "\n\nDYNAPLAN LOCALIZED DECISION SUFFIX REPAIR\n"
            + "The controller will preserve these earlier blocks exactly: "
            + json.dumps(list(preserved_subtask_indices))
            + "\nReturn ONLY complete description and goalstate block pairs for "
            + "these IDs, in order: "
            + json.dumps(list(repair_subtask_indices))
            + "\nDo not repeat the preserved prefix and do not include prose, "
            + "Markdown, mappings, or function calls outside the requested blocks."
            + "\n\nPREVIOUS NORMALIZED DECISION:\n"
            + candidate_output
            + "\n\nLOCALIZED FAILURE CERTIFICATE:\n"
            + json.dumps(dict(certificate), indent=2, sort_keys=True)
        ),
    )


def audit_localization(
    record: Mapping[str, object], owner: str
) -> Optional[dict[str, object]]:
    """Return only a well-formed, evidence-complete LLM audit localization."""

    if (
        record.get("raw_verdict") != "INVALID"
        or record.get("effective_verdict") != "INVALID"
        or record.get("parse_valid") is not True
        or record.get("coverage_guard_passed") is not True
        or record.get("requirement_evidence_guard_passed") is False
    ):
        return None
    try:
        subtask = int(record["first_bad_subtask"])
        action = int(record["first_bad_action_in_subtask"])
    except (KeyError, TypeError, ValueError):
        return None
    if subtask <= 0 or action < 0 or owner not in {
        "decision",
        "hierarchy",
        "both",
    }:
        return None
    return {
        "certificate_source": "llm_execution_audit",
        "semantic_verification": "WITHHELD",
        "first_bad_subtask": subtask,
        "first_bad_action_in_subtask": action,
        "owner": owner,
        "reason": str(record.get("reason") or "N/A"),
        "prefix_status": "audit-cleared-but-unverified",
        "mandatory_full_candidate_recheck": True,
        "localized_repair_revision": LOCALIZED_REPAIR_REVISION,
    }


__all__ = [
    "DecisionSuffixSpec",
    "LOCALIZED_REPAIR_REVISION",
    "audit_localization",
    "decision_suffix_request",
    "decision_suffix_spec",
    "merge_decision_suffix",
]
