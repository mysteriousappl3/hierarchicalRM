"""Offline tests for the opt-in DynaPlan exhaustion fallback."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


RUNTIME_ROOT = Path(__file__).resolve().parent / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from dynaplan_nlevel_exhaustion_fallback import (  # noqa: E402
    UNCERTIFIED_FALLBACK,
    ExhaustionCandidatePool,
)


def _audit(
    *,
    bad_subtask: int = 2,
    bad_action: int = 2,
    checkpoints: int = 1,
    outstanding: int = 1,
    verdict: str = "INVALID",
):
    return {
        "verdict": verdict,
        "first_bad_subtask": 0 if verdict == "VALID" else bad_subtask,
        "first_bad_action_in_subtask": (
            0 if verdict == "VALID" else bad_action
        ),
        "coverage": {
            "checked_checkpoints": checkpoints,
        },
        "outstanding_requirements": [
            f"requirement-{index}" for index in range(outstanding)
        ],
    }


def _consider(
    pool: ExhaustionCandidatePool,
    *,
    serial: int,
    audit=None,
    action_count: int = 6,
    structurally_valid: bool = True,
    fully_expanded: bool = True,
    raw: str = '{"verdict":"INVALID"}',
):
    actions = tuple(f"action-{serial}-{index}" for index in range(action_count))
    first_count = action_count // 2
    counts = ((1, first_count), (2, action_count - first_count))
    return pool.consider(
        candidate_serial=serial,
        state_revision=0,
        structurally_valid=structurally_valid,
        fully_expanded=fully_expanded,
        final_state={"untrusted_shadow": serial},
        executed_actions=actions,
        high_level_plan=(f"H3-{serial}",),
        expanded_h0_plan=actions,
        canonical_actions=actions,
        score_context={"candidate": serial},
        outputs={"router_output": raw},
        raw_audit_certificate=raw,
        audit_record=audit or _audit(),
        subtask_action_counts=counts,
    )


def test_default_off_reproduces_no_fallback_behavior() -> None:
    pool = ExhaustionCandidatePool()

    assert _consider(pool, serial=1) is False
    assert pool.best_candidate() is None
    assert (
        pool.select_on_exhaustion(attempts_exhausted=True) is None
    )
    assert pool.telemetry()["exhaustion_candidate_fallback"] is False


@pytest.mark.parametrize(
    ("structurally_valid", "fully_expanded"),
    ((False, True), (True, False), (False, False)),
)
def test_only_structurally_valid_fully_expanded_candidates_are_retained(
    structurally_valid: bool,
    fully_expanded: bool,
) -> None:
    pool = ExhaustionCandidatePool(enabled=True)

    assert not _consider(
        pool,
        serial=1,
        structurally_valid=structurally_valid,
        fully_expanded=fully_expanded,
    )
    assert pool.best_candidate() is None


def test_ranking_uses_reported_progress_then_checkpoints_and_requirements() -> None:
    pool = ExhaustionCandidatePool(enabled=True)
    # Global failures are action 2, 5, 5, and 5 respectively.  The candidates
    # tied at action 5 are ordered by checkpoint count and then outstanding
    # requirement count.  No action meaning is inspected.
    _consider(
        pool,
        serial=1,
        audit=_audit(bad_subtask=1, bad_action=2, checkpoints=2, outstanding=0),
    )
    _consider(
        pool,
        serial=2,
        audit=_audit(bad_subtask=2, bad_action=2, checkpoints=1, outstanding=0),
    )
    _consider(
        pool,
        serial=3,
        audit=_audit(bad_subtask=2, bad_action=2, checkpoints=2, outstanding=2),
    )
    _consider(
        pool,
        serial=4,
        audit=_audit(bad_subtask=2, bad_action=2, checkpoints=2, outstanding=1),
    )

    best = pool.best_candidate()
    assert best is not None
    assert best.candidate_serial == 4
    assert best.audit_progress.first_bad_global_action == 5
    assert best.audit_progress.checkpoints_satisfied == 2
    assert best.audit_progress.outstanding_requirement_count == 1


def test_shortest_plan_is_final_quality_tiebreak_before_serial() -> None:
    pool = ExhaustionCandidatePool(enabled=True)
    # VALID-shaped but guard-rejected certificates have no reported bad action;
    # their progress is normalized to one position beyond their own terminal
    # trace.  Use local failures at the same global position to isolate length.
    same_progress = _audit(
        bad_subtask=1,
        bad_action=2,
        checkpoints=1,
        outstanding=1,
    )
    _consider(pool, serial=1, audit=same_progress, action_count=8)
    _consider(pool, serial=2, audit=same_progress, action_count=6)

    best = pool.best_candidate()
    assert best is not None
    assert best.candidate_serial == 2
    assert best.action_count == 6


def test_valid_claim_rejected_by_later_guard_has_terminal_plus_one_progress() -> None:
    pool = ExhaustionCandidatePool(enabled=True)
    raw = '{"verdict":"VALID","latest_trigger_state":17}'
    _consider(
        pool,
        serial=1,
        audit=_audit(verdict="VALID", checkpoints=2, outstanding=0),
        raw=raw,
    )

    best = pool.best_candidate()
    assert best is not None
    assert best.audit_progress.first_bad_global_action == 7
    assert best.raw_audit_certificate == raw


def test_fallback_activates_only_after_exhaustion_and_is_one_shot() -> None:
    pool = ExhaustionCandidatePool(enabled=True)
    _consider(pool, serial=1)

    assert pool.select_on_exhaustion(attempts_exhausted=False) is None
    selected = pool.select_on_exhaustion(attempts_exhausted=True)
    assert selected is not None
    assert selected.status == UNCERTIFIED_FALLBACK
    assert selected.telemetry()["semantic_certification"] is False
    with pytest.raises(RuntimeError, match="already taken"):
        pool.select_on_exhaustion(attempts_exhausted=True)


def test_accepted_candidate_can_never_be_replaced_by_fallback() -> None:
    pool = ExhaustionCandidatePool(enabled=True)
    _consider(pool, serial=1)
    pool.mark_accepted()

    assert pool.select_on_exhaustion(attempts_exhausted=True) is None
    assert pool.telemetry()["exhaustion_fallback_accepted_plan_guard"] is True


def test_explicit_downstream_rejection_discards_candidate() -> None:
    pool = ExhaustionCandidatePool(enabled=True)
    _consider(pool, serial=1)

    assert pool.discard(1) is True
    assert pool.discard(1) is False
    assert pool.best_candidate() is None
    assert pool.select_on_exhaustion(attempts_exhausted=True) is None
    assert pool.telemetry()["exhaustion_fallback_discarded_count"] == 1


def test_explicit_accepted_incumbent_guard_prevents_selection() -> None:
    pool = ExhaustionCandidatePool(enabled=True)
    _consider(pool, serial=1)

    assert (
        pool.select_on_exhaustion(
            attempts_exhausted=True,
            accepted_candidate_exists=True,
        )
        is None
    )


def test_component_never_calls_model_simulator_or_official_evaluator() -> None:
    calls = {"official": 0}

    def official_evaluator(candidate) -> bool:
        calls["official"] += 1
        return bool(candidate.canonical_actions)

    pool = ExhaustionCandidatePool(enabled=True)
    _consider(pool, serial=1)
    selected = pool.select_on_exhaustion(attempts_exhausted=True)

    # Selection itself is pure bookkeeping.  The owning pipeline makes its
    # existing single terminal evaluator call after restoring the snapshot.
    assert calls["official"] == 0
    assert selected is not None
    assert official_evaluator(selected.candidate) is True
    assert calls["official"] == 1
    telemetry = pool.telemetry()
    assert telemetry["exhaustion_fallback_semantic_authority"] is False
    assert telemetry["exhaustion_fallback_evaluator_calls"] == 0


def test_inconsistent_structural_snapshot_fails_closed() -> None:
    pool = ExhaustionCandidatePool(enabled=True)
    with pytest.raises(ValueError, match="cover every canonical action"):
        pool.consider(
            candidate_serial=1,
            state_revision=0,
            structurally_valid=True,
            fully_expanded=True,
            final_state={},
            executed_actions=("a", "b"),
            high_level_plan=("H2",),
            expanded_h0_plan=("a", "b"),
            canonical_actions=("a", "b"),
            score_context={},
            outputs={},
            raw_audit_certificate="{}",
            audit_record={},
            subtask_action_counts=((1, 1),),
        )
