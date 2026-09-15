"""Focused regressions for opt-in irrelevant latest_* evidence tolerance.

These tests are offline: they exercise only the audit certificate guard and
make no model or evaluator calls.
"""

from __future__ import annotations

from copy import deepcopy
import json
import sys
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parent / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from dynaplan_nlevel_adapter import DynaPlanLexiconAdapter  # noqa: E402


class _LenientEvidenceAdapter(DynaPlanLexiconAdapter):
    lenient_irrelevant_evidence_fields = True


class _StrictEvidenceAdapter(DynaPlanLexiconAdapter):
    lenient_irrelevant_evidence_fields = False


def _row(
    requirement_id: str,
    obligation_type: str,
    *,
    terminal: int = 30,
    witnesses: list[int] | None = None,
    trigger: int | None = None,
    response: int | None = None,
    vacuous: bool = False,
) -> dict[str, object]:
    return {
        "requirement_id": requirement_id,
        "obligation_type": obligation_type,
        "satisfied": True,
        "evaluated_through_state": terminal,
        "witness_states": list(witnesses or []),
        "latest_trigger_state": trigger,
        "latest_response_state": response,
        "vacuous": vacuous,
        "evidence": f"Offline evidence for {requirement_id}.",
    }


def _payload(
    rows: list[dict[str, object]], *, terminal: int = 30
) -> dict[str, object]:
    return {
        "verdict": "VALID",
        "first_bad_subtask": 0,
        "first_bad_action_in_subtask": 0,
        "owner": "NA",
        "coverage": {
            "expected_actions": terminal,
            "checked_actions": terminal,
            "expected_checkpoints": 13,
            "checked_checkpoints": 13,
            "expected_final_requirements": len(rows),
            "checked_final_requirements": len(rows),
            "forward_check_complete": True,
            "backward_check_complete": True,
        },
        "final_state_facts": ["(at_ p1 l2_4)", "(at_ p2 l2_1)"],
        "outstanding_requirements": [],
        "reason": "All requirements checked.",
        "requirement_evidence": rows,
    }


def _prepare(adapter: DynaPlanLexiconAdapter, manifest: dict[str, str]) -> None:
    adapter._pending_audit_manifest = {
        "expected_actions": 30,
        "expected_checkpoints": 13,
        "expected_final_requirements": len(manifest),
    }
    adapter._pending_subtask_action_counts = {1: 30}
    adapter._pending_evidence_manifest = manifest


def _c3_id23_certificate() -> dict[str, object]:
    """Reproduce the obligation/evidence shape emitted by Haiku on c3-id23."""
    return _payload(
        [
            _row("goal_1", "final_goal", witnesses=[30]),
            _row("goal_2", "final_goal", witnesses=[30]),
            _row("constraint_1", "sometime", witnesses=[12]),
            _row(
                "constraint_2",
                "sometime_before",
                witnesses=[11, 12],
                trigger=12,
                response=11,
            ),
            _row("constraint_3", "sometime", witnesses=[23]),
            _row("constraint_4", "sometime", witnesses=[4]),
        ]
    )


_C3_ID23_MANIFEST = {
    "goal_1": "final_goal",
    "goal_2": "final_goal",
    "constraint_1": "sometime",
    "constraint_2": "sometime_before",
    "constraint_3": "sometime",
    "constraint_4": "sometime",
}


def test_feature_flag_off_preserves_v12_strict_rejection() -> None:
    adapter = _StrictEvidenceAdapter()
    _prepare(adapter, _C3_ID23_MANIFEST)

    verdict = adapter.parse_router(json.dumps(_c3_id23_certificate()))

    assert not verdict.no_mistake
    record = adapter.single_innerbot_audit_records[-1]
    assert record["lenient_irrelevant_evidence_fields"] is False
    assert record["requirement_evidence_guard_passed"] is False
    assert "latest_* fields are reserved" in record[
        "requirement_evidence_guard_reason"
    ]


def test_c3_id23_irrelevant_latest_fields_are_ignored_without_mutating_raw() -> None:
    adapter = _LenientEvidenceAdapter()
    _prepare(adapter, _C3_ID23_MANIFEST)
    certificate = _c3_id23_certificate()
    raw_rows = deepcopy(certificate["requirement_evidence"])

    verdict = adapter.parse_router(json.dumps(certificate))

    assert verdict.no_mistake
    record = adapter.single_innerbot_audit_records[-1]
    assert record["requirement_evidence_guard_passed"] is True
    assert record["raw_audit_certificate"] == certificate
    assert record["requirement_evidence"] == raw_rows
    assert record["requirement_evidence_raw"] == raw_rows
    assert record["ignored_irrelevant_evidence_fields"] == [
        {
            "requirement_id": "constraint_2",
            "obligation_type": "sometime_before",
            "fields": ["latest_trigger_state", "latest_response_state"],
        }
    ]
    captured = record["requirement_evidence_raw"][3]
    assert captured["latest_trigger_state"] == 12
    assert captured["latest_response_state"] == 11


def test_leniency_does_not_bypass_required_final_goal_witness() -> None:
    adapter = _LenientEvidenceAdapter()
    _prepare(adapter, {"goal_1": "final_goal"})
    certificate = _payload(
        [_row("goal_1", "final_goal", witnesses=[29], trigger=20, response=21)]
    )

    verdict = adapter.parse_router(json.dumps(certificate))

    assert not verdict.no_mistake
    record = adapter.single_innerbot_audit_records[-1]
    assert record["requirement_evidence_guard_passed"] is False
    assert "non-vacuous terminal-state witness" in record["requirement_evidence_guard_reason"]
    assert record["requirement_evidence_raw"][0][
        "latest_trigger_state"
    ] == 20


def test_leniency_never_weakens_sometime_after_temporal_validation() -> None:
    adapter = _LenientEvidenceAdapter()
    _prepare(adapter, {"constraint_after": "sometime_after"})
    certificate = _payload(
        [
            _row(
                "constraint_after",
                "sometime_after",
                witnesses=[11],
                trigger=12,
                response=11,
            )
        ]
    )

    verdict = adapter.parse_router(json.dumps(certificate))

    assert not verdict.no_mistake
    record = adapter.single_innerbot_audit_records[-1]
    assert record["requirement_evidence_guard_passed"] is False
    assert "latest response must be at or after" in record[
        "requirement_evidence_guard_reason"
    ]


def test_leniency_requires_remaining_sometime_before_witness_evidence() -> None:
    adapter = _LenientEvidenceAdapter()
    _prepare(adapter, {"constraint_before": "sometime_before"})
    certificate = _payload(
        [
            _row(
                "constraint_before",
                "sometime_before",
                witnesses=[12],
                trigger=12,
                response=11,
            )
        ]
    )

    verdict = adapter.parse_router(json.dumps(certificate))

    assert not verdict.no_mistake
    record = adapter.single_innerbot_audit_records[-1]
    assert record["requirement_evidence_guard_passed"] is False
    assert "distinct strict-prior witness states" in record[
        "requirement_evidence_guard_reason"
    ]
