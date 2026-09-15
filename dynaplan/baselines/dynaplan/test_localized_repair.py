"""Offline regressions for DynaPlan v1.2 success-first repair policy.

These tests use only the copied official runtime and make no model calls.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parent / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from dynaplan_nlevel_adapter import DynaPlanBlocksworldAdapter  # noqa: E402
from dynaplan_nlevel_adapter import DynaPlanFlatHanoiAdapter  # noqa: E402
from dynaplan_nlevel_localized_repair import (  # noqa: E402
    LOCALIZED_REPAIR_REVISION,
    decision_suffix_spec,
    merge_decision_suffix,
)
from shared_nlevel_lexicon import (  # noqa: E402
    _contains_executable_action_syntax,
)
from dynaplan_nlevel_pipeline import run_shared_nlevel_loop  # noqa: E402
from flat_hanoi_task_loader import FlatHanoiTask, public_task_view  # noqa: E402
from models import MockHanoiClient  # noqa: E402
from task_loader import Ring  # noqa: E402


class _V12CompatibleBlocksworldAdapter(DynaPlanBlocksworldAdapter):
    compact_generation_contracts = False
    exhaustion_candidate_fallback = False
    lenient_irrelevant_evidence_fields = False


class _V12CompatibleFlatHanoiAdapter(DynaPlanFlatHanoiAdapter):
    compact_generation_contracts = False
    exhaustion_candidate_fallback = False
    lenient_irrelevant_evidence_fields = False


def _decision_block(index: int, description: str, checkpoint: str = "{}") -> str:
    return f"""```start_subtask_{index}
{description}
```end_subtask_{index}
```start_subtask_goalstate_{index}
{checkpoint}
```end_subtask_goalstate_{index}"""


def test_natural_language_action_verbs_are_not_executable_syntax() -> None:
    blocksworld = ("pickup", "putdown", "stack", "unstack")
    logistics = ("loadtruck", "unloadtruck", "drivetruck")

    assert not _contains_executable_action_syntax(
        "Unstack the blue block from white, then stack it on red.",
        blocksworld,
    )
    assert not _contains_executable_action_syntax(
        "Unload the package after the truck reaches its destination.",
        logistics,
    )

    assert _contains_executable_action_syntax(
        "Use unstack(blue, white).", blocksworld
    )
    assert _contains_executable_action_syntax(
        "Use (unstack blue white).", blocksworld
    )
    assert _contains_executable_action_syntax(
        "Call ClearTower(blue).", blocksworld
    )
    assert _contains_executable_action_syntax(
        "Call unloadtruck(p1, t1, l1).", logistics
    )


def test_decision_suffix_merge_preserves_prefix_exactly() -> None:
    prefix = _decision_block(1, "Keep this prefix byte-for-byte.")
    candidate = "\n\n".join(
        (
            prefix,
            _decision_block(2, "Old second subtask."),
            _decision_block(3, "Old third subtask."),
        )
    )
    patch = "\n\n".join(
        (
            _decision_block(2, "New second subtask."),
            _decision_block(3, "New third subtask."),
        )
    )

    spec = decision_suffix_spec(
        candidate,
        ("Subtask 2 checkpoint is internally inconsistent",),
    )
    assert spec is not None
    assert spec.preserved_subtask_indices == (1,)
    assert spec.repair_subtask_indices == (2, 3)

    merged = merge_decision_suffix(
        candidate,
        patch,
        spec.preserved_subtask_indices,
        spec.repair_subtask_indices,
    )
    assert merged.valid, merged.errors
    assert merged.value is not None
    prefix_description, prefix_checkpoint = prefix.split(
        "```end_subtask_1\n", 1
    )
    assert prefix_description + "```end_subtask_1" in merged.value
    assert prefix_checkpoint in merged.value
    assert "Old second subtask" not in merged.value
    assert "New second subtask" in merged.value
    assert "New third subtask" in merged.value


def test_decision_suffix_rejects_unsafe_or_global_repairs() -> None:
    candidate = "\n\n".join(
        (_decision_block(1, "one"), _decision_block(2, "two"))
    )
    assert decision_suffix_spec(candidate, ("Final goal is missing",)) is None

    unsafe_patch = "prose before\n" + _decision_block(2, "replacement")
    merged = merge_decision_suffix(candidate, unsafe_patch, (1,), (2,))
    assert not merged.valid
    assert "outside numbered blocks" in merged.reason

    wrong_ids = merge_decision_suffix(
        candidate, _decision_block(1, "replacement"), (1,), (2,)
    )
    assert not wrong_ids.valid
    assert "exactly [2]" in wrong_ids.reason


def test_registered_policy_disables_audit_localization() -> None:
    adapter = DynaPlanBlocksworldAdapter()
    assert adapter.audit_localized_suffix_repair is False
    assert adapter.audit_localized_suffix_repair_limit == 0
    assert adapter.compact_generation_contracts is True
    assert adapter.decision_localized_suffix_repair is False
    assert adapter.decision_localized_suffix_repair_limit == 1
    compatibility = _V12CompatibleBlocksworldAdapter()
    assert compatibility.decision_localized_suffix_repair is True
    assert LOCALIZED_REPAIR_REVISION == (
        "dynaplan_deterministic_decision_suffix_repair_v1"
    )


class _AuditThenAcceptHanoiClient:
    """Force one localized rejection, then accept the fully re-audited trace."""

    def __init__(
        self,
        adapter: DynaPlanFlatHanoiAdapter,
        *,
        reject_on_audit: int = 1,
        reject_first_outer: bool = False,
    ) -> None:
        self.adapter = adapter
        self.delegate = MockHanoiClient("mock-hanoi")
        self.reject_on_audit = reject_on_audit
        self.reject_first_outer = reject_first_outer
        self.audit_count = 0
        self.outer_count = 0
        self.repair_prompts: list[str] = []
        self.hierarchy_prompts: list[str] = []
        self.initial_hierarchy = ""

    def _audit_response(self) -> str:
        self.audit_count += 1
        manifest = self.adapter._pending_audit_manifest
        terminal = manifest["expected_actions"]
        accepting = self.audit_count != self.reject_on_audit
        coverage = {
            "expected_actions": terminal,
            "checked_actions": terminal if accepting else 1,
            "expected_checkpoints": manifest["expected_checkpoints"],
            "checked_checkpoints": (
                manifest["expected_checkpoints"] if accepting else 0
            ),
            "expected_final_requirements": manifest[
                "expected_final_requirements"
            ],
            "checked_final_requirements": (
                manifest["expected_final_requirements"] if accepting else 0
            ),
            "forward_check_complete": accepting,
            "backward_check_complete": accepting,
        }
        if not accepting:
            return json.dumps(
                {
                    "verdict": "INVALID",
                    "first_bad_subtask": 1,
                    "first_bad_action_in_subtask": 1,
                    "owner": "HierarchyPlanner",
                    "coverage": coverage,
                    "final_state_facts": [],
                    "outstanding_requirements": ["forced test repair"],
                    "reason": "Forced localized-repair regression.",
                    "requirement_evidence": [],
                }
            )

        evidence = []
        for requirement_id, obligation_type in (
            self.adapter._pending_evidence_manifest.items()
        ):
            witnesses = (
                [terminal]
                if obligation_type in {"final_goal", "sometime"}
                else []
            )
            evidence.append(
                {
                    "requirement_id": requirement_id,
                    "obligation_type": obligation_type,
                    "satisfied": True,
                    "evaluated_through_state": terminal,
                    "witness_states": witnesses,
                    "latest_trigger_state": None,
                    "latest_response_state": None,
                    "vacuous": obligation_type == "sometime_after",
                    "evidence": "Offline fixture evidence.",
                }
            )
        return json.dumps(
            {
                "verdict": "VALID",
                "first_bad_subtask": 0,
                "first_bad_action_in_subtask": 0,
                "owner": "NA",
                "coverage": coverage,
                "final_state_facts": ["Exact target stacks reached."],
                "outstanding_requirements": [],
                "reason": "Accepted after complete second audit.",
                "requirement_evidence": evidence,
            }
        )

    def generate(self, system: str, prompt: str, **kwargs: object) -> str:
        if (
            kwargs.get("schema_name")
            == "n_hierarchy_single_innerbot_requirement_evidence_v3_3"
        ):
            return self._audit_response()
        if "audit-localized suffix repair" in system:
            self.repair_prompts.append(prompt)
            return "\n\n".join(
                re.findall(
                    r"```start_subtask_funcs_\d+.*?"
                    r"```end_subtask_funcs_\d+",
                    self.initial_hierarchy,
                    re.DOTALL,
                )
            )
        if "outerbot" in system.lower():
            self.outer_count += 1
            if self.reject_first_outer and self.outer_count == 1:
                return """```start_error_type
Error : RECOVERABLE
Reason : Forced OuterBot rejection for rollback regression.
```end_error_type"""
        output = self.delegate.generate(system, prompt, **kwargs)
        if "hierarchyplanner" in system.lower():
            self.hierarchy_prompts.append(prompt)
            self.initial_hierarchy = output
        return output


def _three_ring_task() -> FlatHanoiTask:
    return FlatHanoiTask(
        id="localized-repair-smoke",
        name="Localized repair smoke",
        pegs=["peg_0", "peg_1", "peg_2"],
        rings=[
            Ring(name=f"ring_{size}", size=size, label=f"ring {size}")
            for size in (1, 2, 3)
        ],
        initial={
            "peg_0": ["ring_3", "ring_2", "ring_1"],
            "peg_1": [],
            "peg_2": [],
        },
        goal={
            "peg_0": [],
            "peg_1": [],
            "peg_2": ["ring_3", "ring_2", "ring_1"],
        },
        instruction="Reach the exact goal using legal Hanoi moves.",
        optimal_move_count=7,
    )


class _MalformedDecisionPatchClient:
    """Reject one Decision structurally, then return a malformed patch."""

    def __init__(self) -> None:
        self.delegate = MockHanoiClient("mock-hanoi")
        self.full_decision_prompts: list[str] = []
        self.patch_prompts: list[str] = []

    def generate(self, system: str, prompt: str, **kwargs: object) -> str:
        if "DYNAPLAN LOCALIZED DECISION SUFFIX REPAIR" in prompt:
            self.patch_prompts.append(prompt)
            return "I could not produce the requested numbered block."

        output = self.delegate.generate(system, prompt, **kwargs)
        if "decisionbot" not in system.lower():
            return output

        self.full_decision_prompts.append(prompt)
        if len(self.full_decision_prompts) != 1:
            return output

        # Preserve a complete, localizable Decision artifact while making its
        # sole checkpoint deterministically invalid by reversing stack order.
        invalid = output.replace(
            '"ring_3",\n    "ring_2",\n    "ring_1"',
            '"ring_1",\n    "ring_2",\n    "ring_3"',
        )
        assert invalid != output
        return invalid


def test_failed_decision_patch_clears_suffix_feedback_before_full_generation() -> None:
    private_task = _three_ring_task()
    client = _MalformedDecisionPatchClient()

    result = run_shared_nlevel_loop(
        public_task_view(private_task),
        client,
        _V12CompatibleFlatHanoiAdapter(),
        final_score_task=private_task,
        fixed_goal=False,
        max_tokens=8192,
        max_replans=2,
        reuse_h1=True,
        include_code_block=True,
        reasoning_effort="medium",
    )

    assert len(client.patch_prompts) == 1
    assert len(client.full_decision_prompts) == 2
    assert "DYNAPLAN LOCALIZED DECISION SUFFIX REPAIR" not in (
        client.full_decision_prompts[1]
    )
    assert "Decision suffix patch merge failed" not in (
        client.full_decision_prompts[1]
    )
    assert result.extra_metrics["decision_suffix_patch_request_count"] == 1
    assert result.extra_metrics["decision_suffix_patch_reject_count"] == 1
    assert result.extra_metrics["decision_suffix_full_regeneration_count"] == 1
    assert result.extra_metrics["suffix_patch_feedback_clear_count"] == 1


def test_innerbot_rejection_triggers_full_hierarchy_regeneration() -> None:
    private_task = _three_ring_task()
    adapter = _V12CompatibleFlatHanoiAdapter()
    client = _AuditThenAcceptHanoiClient(adapter)

    result = run_shared_nlevel_loop(
        public_task_view(private_task),
        client,
        adapter,
        final_score_task=private_task,
        fixed_goal=False,
        max_tokens=8192,
        max_replans=2,
        reuse_h1=True,
        include_code_block=True,
        reasoning_effort="medium",
    )

    assert result.score.solved and result.score.legal
    assert client.audit_count == 2
    assert len(client.repair_prompts) == 0
    assert len(client.hierarchy_prompts) == 2
    assert len(result.attempts) == 2
    assert result.attempts[0]["failed_stage"] == "innerbot_router"
    assert "repair_mode" not in result.attempts[1]
    assert result.extra_metrics["audit_localized_repair_schedule_count"] == 0
    assert result.extra_metrics["audit_localized_hierarchy_repair_count"] == 0
    assert result.extra_metrics["localized_patch_request_count"] == 0


def test_post_outer_rejection_rolls_back_then_fully_regenerates() -> None:
    private_task = _three_ring_task()
    adapter = _V12CompatibleFlatHanoiAdapter()
    client = _AuditThenAcceptHanoiClient(
        adapter,
        reject_on_audit=2,
        reject_first_outer=True,
    )

    result = run_shared_nlevel_loop(
        public_task_view(private_task),
        client,
        adapter,
        final_score_task=private_task,
        fixed_goal=False,
        max_tokens=8192,
        max_replans=2,
        reuse_h1=True,
        include_code_block=True,
        reasoning_effort="medium",
    )

    assert result.score.solved and result.score.legal
    assert client.audit_count == 3
    assert client.outer_count == 2
    assert len(client.repair_prompts) == 0
    assert len(client.hierarchy_prompts) == 2
    assert result.extra_metrics["candidate_transaction_rollback_count"] == 1
    assert result.extra_metrics["audit_localized_post_outer_repair_count"] == 0
    assert result.extra_metrics["audit_localized_repair_schedule_count"] == 0
    assert "repair_mode" not in result.attempts[-1]
