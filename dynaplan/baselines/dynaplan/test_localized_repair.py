"""Offline regressions for DynaPlan v1.1 localized repair.

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
from comparison_protocol import common_semantics_contract  # noqa: E402
from dynaplan_nlevel_localized_repair import (  # noqa: E402
    LOCALIZED_REPAIR_REVISION,
    audit_localization,
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


def test_only_well_formed_invalid_audits_can_localize() -> None:
    record = {
        "raw_verdict": "INVALID",
        "effective_verdict": "INVALID",
        "parse_valid": True,
        "coverage_guard_passed": True,
        "requirement_evidence_guard_passed": True,
        "first_bad_subtask": 2,
        "first_bad_action_in_subtask": 4,
        "reason": "The fourth action lacks a precondition.",
    }
    localized = audit_localization(record, "hierarchy")
    assert localized is not None
    assert localized["certificate_source"] == "llm_execution_audit"
    assert localized["semantic_verification"] == "WITHHELD"
    assert localized["prefix_status"] == "audit-cleared-but-unverified"
    assert localized["first_bad_subtask"] == 2
    assert localized["localized_repair_revision"] == LOCALIZED_REPAIR_REVISION

    assert audit_localization({**record, "parse_valid": False}, "hierarchy") is None
    assert (
        audit_localization(
            {**record, "coverage_guard_passed": False}, "hierarchy"
        )
        is None
    )
    assert (
        audit_localization(
            {**record, "requirement_evidence_guard_passed": False},
            "hierarchy",
        )
        is None
    )
    assert audit_localization(record, "unknown-owner") is None


class _PromptTask:
    def prompt_text(self) -> str:
        return "Public Blocksworld task."


def test_audit_repair_prompt_does_not_claim_deterministic_authority() -> None:
    adapter = DynaPlanBlocksworldAdapter()
    request = adapter.hierarchy_repair_request(
        _PromptTask(),
        None,
        None,
        None,
        "H1",
        "Decision",
        "Candidate",
        {
            "certificate_source": "llm_execution_audit",
            "semantic_verification": "WITHHELD",
            "first_bad_subtask": 2,
        },
        (1,),
        (2,),
        "Audit rejected the suffix.",
        False,
    )

    assert "audit-localized" in request.system
    assert "semantic verification is withheld" in request.system
    assert "LLM AUDIT LOCALIZATION CERTIFICATE" in request.prompt
    assert "DETERMINISTIC FAILURE CERTIFICATE" not in request.prompt
    assert "PROMPT-INDUCED JSON-RULE FAILURE CERTIFICATE" not in request.prompt
    assert "preserved prefix is not semantically certified" in request.prompt
    assert "re-audit the complete merged candidate" in request.prompt
    assert request.prompt.count(common_semantics_contract("blocksworld")) == 1


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


def test_audit_localization_repairs_suffix_then_reaudits_full_candidate() -> None:
    private_task = _three_ring_task()
    adapter = DynaPlanFlatHanoiAdapter()
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
    assert len(client.repair_prompts) == 1
    assert len(result.attempts) == 2
    assert result.attempts[0]["failed_stage"] == "innerbot_router"
    assert (
        result.attempts[1]["repair_mode"]
        == "llm_audit_localized_suffix_patch"
    )
    assert result.extra_metrics["audit_localized_repair_schedule_count"] == 1
    assert result.extra_metrics["audit_localized_hierarchy_repair_count"] == 1
    assert result.extra_metrics["localized_patch_accept_count"] == 1
    certificate = result.extra_metrics[
        "audit_localized_failure_certificates"
    ][0]
    assert certificate["semantic_verification"] == "WITHHELD"
    assert certificate["mandatory_full_candidate_recheck"] is True


def test_post_outer_innerbot_localization_runs_after_clean_rollback() -> None:
    private_task = _three_ring_task()
    adapter = DynaPlanFlatHanoiAdapter()
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
    assert len(client.repair_prompts) == 1
    assert result.extra_metrics["candidate_transaction_rollback_count"] == 1
    assert result.extra_metrics["audit_localized_post_outer_repair_count"] == 1
    assert result.extra_metrics["audit_localized_repair_schedule_count"] == 1
    assert (
        result.attempts[-1]["repair_mode"]
        == "llm_audit_localized_suffix_patch"
    )
