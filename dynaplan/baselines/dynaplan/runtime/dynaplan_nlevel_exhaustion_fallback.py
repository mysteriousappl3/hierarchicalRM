"""Oracle-free exhaustion fallback for DynaPlan candidates.

This module contains only controller bookkeeping.  It does not execute an
action, inspect a domain predicate, call a model, or invoke the official
evaluator.  A caller may retain a candidate here only after the ordinary
compiler has established that the hierarchy is structurally valid and fully
expanded.  That structural fact is deliberately *not* treated as semantic
proof.

The pool is disabled by default so importing it cannot change the registered
DynaPlan v1.2 behavior.  An opted-in controller may submit the best retained
candidate only after its complete attempt budget is exhausted and only when no
candidate was previously accepted.  Such a selection is always labelled
``UNCERTIFIED_FALLBACK``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


EXHAUSTION_FALLBACK_REVISION = "dynaplan_exhaustion_candidate_fallback_v1"
UNCERTIFIED_FALLBACK = "UNCERTIFIED_FALLBACK"


def _non_negative_integer(value: object) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _canonical_subtask_counts(
    values: Sequence[Tuple[int, int]],
) -> Tuple[Tuple[int, int], ...]:
    result = []
    seen = set()
    for raw_index, raw_count in values:
        index = _non_negative_integer(raw_index)
        count = _non_negative_integer(raw_count)
        if index is None or index == 0:
            raise ValueError("subtask indices must be positive integers")
        if count is None:
            raise ValueError("subtask action counts must be non-negative integers")
        if index in seen:
            raise ValueError(f"duplicate subtask index {index}")
        seen.add(index)
        result.append((index, count))
    return tuple(result)


def _global_failure_position(
    audit_record: Mapping[str, object],
    subtask_action_counts: Sequence[Tuple[int, int]],
) -> Optional[int]:
    """Translate an LLM-reported local failure into a structural trace index.

    A zero local action denotes a checkpoint/final-requirement failure at the
    end of the named subtask.  A rejected certificate whose raw verdict says
    ``VALID`` has no reported counterexample, so its structural progress is one
    position beyond the terminal action.  Neither case claims the report is
    semantically correct.
    """

    total_actions = sum(count for _, count in subtask_action_counts)
    if audit_record.get("verdict") == "VALID":
        return total_actions + 1

    failed_subtask = _non_negative_integer(
        audit_record.get("first_bad_subtask")
    )
    failed_action = _non_negative_integer(
        audit_record.get("first_bad_action_in_subtask")
    )
    if failed_subtask is None or failed_subtask == 0 or failed_action is None:
        return None

    prefix = 0
    for subtask_index, action_count in subtask_action_counts:
        if subtask_index != failed_subtask:
            prefix += action_count
            continue
        if failed_action > action_count:
            return None
        # Action zero means the boundary immediately after this subtask.
        return prefix + (failed_action if failed_action else action_count)
    return None


@dataclass(frozen=True)
class ReportedAuditProgress:
    """Untrusted, shape-only progress used to rank fallback candidates."""

    first_bad_global_action: Optional[int]
    checkpoints_satisfied: Optional[int]
    outstanding_requirement_count: Optional[int]

    @classmethod
    def from_audit_record(
        cls,
        audit_record: Mapping[str, object],
        subtask_action_counts: Sequence[Tuple[int, int]],
    ) -> "ReportedAuditProgress":
        counts = _canonical_subtask_counts(subtask_action_counts)
        coverage = audit_record.get("coverage")
        checked_checkpoints = None
        if isinstance(coverage, Mapping):
            checked_checkpoints = _non_negative_integer(
                coverage.get("checked_checkpoints")
            )

        outstanding = audit_record.get("outstanding_requirements")
        outstanding_count = (
            len(outstanding)
            if isinstance(outstanding, list)
            and all(isinstance(item, str) for item in outstanding)
            else None
        )
        return cls(
            first_bad_global_action=_global_failure_position(
                audit_record, counts
            ),
            checkpoints_satisfied=checked_checkpoints,
            outstanding_requirement_count=outstanding_count,
        )


@dataclass(frozen=True)
class ExhaustionFallbackCandidate:
    """Immutable-enough snapshot needed to restore one rejected candidate.

    ``final_state`` and ``score_context`` are opaque controller snapshots.  The
    pool never inspects them.  The caller remains responsible for taking any
    domain-appropriate copies before retention.
    """

    candidate_serial: int
    state_revision: int
    final_state: object
    executed_actions: Tuple[object, ...]
    high_level_plan: Tuple[str, ...]
    expanded_h0_plan: Tuple[str, ...]
    canonical_actions: Tuple[str, ...]
    score_context: object
    outputs: Mapping[str, object]
    raw_audit_certificate: str
    audit_progress: ReportedAuditProgress
    fingerprint: str

    @property
    def action_count(self) -> int:
        return len(self.canonical_actions)

    @property
    def ranking_key(self) -> Tuple[int, int, int, int, int, str]:
        """Return the preregisterable, deterministic non-semantic ranking.

        Higher is better: later reported failure, more reportedly checked
        checkpoints, fewer outstanding requirements, then shorter plan.  An
        earlier serial and the content fingerprint provide stable final
        tie-breaks without inspecting action meaning.
        """

        progress = self.audit_progress
        first_bad = (
            progress.first_bad_global_action
            if progress.first_bad_global_action is not None
            else -1
        )
        checkpoints = (
            progress.checkpoints_satisfied
            if progress.checkpoints_satisfied is not None
            else -1
        )
        # Missing evidence ranks below any concrete outstanding count.
        outstanding = (
            progress.outstanding_requirement_count
            if progress.outstanding_requirement_count is not None
            else 2**31 - 1
        )
        return (
            first_bad,
            checkpoints,
            -outstanding,
            -self.action_count,
            -self.candidate_serial,
            self.fingerprint,
        )


@dataclass(frozen=True)
class ExhaustionFallbackSelection:
    """One explicitly uncertified candidate selected at terminal exhaustion."""

    candidate: ExhaustionFallbackCandidate
    status: str = UNCERTIFIED_FALLBACK
    reason: str = (
        "Attempt budget exhausted without an accepted candidate; submitting "
        "the highest-ranked structurally complete rejected candidate."
    )

    def telemetry(self) -> Dict[str, object]:
        progress = self.candidate.audit_progress
        return {
            "status": self.status,
            "candidate_serial": self.candidate.candidate_serial,
            "candidate_fingerprint": self.candidate.fingerprint,
            "action_count": self.candidate.action_count,
            "reported_first_bad_global_action": (
                progress.first_bad_global_action
            ),
            "reported_checkpoints_satisfied": progress.checkpoints_satisfied,
            "reported_outstanding_requirement_count": (
                progress.outstanding_requirement_count
            ),
            "semantic_certification": False,
            "official_evaluator_called_by_fallback_component": False,
            "reason": self.reason,
        }


def _candidate_fingerprint(
    *,
    state_revision: int,
    canonical_actions: Sequence[str],
) -> str:
    payload = json.dumps(
        {
            "state_revision": state_revision,
            "canonical_actions": list(canonical_actions),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ExhaustionCandidatePool:
    """Rollout-local retention and one-shot exhaustion selection.

    The constructor's default is intentionally disabled.  ``consider`` only
    accepts a snapshot when both caller-provided structural guards are true.
    Selection is impossible before exhaustion and after ``mark_accepted``.
    """

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = bool(enabled)
        self._candidates: Dict[int, ExhaustionFallbackCandidate] = {}
        self._accepted_candidate_exists = False
        self._selection_taken = False
        self.considered_count = 0
        self.ineligible_count = 0
        self.retained_count = 0
        self.discarded_count = 0
        self.replaced_same_serial_count = 0

    def mark_accepted(self) -> None:
        """Permanently prevent this pool from replacing an accepted plan."""

        self._accepted_candidate_exists = True

    def discard(self, candidate_serial: int) -> bool:
        """Remove a candidate after an explicit downstream rejection.

        A structurally complete candidate is retained before its audit so a
        truncated final audit/review cannot erase it.  An actual OuterBot
        rejection remains authoritative for candidate selection and removes
        that snapshot rather than letting exhaustion fallback bypass the
        second line of defense.
        """

        removed = self._candidates.pop(candidate_serial, None) is not None
        if removed:
            self.discarded_count += 1
        return removed

    def consider(
        self,
        *,
        candidate_serial: int,
        state_revision: int,
        structurally_valid: bool,
        fully_expanded: bool,
        final_state: object,
        executed_actions: Sequence[object],
        high_level_plan: Sequence[str],
        expanded_h0_plan: Sequence[str],
        canonical_actions: Sequence[str],
        score_context: object,
        outputs: Mapping[str, object],
        raw_audit_certificate: str,
        audit_record: Mapping[str, object],
        subtask_action_counts: Sequence[Tuple[int, int]],
    ) -> bool:
        """Retain an eligible rejected candidate without evaluating semantics."""

        self.considered_count += 1
        if not self.enabled or not structurally_valid or not fully_expanded:
            self.ineligible_count += 1
            return False
        if (
            isinstance(candidate_serial, bool)
            or not isinstance(candidate_serial, int)
            or candidate_serial <= 0
        ):
            raise ValueError("candidate_serial must be a positive integer")
        if (
            isinstance(state_revision, bool)
            or not isinstance(state_revision, int)
            or state_revision < 0
        ):
            raise ValueError("state_revision must be a non-negative integer")
        if not isinstance(raw_audit_certificate, str):
            raise TypeError("raw_audit_certificate must be text")
        if not isinstance(outputs, Mapping) or not isinstance(
            audit_record, Mapping
        ):
            raise TypeError("outputs and audit_record must be mappings")

        canonical = tuple(str(item) for item in canonical_actions)
        actions = tuple(executed_actions)
        h0 = tuple(str(item) for item in expanded_h0_plan)
        if not canonical:
            raise ValueError("a fallback candidate must contain at least one action")
        if len(actions) != len(canonical):
            raise ValueError(
                "executed_actions and canonical_actions must have equal lengths"
            )
        counts = _canonical_subtask_counts(subtask_action_counts)
        if sum(count for _, count in counts) != len(canonical):
            raise ValueError(
                "subtask action counts must cover every canonical action exactly"
            )

        fingerprint = _candidate_fingerprint(
            state_revision=state_revision,
            canonical_actions=canonical,
        )
        retained = ExhaustionFallbackCandidate(
            candidate_serial=candidate_serial,
            state_revision=state_revision,
            final_state=final_state,
            executed_actions=actions,
            high_level_plan=tuple(str(item) for item in high_level_plan),
            expanded_h0_plan=h0,
            canonical_actions=canonical,
            score_context=score_context,
            outputs=deepcopy(dict(outputs)),
            raw_audit_certificate=raw_audit_certificate,
            audit_progress=ReportedAuditProgress.from_audit_record(
                audit_record, counts
            ),
            fingerprint=fingerprint,
        )

        existing = self._candidates.get(candidate_serial)
        if existing is not None and existing.fingerprint != fingerprint:
            raise ValueError(
                f"candidate serial {candidate_serial} identifies different traces"
            )
        if existing is None:
            self._candidates[candidate_serial] = retained
            self.retained_count += 1
            return True
        if retained.ranking_key > existing.ranking_key or (
            retained.ranking_key == existing.ranking_key
            and retained.raw_audit_certificate
            and not existing.raw_audit_certificate
        ):
            self._candidates[candidate_serial] = retained
            self.replaced_same_serial_count += 1
            return True
        return False

    def best_candidate(self) -> Optional[ExhaustionFallbackCandidate]:
        """Inspect the best retained snapshot without consuming selection."""

        if not self._candidates:
            return None
        return max(self._candidates.values(), key=lambda item: item.ranking_key)

    def select_on_exhaustion(
        self,
        *,
        attempts_exhausted: bool,
        accepted_candidate_exists: bool = False,
    ) -> Optional[ExhaustionFallbackSelection]:
        """Take the fallback once, strictly at exhausted terminal selection."""

        if not self.enabled or not attempts_exhausted:
            return None
        if self._accepted_candidate_exists or accepted_candidate_exists:
            return None
        if self._selection_taken:
            raise RuntimeError("exhaustion fallback selection was already taken")
        candidate = self.best_candidate()
        if candidate is None:
            return None
        self._selection_taken = True
        return ExhaustionFallbackSelection(candidate=candidate)

    def telemetry(self) -> Dict[str, Any]:
        best = self.best_candidate()
        return {
            "exhaustion_candidate_fallback": self.enabled,
            "exhaustion_candidate_fallback_revision": (
                EXHAUSTION_FALLBACK_REVISION
            ),
            "exhaustion_fallback_considered_count": self.considered_count,
            "exhaustion_fallback_ineligible_count": self.ineligible_count,
            "exhaustion_fallback_retained_count": self.retained_count,
            "exhaustion_fallback_discarded_count": self.discarded_count,
            "exhaustion_fallback_same_serial_update_count": (
                self.replaced_same_serial_count
            ),
            "exhaustion_fallback_accepted_plan_guard": (
                self._accepted_candidate_exists
            ),
            "exhaustion_fallback_selection_taken": self._selection_taken,
            "exhaustion_fallback_best_candidate_serial": (
                best.candidate_serial if best is not None else None
            ),
            "exhaustion_fallback_semantic_authority": False,
            "exhaustion_fallback_evaluator_calls": 0,
        }


__all__ = [
    "EXHAUSTION_FALLBACK_REVISION",
    "UNCERTIFIED_FALLBACK",
    "ReportedAuditProgress",
    "ExhaustionFallbackCandidate",
    "ExhaustionFallbackSelection",
    "ExhaustionCandidatePool",
]
