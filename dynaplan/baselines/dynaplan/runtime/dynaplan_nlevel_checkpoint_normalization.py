"""Conservative, domain-neutral Decision checkpoint-tag normalization.

This module repairs only the observed syntax slip where a uniquely delimited
``start_subtask_goalstate_N`` block is closed with ``end_subtask_N``.  It does
not edit checkpoint bodies, infer missing blocks, renumber subtasks, or relax
the downstream Decision validators.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Dict, List, Tuple


NORMALIZATION_REVISION = "dynaplan_safe_checkpoint_closer_normalization_v1"

_MARKER_LINE_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<fence>```)?"
    r"(?P<kind>start_subtask_goalstate|end_subtask_goalstate|"
    r"start_subtask|end_subtask)_(?P<index>\d+)"
    r"(?P<trailing>[ \t]*)(?P<carriage>\r?)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class _Marker:
    kind: str
    index: int
    fence: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class DecisionNormalization:
    """A syntax-only normalization result with an auditable repair list."""

    raw_output: str
    normalized_output: str
    repaired_ids: Tuple[int, ...]

    @property
    def repair_count(self) -> int:
        return len(self.repaired_ids)

    @property
    def changed(self) -> bool:
        return self.normalized_output != self.raw_output

    @property
    def raw_sha256(self) -> str:
        return hashlib.sha256(self.raw_output.encode("utf-8")).hexdigest()

    @property
    def normalized_sha256(self) -> str:
        return hashlib.sha256(
            self.normalized_output.encode("utf-8")
        ).hexdigest()


def _markers(text: str) -> List[_Marker]:
    return [
        _Marker(
            kind=match.group("kind"),
            index=int(match.group("index")),
            fence=match.group("fence") or "",
            start=match.start(),
            end=match.end(),
            text=match.group(0),
        )
        for match in _MARKER_LINE_RE.finditer(text)
    ]


def normalize_decision_checkpoint_closers(output: str) -> DecisionNormalization:
    """Repair only structurally unique short goal-state closing markers.

    For an ID to qualify, its complete marker sequence must be exactly:

    ``start_subtask_N, end_subtask_N, start_subtask_goalstate_N, end_subtask_N``

    The first short closer is therefore the legitimate description closer and
    the second is unambiguously the malformed goal-state closer.  Any correct
    goal-state closer, duplicate opener, reordered marker, non-line marker, or
    fence-style mismatch makes that ID ineligible.  Eligible replacements are
    applied from right to left, changing only the marker name.
    """

    raw = output if isinstance(output, str) else ""
    markers = _markers(raw)
    by_id: Dict[int, List[_Marker]] = {}
    for marker in markers:
        by_id.setdefault(marker.index, []).append(marker)

    replacements: List[Tuple[int, int, str]] = []
    repaired_ids: List[int] = []
    expected = (
        "start_subtask",
        "end_subtask",
        "start_subtask_goalstate",
        "end_subtask",
    )
    for index, same_id in sorted(by_id.items()):
        if tuple(marker.kind for marker in same_id) != expected:
            continue
        description_start, description_end, goal_start, malformed_end = same_id
        if description_start.fence != description_end.fence:
            continue
        if goal_start.fence != malformed_end.fence:
            continue
        replacement = malformed_end.text.replace(
            f"end_subtask_{index}",
            f"end_subtask_goalstate_{index}",
            1,
        )
        if replacement == malformed_end.text:
            continue
        replacements.append((malformed_end.start, malformed_end.end, replacement))
        repaired_ids.append(index)

    normalized = raw
    for start, end, replacement in reversed(replacements):
        normalized = normalized[:start] + replacement + normalized[end:]
    return DecisionNormalization(raw, normalized, tuple(repaired_ids))


__all__ = [
    "DecisionNormalization",
    "NORMALIZATION_REVISION",
    "normalize_decision_checkpoint_closers",
]
