"""Offline end-to-end regressions for the registered DynaPlan v1.3 path."""

from __future__ import annotations

import json
import sys
from pathlib import Path


METHOD_ROOT = Path(__file__).resolve().parent
RUNTIME_ROOT = METHOD_ROOT / "runtime"
for value in (str(RUNTIME_ROOT), str(METHOD_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from dynamic_scoring import parse_plan_subtasks  # noqa: E402
from dynaplan_nlevel_adapter import (  # noqa: E402
    DynaPlanFlatHanoiAdapter,
    _DynaPlanV12Mixin,
)
from dynaplan_nlevel_pipeline import run_shared_nlevel_loop  # noqa: E402
from flat_hanoi_task_loader import public_task_view  # noqa: E402
from scoring import parse_mappings, parse_subtask_plans  # noqa: E402
from shared_nlevel_execution_audit_v3_3_adapter import (  # noqa: E402
    V33SuccessFirstFlatHanoiAdapter,
)
from test_localized_repair import (  # noqa: E402
    _AuditThenAcceptHanoiClient,
    _three_ring_task,
)


def _compact_decision(tagged: str) -> str:
    subtasks, errors = parse_plan_subtasks(tagged)
    assert not errors
    return json.dumps(
        {
            "subtasks": [
                {
                    "id": int(item["subtask_index"]),
                    "description": str(item["description"]).strip(),
                    "checkpoint": json.loads(str(item["goal_state_text"])),
                }
                for item in subtasks
            ]
        }
    )


def _compact_hierarchy(tagged: str) -> str:
    mappings, mapping_errors = parse_mappings(tagged)
    subtasks, subtask_errors = parse_subtask_plans(tagged)
    assert not mapping_errors
    assert not subtask_errors
    return json.dumps(
        {
            "mappings": [
                {
                    "name": mapping.name,
                    "params": list(mapping.params),
                    "calls": [
                        {"name": call.name, "args": list(call.args)}
                        for call in mapping.calls
                    ],
                }
                for mapping in mappings.values()
            ],
            "subtasks": [
                {
                    "id": index,
                    "calls": [
                        {"name": call.name, "args": list(call.args)}
                        for call in calls
                    ],
                }
                for index, calls in enumerate(subtasks, start=1)
            ],
        }
    )


class _CompactFixtureClient(_AuditThenAcceptHanoiClient):
    """Translate established scripted fixtures onto the compact wire only."""

    def __init__(self, adapter, *, reject_on_audit: int) -> None:
        super().__init__(adapter, reject_on_audit=reject_on_audit)
        self.audit_prompts: list[str] = []

    def generate(self, system: str, prompt: str, **kwargs: object) -> str:
        schema_name = kwargs.get("schema_name")
        if schema_name == "n_hierarchy_single_innerbot_requirement_evidence_v3_3":
            self.audit_prompts.append(prompt)
        output = super().generate(system, prompt, **kwargs)
        if schema_name == "dynaplan_compact_decision_v1":
            return _compact_decision(output)
        if schema_name == "dynaplan_compact_hierarchy_v1":
            return _compact_hierarchy(output)
        return output


class _FrozenV12ReferenceAdapter(
    _DynaPlanV12Mixin, V33SuccessFirstFlatHanoiAdapter
):
    """Behavioral reference for the immediately preceding registered adapter."""


class _AllV13FlagsOffAdapter(DynaPlanFlatHanoiAdapter):
    compact_generation_contracts = False
    exhaustion_candidate_fallback = False
    lenient_irrelevant_evidence_fields = False


def _run(*, reject_on_audit: int, max_replans: int):
    private_task = _three_ring_task()
    adapter = DynaPlanFlatHanoiAdapter()
    client = _CompactFixtureClient(
        adapter, reject_on_audit=reject_on_audit
    )
    result = run_shared_nlevel_loop(
        public_task_view(private_task),
        client,
        adapter,
        final_score_task=private_task,
        fixed_goal=False,
        max_tokens=8192,
        max_replans=max_replans,
        reuse_h1=True,
        include_code_block=True,
        reasoning_effort="medium",
    )
    return adapter, client, result


def test_all_feature_flags_off_reproduce_v12_generation_requests() -> None:
    task = public_task_view(_three_ring_task())
    reference = _FrozenV12ReferenceAdapter()
    flags_off = _AllV13FlagsOffAdapter()
    state = reference.initial_state(task)
    scene = reference.render_state(task, state)
    common = (task, state, scene, "state output", "H1 output")

    reference_decision = reference.decision_request(*common, "")
    flags_off_decision = flags_off.decision_request(*common, "")
    assert flags_off_decision == reference_decision
    assert flags_off_decision.response_schema is None
    assert flags_off_decision.schema_name is None

    reference_hierarchy = reference.hierarchy_request(
        task,
        state,
        scene,
        "state output",
        "H1 output",
        "decision output",
        "",
        True,
    )
    flags_off_hierarchy = flags_off.hierarchy_request(
        task,
        state,
        scene,
        "state output",
        "H1 output",
        "decision output",
        "",
        True,
    )
    assert flags_off_hierarchy == reference_hierarchy
    assert flags_off_hierarchy.response_schema is None
    assert flags_off_hierarchy.schema_name is None
    assert flags_off.exhaustion_candidate_pool.enabled is False


def test_compact_contracts_round_trip_before_compile_cache_and_audit() -> None:
    adapter, client, result = _run(reject_on_audit=99, max_replans=0)

    assert result.score.solved and result.score.legal
    assert result.termination_reason == "task_success"
    assert adapter.official_final_evaluator_call_count == 1
    assert result.extra_metrics["compact_generation_contracts"] is True
    assert result.extra_metrics["compact_decision_raw_output_count"] == 1
    assert result.extra_metrics["compact_hierarchy_raw_output_count"] == 1
    attempt = result.attempts[0]
    assert attempt["hierarchy_canonicalization"]["valid"] is True
    assert attempt["stage_outputs"]["decision_raw_output"].lstrip().startswith("{")
    assert attempt["stage_outputs"]["hierarchy_raw_output"].lstrip().startswith("{")
    assert attempt["stage_outputs"]["decision_output"].startswith(
        "```start_subtask_1"
    )
    assert attempt["stage_outputs"]["hierarchy_output"].startswith(
        "```start_mapping"
    )
    assert client.audit_prompts
    assert all(
        '"semantic_verification": "WITHHELD"' in prompt
        for prompt in client.audit_prompts
    )


def test_exhaustion_submits_complete_candidate_once_as_uncertified() -> None:
    adapter, client, result = _run(reject_on_audit=1, max_replans=0)

    assert result.score.solved and result.score.legal
    assert result.termination_reason == "uncertified_fallback_submitted"
    assert result.executed_actions
    assert adapter.official_final_evaluator_call_count == 1
    assert result.extra_metrics["attempt_budget_exhausted"] is True
    assert result.extra_metrics["exhaustion_fallback_status"] == (
        "UNCERTIFIED_FALLBACK"
    )
    assert result.extra_metrics["exhaustion_fallback_selection_taken"] is True
    assert result.extra_metrics["exhaustion_fallback_semantic_authority"] is False
    assert result.extra_metrics["exhaustion_fallback_evaluator_calls"] == 0
    selection = result.attempts[-1]["exhaustion_fallback_selection"]
    assert selection["status"] == "UNCERTIFIED_FALLBACK"
    assert client.audit_count == 1
    assert all(
        '"semantic_verification": "WITHHELD"' in prompt
        for prompt in client.audit_prompts
    )


def test_normally_accepted_plan_permanently_blocks_fallback_replacement() -> None:
    adapter, _, result = _run(reject_on_audit=99, max_replans=1)

    assert result.termination_reason == "task_success"
    assert result.extra_metrics["exhaustion_fallback_selection_taken"] is False
    assert result.extra_metrics["exhaustion_fallback_accepted_plan_guard"] is True
    assert result.extra_metrics["exhaustion_fallback_status"] is None
    assert adapter.official_final_evaluator_call_count == 1
