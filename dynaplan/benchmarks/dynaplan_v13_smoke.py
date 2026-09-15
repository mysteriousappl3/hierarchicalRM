#!/usr/bin/env python3
"""Register, resume, and report the six-condition DynaPlan v1.3 smoke.

The smoke uses three frozen official tasks and both frozen official model
configurations.  Registration is offline and records the acceptance gate
before any execution.  Paid inference occurs only with ``--execute``; this
launcher never starts the 90-condition v1.3 sweep.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import concurrent.futures
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import official_sweep as frozen


SCRIPT_PATH = Path(__file__).resolve()
BENCHMARKS_ROOT = SCRIPT_PATH.parent
DYNAPLAN_ROOT = BENCHMARKS_ROOT.parent
SPEC_PATH = BENCHMARKS_ROOT / "official_sweep_v1.json"
DEFAULT_CAMPAIGN_DIR = (
    BENCHMARKS_ROOT
    / "results"
    / "dynaplan_v13_compact_fallback_smoke_6_20260915"
)
CAMPAIGN_ID = "dynaplan_v13_compact_fallback_smoke_6_20260915"
FRAMEWORK_VERSION = "dynaplan_v1_3_compact_fallback"
FRAMEWORK_BENCHMARK_VERSION = 61
EXPECTED_CONDITIONS = 6
EXPECTED_PER_MODEL = 3
FROZEN_SPEC_SHA256 = (
    "67bf3e8b35d975a72d43c7384f426a26f4247a09e5dc9e531e78d533bb4a0d7b"
)
UNCERTIFIED_FALLBACK = "UNCERTIFIED_FALLBACK"
ACCEPTANCE_GATE_REVISION = "dynaplan_v13_smoke_acceptance_gate_v1"
V13_FEATURE_FLAGS = (
    "compact_generation_contracts",
    "exhaustion_candidate_fallback",
    "lenient_irrelevant_evidence_fields",
)

SMOKE_TARGETS: Tuple[Tuple[str, str], ...] = (
    ("logistics", "c3-id23"),
    ("blocksworld", "c5-id12"),
    ("flat-hanoi", "n5-0008"),
)
FROZEN_MODELS: Tuple[Tuple[str, str, str, int, Optional[int]], ...] = (
    ("openai", "gpt-5.6-luna", "medium", 8192, None),
    ("anthropic", "claude-haiku-4-5-20251001", "medium", 8192, 4096),
)
FORBIDDEN_MODEL_VISIBLE_FIELDS = {
    "logistics": (
        "optimal_length",
        "oracle_actions",
        "task_dir",
        "source_files",
        "source_metadata",
    ),
    "blocksworld": (
        "optimal_length",
        "oracle_length",
        "oracle_actions",
        "unconstrained_optimal_length",
        "unconstrained_oracle_actions",
        "task_dir",
        "source_files",
        "source_metadata",
    ),
    "flat-hanoi": (
        "optimal_move_count",
        "source_peg",
        "auxiliary_peg",
        "target_peg",
    ),
}


def _spec() -> Dict[str, Any]:
    spec = frozen._read_json(SPEC_PATH)
    frozen._validate_spec(spec)
    if frozen._canonical_sha256(spec) != FROZEN_SPEC_SHA256:
        raise frozen.SweepError("official frozen sweep registry digest changed")
    observed_models = tuple(
        (
            str(item.get("provider")),
            str(item.get("model")),
            str(item.get("reasoning")),
            int(item.get("max_output_tokens", -1)),
            item.get("thinking_budget_tokens"),
        )
        for item in spec["models"]
    )
    if observed_models != FROZEN_MODELS:
        raise frozen.SweepError("frozen smoke model configuration changed")
    return spec


def _conditions(spec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    wanted = set(SMOKE_TARGETS)
    by_key = {
        (
            str(condition["provider"]),
            str(condition["benchmark"]),
            str(condition["coordinate"]),
        ): condition
        for condition in frozen._conditions(spec)
        if condition["method"] == "dynaplan"
        and (condition["benchmark"], condition["coordinate"]) in wanted
    }
    conditions: List[Dict[str, Any]] = []
    for provider, model, reasoning, tokens, thinking in FROZEN_MODELS:
        for benchmark, coordinate in SMOKE_TARGETS:
            key = (provider, benchmark, coordinate)
            condition = by_key.get(key)
            if condition is None:
                raise frozen.SweepError(
                    f"frozen smoke condition is missing: {key}"
                )
            if (
                condition["model"] != model
                or condition["reasoning"] != reasoning
                or int(condition["max_output_tokens"]) != tokens
                or condition["thinking_budget_tokens"] != thinking
            ):
                raise frozen.SweepError(
                    f"frozen smoke settings changed for {condition['condition_id']}"
                )
            conditions.append(dict(condition))

    if len(conditions) != EXPECTED_CONDITIONS:
        raise frozen.SweepError(
            f"smoke matrix has {len(conditions)} conditions; "
            f"expected {EXPECTED_CONDITIONS}"
        )
    if len({item["condition_id"] for item in conditions}) != len(conditions):
        raise frozen.SweepError("smoke condition IDs are not unique")
    if {item["benchmark"] for item in conditions} != {
        item[0] for item in SMOKE_TARGETS
    }:
        raise frozen.SweepError("smoke benchmark coverage changed")
    return conditions


def _source_lock(spec: Mapping[str, Any]) -> Dict[str, str]:
    lock = frozen._source_lock(spec)
    lock["official/benchmarks/dynaplan_v13_smoke.py"] = frozen._sha256(
        SCRIPT_PATH
    )
    return lock


def _framework_manifest() -> Dict[str, Any]:
    path = DYNAPLAN_ROOT / "baselines" / "dynaplan" / "framework.json"
    manifest = frozen._read_json(path)
    if manifest.get("framework_version") != FRAMEWORK_VERSION:
        raise frozen.SweepError(
            "DynaPlan framework manifest is not the registered v1.3 variant"
        )
    if manifest.get("benchmark_version") != FRAMEWORK_BENCHMARK_VERSION:
        raise frozen.SweepError("DynaPlan benchmark version mismatch")
    flags = manifest.get("v1_3_feature_flags")
    if not isinstance(flags, Mapping) or any(
        flags.get(name) is not True for name in V13_FEATURE_FLAGS
    ):
        raise frozen.SweepError("DynaPlan v1.3 feature flags are not enabled")
    return manifest


def _gate_definition(
    conditions: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "revision": ACCEPTANCE_GATE_REVISION,
        "declared_before_execution": True,
        "condition_ids": [item["condition_id"] for item in conditions],
        "requirements": {
            "complete_condition_count": EXPECTED_CONDITIONS,
            "setup_and_prompt_contracts": "all 6 conditions pass both checks",
            "compact_stage_prompt_contract": (
                "each condition has decision and hierarchy_planner calls, and "
                "every such call uses the v1.3 compact response schema"
            ),
            "gpt_5_6_luna_valid_minimum": 2,
            "gpt_5_6_luna_valid_denominator": EXPECTED_PER_MODEL,
            "gpt_interpretation": "no obvious regression",
            "claude_haiku_4_5_valid_minimum_exclusive": 0,
            "claude_haiku_4_5_valid_denominator": EXPECTED_PER_MODEL,
            "exhausted_retained_candidate_policy": (
                "every attempt-budget-exhausted run with an eligible candidate "
                "available at terminal selection submits it as "
                "UNCERTIFIED_FALLBACK"
            ),
            "official_final_evaluator_calls_per_condition": 1,
            "fallback_component_evaluator_calls": 0,
            "transaction_policy": (
                "every rejected candidate transaction is rolled back without "
                "state/action leakage before retry or terminal selection"
            ),
            "public_task_policy": (
                "oracle fields are structurally absent from every slot-only "
                "model-visible task"
            ),
        },
    }


def register(campaign_dir: Path) -> None:
    if campaign_dir.exists():
        raise frozen.SweepError(
            f"campaign directory already exists: {campaign_dir}"
        )
    spec = _spec()
    conditions = _conditions(spec)
    framework = _framework_manifest()
    gate = _gate_definition(conditions)
    git_status = frozen._git("status", "--porcelain", "--untracked-files=no")
    manifest = {
        "manifest_schema_version": 1,
        "registered_at": frozen._utc_now(),
        "campaign_id": CAMPAIGN_ID,
        "derived_from_campaign": spec["campaign_id"],
        "comparison_prompt_protocol": spec["comparison_prompt_protocol"],
        "framework_version": FRAMEWORK_VERSION,
        "framework_benchmark_version": framework["benchmark_version"],
        "spec": spec,
        "spec_sha256": frozen._canonical_sha256(spec),
        "git_commit": frozen._git("rev-parse", "HEAD"),
        "source_tree_had_tracked_changes": bool(git_status),
        "source_lock_is_authoritative": True,
        "python_executable": str(Path(sys.executable).resolve()),
        "source_lock": _source_lock(spec),
        "conditions": conditions,
        "condition_count": EXPECTED_CONDITIONS,
        "acceptance_gate": gate,
        "acceptance_gate_sha256": frozen._canonical_sha256(gate),
        "resumability": "completed conditions are skipped; partial attempts are retained",
        "full_sweep_automatically_triggered": False,
        "execution_started": False,
    }
    campaign_dir.mkdir(parents=True, exist_ok=False)
    frozen._write_json(campaign_dir / "registered_manifest.json", manifest)
    frozen._write_json(
        campaign_dir / "acceptance_gate_definition.json",
        {
            "campaign_id": CAMPAIGN_ID,
            "acceptance_gate": gate,
            "acceptance_gate_sha256": manifest["acceptance_gate_sha256"],
        },
    )
    print(
        f"Registered {EXPECTED_CONDITIONS} DynaPlan v1.3 smoke conditions: "
        f"{campaign_dir / 'registered_manifest.json'}"
    )


def verify(campaign_dir: Path) -> Dict[str, Any]:
    manifest = frozen._read_json(campaign_dir / "registered_manifest.json")
    gate_file = frozen._read_json(
        campaign_dir / "acceptance_gate_definition.json"
    )
    spec = _spec()
    expected_conditions = _conditions(spec)
    expected_gate = _gate_definition(expected_conditions)
    if manifest.get("campaign_id") != CAMPAIGN_ID:
        raise frozen.SweepError("campaign ID mismatch")
    if manifest.get("framework_version") != FRAMEWORK_VERSION:
        raise frozen.SweepError("framework version mismatch")
    if (
        manifest.get("framework_benchmark_version")
        != FRAMEWORK_BENCHMARK_VERSION
    ):
        raise frozen.SweepError("framework benchmark version mismatch")
    if manifest.get("spec") != spec:
        raise frozen.SweepError("registered frozen spec changed")
    if manifest.get("spec_sha256") != frozen._canonical_sha256(spec):
        raise frozen.SweepError("frozen task/model spec changed")
    if manifest.get("conditions") != expected_conditions:
        raise frozen.SweepError("registered smoke condition matrix changed")
    if manifest.get("condition_count") != EXPECTED_CONDITIONS:
        raise frozen.SweepError("registered smoke condition count mismatch")
    if manifest.get("acceptance_gate") != expected_gate:
        raise frozen.SweepError("predeclared acceptance gate changed")
    gate_digest = frozen._canonical_sha256(expected_gate)
    if manifest.get("acceptance_gate_sha256") != gate_digest:
        raise frozen.SweepError("predeclared acceptance gate digest changed")
    if gate_file != {
        "campaign_id": CAMPAIGN_ID,
        "acceptance_gate": expected_gate,
        "acceptance_gate_sha256": gate_digest,
    }:
        raise frozen.SweepError("acceptance gate definition file changed")
    if manifest.get("source_lock") != _source_lock(spec):
        raise frozen.SweepError("DynaPlan v1.3 smoke source or task drifted")
    if manifest.get("git_commit") != frozen._git("rev-parse", "HEAD"):
        raise frozen.SweepError("Git commit changed after registration")
    if manifest.get("python_executable") != str(Path(sys.executable).resolve()):
        raise frozen.SweepError("Python interpreter changed after registration")
    if manifest.get("full_sweep_automatically_triggered") is not False:
        raise frozen.SweepError("smoke/full-sweep separation policy changed")
    _framework_manifest()
    return manifest


def _interleave_providers(
    conditions: Sequence[Mapping[str, Any]],
) -> List[Mapping[str, Any]]:
    queues = {
        provider: deque(
            condition
            for condition in conditions
            if condition["provider"] == provider
        )
        for provider in frozen.EXPECTED_PROVIDERS
    }
    ordered: List[Mapping[str, Any]] = []
    while any(queues.values()):
        for provider in frozen.EXPECTED_PROVIDERS:
            if queues[provider]:
                ordered.append(queues[provider].popleft())
    return ordered


def _attempt_number(path: Path, condition_id: str) -> Optional[int]:
    match = re.fullmatch(
        re.escape(condition_id) + r"--attempt-(\d+)", path.name
    )
    return int(match.group(1)) if match else None


def _setup_complete_artifact(
    condition_id: str, campaign_dir: Path
) -> Optional[Path]:
    attempts = frozen._existing_attempts(
        condition_id, campaign_dir / "condition_runs"
    )
    completed: List[Path] = []
    for path in attempts:
        summary_path = path / "summary.json"
        if not summary_path.is_file():
            continue
        try:
            summary = frozen._read_json(summary_path)
        except frozen.SweepError:
            continue
        results = summary.get("results")
        if (
            int(summary.get("setup_verified", 0)) == 1
            and isinstance(results, list)
            and len(results) == 1
            and isinstance(results[0], Mapping)
            and results[0].get("setup_verified") is True
        ):
            completed.append(path)
    return completed[-1] if completed else None


def _run_condition(
    condition: Mapping[str, Any], campaign_dir: Path, env_file: Path
) -> Dict[str, Any]:
    """Resume without overwriting partial or failed-infrastructure attempts."""

    condition_id = str(condition["condition_id"])
    complete = _setup_complete_artifact(condition_id, campaign_dir)
    if complete is not None:
        return {
            "condition_id": condition_id,
            "status": "SKIPPED_COMPLETE",
            "artifact": str(complete),
            "completed_at": frozen._utc_now(),
        }
    attempts = frozen._existing_attempts(
        condition_id, campaign_dir / "condition_runs"
    )
    numbers = [
        number
        for number in (_attempt_number(path, condition_id) for path in attempts)
        if number is not None
    ]
    attempt = max(numbers, default=0) + 1
    command = frozen._condition_command(
        condition, campaign_dir, attempt, env_file
    )
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(DYNAPLAN_ROOT),
    )
    run_dir = (
        campaign_dir
        / "condition_runs"
        / f"{condition_id}--attempt-{attempt:03d}"
    )
    setup_complete = _setup_complete_artifact(condition_id, campaign_dir)
    return {
        "condition_id": condition_id,
        "status": "COMPLETE" if setup_complete == run_dir else "INCOMPLETE",
        "returncode": completed.returncode,
        "artifact": str(run_dir),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "completed_at": frozen._utc_now(),
    }


def execute(
    campaign_dir: Path,
    *,
    env_file: Path,
    jobs: int,
    provider: Optional[str],
    benchmark: Optional[str],
    condition_ids: Sequence[str],
) -> None:
    manifest = verify(campaign_dir)
    requested_ids = set(condition_ids)
    known_ids = {item["condition_id"] for item in manifest["conditions"]}
    unknown_ids = requested_ids - known_ids
    if unknown_ids:
        raise frozen.SweepError(
            "unknown condition ID(s): " + ", ".join(sorted(unknown_ids))
        )
    selected = [
        condition
        for condition in manifest["conditions"]
        if (provider is None or condition["provider"] == provider)
        and (benchmark is None or condition["benchmark"] == benchmark)
        and (
            not requested_ids
            or condition["condition_id"] in requested_ids
        )
    ]
    if not selected:
        raise frozen.SweepError("execution filters selected no conditions")
    if not env_file.is_file():
        raise frozen.SweepError(f"environment file is missing: {env_file}")
    ordered = _interleave_providers(selected)
    event_log = campaign_dir / "execution_log.jsonl"
    print(
        f"Executing/resuming {len(ordered)} DynaPlan v1.3 smoke conditions "
        f"with jobs={jobs}",
        flush=True,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(
                _run_condition, condition, campaign_dir, env_file
            ): condition
            for condition in ordered
        }
        for index, future in enumerate(
            concurrent.futures.as_completed(futures), start=1
        ):
            record = future.result()
            frozen._append_jsonl(event_log, record)
            print(
                f"[{index}/{len(ordered)}] {record['condition_id']}: "
                f"{record['status']} rc={record.get('returncode', '—')}",
                flush=True,
            )


def _strict_int(value: object) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _recursive_mapping_keys(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _recursive_mapping_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _recursive_mapping_keys(nested)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _native_bundle(
    artifact: Path, result: Mapping[str, Any]
) -> Tuple[Optional[Path], Mapping[str, Any], Mapping[str, Any], List[str]]:
    errors: List[str] = []
    candidates: List[Path] = []
    reported = result.get("native_result_dir")
    if isinstance(reported, str) and reported:
        reported_path = Path(reported)
        if (
            reported_path.is_dir()
            and _is_within(reported_path, artifact)
            and (reported_path / "metrics.json").is_file()
            and (reported_path / "steps.json").is_file()
        ):
            candidates.append(reported_path)
    if not candidates:
        candidates = sorted(
            path.parent
            for path in artifact.rglob("metrics.json")
            if (path.parent / "steps.json").is_file()
        )
    unique = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in unique:
            unique.append(resolved)
    if len(unique) != 1:
        errors.append(
            "expected exactly one native metrics/steps bundle inside the condition artifact"
        )
        return None, {}, {}, errors
    native_dir = Path(unique[0])
    if not _is_within(native_dir, artifact):
        errors.append("native artifact resolves outside the condition artifact")
        return native_dir, {}, {}, errors
    try:
        metrics = frozen._read_json(native_dir / "metrics.json")
        steps = frozen._read_json(native_dir / "steps.json")
    except frozen.SweepError as error:
        errors.append(str(error))
        return native_dir, {}, {}, errors
    return native_dir, metrics, steps, errors


def _compact_stage_contract_audit(artifact: Path) -> Dict[str, Any]:
    errors: List[str] = []
    logs = sorted(artifact.rglob("live_model_calls.jsonl"))
    if len(logs) != 1:
        errors.append(
            "expected exactly one live_model_calls.jsonl in the condition artifact"
        )
        return {
            "verified": False,
            "log_path": None,
            "decision_call_count": 0,
            "hierarchy_planner_call_count": 0,
            "errors": errors,
        }
    records: List[Mapping[str, Any]] = []
    try:
        for line_number, line in enumerate(
            logs[0].read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, Mapping):
                raise ValueError(f"line {line_number} is not an object")
            records.append(value)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        errors.append(f"cannot read completed-call ledger: {error}")

    expected_schemas = {
        "decision": "dynaplan_compact_decision_v1",
        "hierarchy_planner": "dynaplan_compact_hierarchy_v1",
    }
    counts: Dict[str, int] = {}
    for stage, schema in expected_schemas.items():
        calls = [record for record in records if record.get("stage") == stage]
        counts[stage] = len(calls)
        if not calls:
            errors.append(f"completed-call ledger contains no {stage} call")
        mismatches = [
            record.get("call_index")
            for record in calls
            if record.get("response_schema_name") != schema
        ]
        if mismatches:
            errors.append(
                f"{stage} call(s) use a non-compact response schema: {mismatches}"
            )
    return {
        "verified": not errors,
        "log_path": str(logs[0]),
        "decision_call_count": counts.get("decision", 0),
        "hierarchy_planner_call_count": counts.get("hierarchy_planner", 0),
        "errors": errors,
    }


def _prompt_contract_audit(
    result: Mapping[str, Any], benchmark: str, artifact: Path
) -> Tuple[bool, List[str], Dict[str, Any]]:
    errors: List[str] = []
    if result.get("prompt_contract_verified") is not True:
        errors.append("prompt_contract_verified is not true")
    records = result.get("prompt_contract")
    if not isinstance(records, list) or not records:
        errors.append("prompt contract call records are missing")
    else:
        for index, record in enumerate(records, start=1):
            item = _mapping(record)
            if item.get("minimum_objective_count") != 1:
                errors.append(
                    f"prompt call {index} does not contain the objective exactly once"
                )
            if item.get("common_semantics_count") != 1:
                errors.append(
                    f"prompt call {index} does not contain shared semantics exactly once"
                )
            hanoi_count = item.get("shared_hanoi_example_count")
            if benchmark == "flat-hanoi" and hanoi_count != 1:
                errors.append(
                    f"prompt call {index} does not contain the Hanoi example exactly once"
                )
            if benchmark != "flat-hanoi" and hanoi_count is not None:
                errors.append(
                    f"prompt call {index} unexpectedly reports a Hanoi example count"
                )
    compact = _compact_stage_contract_audit(artifact)
    errors.extend(str(item) for item in compact["errors"])
    return not errors, errors, compact


def _native_and_rollback_audit(
    condition: Mapping[str, Any],
    artifact: Path,
    result: Mapping[str, Any],
    method_metrics: Mapping[str, Any],
) -> Dict[str, Any]:
    native_dir, metrics, steps, errors = _native_bundle(artifact, result)
    architecture_ok = bool(
        metrics.get("architecture_version") == FRAMEWORK_VERSION
        and metrics.get("benchmark_version") == FRAMEWORK_BENCHMARK_VERSION
        and steps.get("architecture_version") == FRAMEWORK_VERSION
    )
    if not architecture_ok:
        errors.append("native bundle has the wrong architecture/benchmark version")
    if (
        metrics.get("provider") != condition["provider"]
        or metrics.get("model") != condition["model"]
        or metrics.get("reasoning_effort") != condition["reasoning"]
    ):
        errors.append("native invocation metadata differs from the condition")

    planning_boundary = _mapping(metrics.get("planning_task_boundary"))
    integration = _mapping(metrics.get("official_integration"))
    public_boundary = _mapping(integration.get("public_task_boundary"))
    if planning_boundary.get("oracle_fields_structurally_absent") is not True:
        errors.append("native planning boundary did not attest oracle absence")
    if (
        public_boundary.get("oracle_fields_structurally_absent") is not True
        or public_boundary.get("slot_only") is not True
    ):
        errors.append("official public task boundary is not oracle-free and slot-only")

    visible_keys = set(_recursive_mapping_keys(steps.get("model_visible_task")))
    leaked = sorted(
        visible_keys.intersection(
            FORBIDDEN_MODEL_VISIBLE_FIELDS[str(condition["benchmark"])]
        )
    )
    if leaked:
        errors.append("model-visible task leaked field(s): " + ", ".join(leaked))

    if method_metrics.get("transactional_candidate_execution") is not True:
        errors.append("transactional candidate execution was not enabled")
    for name in V13_FEATURE_FLAGS:
        if method_metrics.get(name) is not True:
            errors.append(f"v1.3 feature flag telemetry is not true: {name}")
    attempts = steps.get("attempts")
    if not isinstance(attempts, list):
        errors.append("native attempt records are missing")
        attempts = []
    rollback_count = 0
    commit_count = 0
    for index, raw_attempt in enumerate(attempts):
        attempt = _mapping(raw_attempt)
        transaction = attempt.get("execution_transaction")
        if not isinstance(transaction, Mapping):
            continue
        rolled_back = transaction.get("rolled_back") is True
        committed = transaction.get("committed") is True
        if rolled_back and committed:
            errors.append(f"attempt {index} is both committed and rolled back")
        if committed:
            commit_count += 1
        if not rolled_back:
            continue
        rollback_count += 1
        starting = _strict_int(transaction.get("starting_state_revision"))
        restored = _strict_int(transaction.get("restored_state_revision"))
        ending = _strict_int(attempt.get("ending_state_revision"))
        if starting is None or restored != starting or ending != starting:
            errors.append(f"attempt {index} did not restore its starting revision")
        if index + 1 < len(attempts):
            next_attempt = _mapping(attempts[index + 1])
            if _strict_int(next_attempt.get("state_revision")) != starting:
                errors.append(
                    f"attempt {index + 1} did not start at the rolled-back revision"
                )
            if next_attempt.get("input_state") != attempt.get("input_state"):
                errors.append(
                    f"attempt {index + 1} inherited state from a rejected candidate"
                )
        else:
            terminal_restore_exempt = bool(
                method_metrics.get("exhaustion_fallback_selection_taken") is True
                or method_metrics.get("valid_incumbent_restored") is True
            )
            if (
                not terminal_restore_exempt
                and steps.get("final_state") != attempt.get("input_state")
            ):
                errors.append("terminal rejected candidate leaked into final state")

    recorded_rollbacks = _strict_int(
        method_metrics.get("candidate_transaction_rollback_count")
    )
    recorded_commits = _strict_int(
        method_metrics.get("candidate_transaction_commit_count")
    )
    if recorded_rollbacks is None or recorded_rollbacks != rollback_count:
        errors.append("rollback telemetry disagrees with native attempts")
    if recorded_commits is None or recorded_commits != commit_count:
        errors.append("commit telemetry disagrees with native attempts")
    continuations = _strict_int(
        method_metrics.get("candidate_rollback_continuation_count")
    )
    if (
        continuations is None
        or recorded_rollbacks is None
        or continuations < 0
        or continuations > recorded_rollbacks
    ):
        errors.append("rollback continuation telemetry is inconsistent")

    evaluator_count = _strict_int(
        integration.get("official_final_evaluator_call_count")
    )
    return {
        "native_result_dir": str(native_dir) if native_dir is not None else None,
        "termination_reason": metrics.get("termination_reason"),
        "native_artifacts_verified": native_dir is not None and not errors,
        "rollback_count": rollback_count,
        "commit_count": commit_count,
        "official_final_evaluator_call_count": evaluator_count,
        "rollback_and_no_leakage_verified": not errors,
        "errors": errors,
    }


def _fallback_audit(
    result: Mapping[str, Any],
    method_metrics: Mapping[str, Any],
    termination_reason: object,
) -> Dict[str, Any]:
    exhausted_value = method_metrics.get("attempt_budget_exhausted")
    exhausted = exhausted_value is True
    retained_value = _strict_int(
        method_metrics.get("exhaustion_fallback_retained_count")
    )
    retained_count = retained_value if retained_value is not None else -1
    best_serial_value = method_metrics.get(
        "exhaustion_fallback_best_candidate_serial"
    )
    best_serial = (
        _strict_int(best_serial_value)
        if best_serial_value is not None
        else None
    )
    eligible_at_exhaustion = bool(exhausted and best_serial is not None)
    applicable = eligible_at_exhaustion
    errors: List[str] = []
    if not isinstance(exhausted_value, bool):
        errors.append("attempt-budget exhaustion telemetry is missing")
    if retained_value is None or retained_value < 0:
        errors.append("retained-candidate telemetry is missing or invalid")
    if best_serial_value is not None and best_serial is None:
        errors.append("eligible fallback candidate serial is invalid")
    if method_metrics.get("exhaustion_candidate_fallback") is not True:
        errors.append("exhaustion candidate fallback was not enabled")
    if method_metrics.get("exhaustion_fallback_semantic_authority") is not False:
        errors.append("fallback incorrectly claims semantic authority")
    if method_metrics.get("exhaustion_fallback_evaluator_calls") != 0:
        errors.append("fallback component called the evaluator")
    if applicable:
        selection = _mapping(
            method_metrics.get("exhaustion_fallback_selection")
        )
        if method_metrics.get("exhaustion_fallback_selection_taken") is not True:
            errors.append("fallback selection was not taken")
        if method_metrics.get("exhaustion_fallback_status") != UNCERTIFIED_FALLBACK:
            errors.append("fallback status is not UNCERTIFIED_FALLBACK")
        if selection.get("status") != UNCERTIFIED_FALLBACK:
            errors.append("selected fallback is not marked UNCERTIFIED_FALLBACK")
        if termination_reason != "uncertified_fallback_submitted":
            errors.append("retained fallback was not the terminal submission")
        submitted = result.get("submitted_candidate_actions")
        if not isinstance(submitted, list) or not submitted:
            errors.append("fallback submission contains no primitive actions")
    elif method_metrics.get("exhaustion_fallback_selection_taken") is True:
        errors.append(
            "fallback selection was taken without an eligible exhausted candidate"
        )
    return {
        "applicable": applicable,
        "attempt_budget_exhausted": exhausted,
        "retained_candidate_count_lifetime": retained_count,
        "eligible_candidate_at_exhaustion": eligible_at_exhaustion,
        "best_candidate_serial_at_exhaustion": best_serial,
        "verified": not errors,
        "errors": errors,
    }


def _condition_row(
    condition: Mapping[str, Any], artifact: Path
) -> Dict[str, Any]:
    summary = frozen._read_json(artifact / "summary.json")
    results = summary.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise frozen.SweepError(f"{artifact} must contain exactly one result")
    result = results[0]
    if not isinstance(result, Mapping):
        raise frozen.SweepError(f"{artifact} result must be an object")
    evaluation = result.get("evaluation")
    usage = summary.get("usage")
    if not isinstance(evaluation, dict) or not isinstance(usage, dict):
        raise frozen.SweepError(f"{artifact} is missing evaluation or usage")
    if (
        summary.get("provider") != condition["provider"]
        or summary.get("model") != condition["model"]
        or summary.get("reasoning_effort") != condition["reasoning"]
        or summary.get("baseline_selection") != "dynaplan"
        or summary.get("benchmarks") != [condition["benchmark"]]
    ):
        raise frozen.SweepError(f"condition metadata mismatch in {artifact}")
    if int(summary.get("max_completion_tokens", -1)) != int(
        condition["max_output_tokens"]
    ):
        raise frozen.SweepError(f"token ceiling mismatch in {artifact}")
    if (
        summary.get("anthropic_thinking_budget_tokens")
        != condition["thinking_budget_tokens"]
    ):
        raise frozen.SweepError(f"thinking budget mismatch in {artifact}")
    if result.get("architecture_version") != FRAMEWORK_VERSION:
        raise frozen.SweepError(f"condition architecture mismatch in {artifact}")
    if (
        result.get("provider") != condition["provider"]
        or result.get("model") != condition["model"]
        or result.get("reasoning_effort") != condition["reasoning"]
        or result.get("baseline") != "dynaplan"
        or result.get("benchmark") != condition["benchmark"]
    ):
        raise frozen.SweepError(f"result metadata mismatch in {artifact}")

    method_metrics = _mapping(result.get("method_metrics"))
    prompt_ok, prompt_errors, compact_contract = _prompt_contract_audit(
        result, str(condition["benchmark"]), artifact
    )
    native_audit = _native_and_rollback_audit(
        condition, artifact, result, method_metrics
    )
    evaluator_ok = bool(
        result.get("final_evaluator_once") is True
        and method_metrics.get("official_final_evaluator_call_count") == 1
        and native_audit["official_final_evaluator_call_count"] == 1
    )
    fallback_audit = _fallback_audit(
        result, method_metrics, native_audit["termination_reason"]
    )
    cost = summary.get("estimated_cost_usd")
    return {
        **condition,
        "artifact": str(artifact),
        "setup_verified": result.get("setup_verified") is True,
        "prompt_contract_verified": prompt_ok,
        "prompt_contract_errors": prompt_errors,
        "compact_stage_contract": compact_contract,
        "final_evaluator_once": evaluator_ok,
        "rollback_and_no_leakage_verified": native_audit[
            "rollback_and_no_leakage_verified"
        ],
        "native_audit": native_audit,
        "fallback_policy_verified": fallback_audit["verified"],
        "fallback_audit": fallback_audit,
        "success": bool(evaluation.get("success")),
        "optimal": bool(evaluation.get("optimal")),
        "status": evaluation.get("status"),
        "submitted_length": evaluation.get("submitted_length"),
        "optimal_length": evaluation.get("optimal_length"),
        "model_calls": int(summary.get("model_call_count", 0)),
        "tokens": int(usage.get("total_tokens", 0)),
        "estimated_cost_usd": float(cost) if cost is not None else None,
    }


def _check(
    check_id: str,
    requirement: str,
    observed: object,
    passed: bool,
    failures: Sequence[str],
    *,
    complete: bool,
) -> Dict[str, Any]:
    return {
        "check_id": check_id,
        "requirement": requirement,
        "observed": observed,
        "status": "PASS" if complete and passed else "FAIL" if complete else "PENDING",
        "passed": passed if complete else None,
        "failures": list(failures),
    }


def _gate_report(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    incomplete: Sequence[str],
) -> Dict[str, Any]:
    complete = not incomplete and len(rows) == EXPECTED_CONDITIONS
    row_ids = [str(row["condition_id"]) for row in rows]

    contract_failures = [
        str(row["condition_id"])
        for row in rows
        if not (
            row["setup_verified"] and row["prompt_contract_verified"]
        )
    ]
    evaluator_failures = [
        str(row["condition_id"])
        for row in rows
        if not row["final_evaluator_once"]
    ]
    rollback_failures = [
        str(row["condition_id"])
        for row in rows
        if not row["rollback_and_no_leakage_verified"]
    ]
    fallback_failures = [
        str(row["condition_id"])
        for row in rows
        if not row["fallback_policy_verified"]
    ]
    openai_rows = [row for row in rows if row["provider"] == "openai"]
    anthropic_rows = [row for row in rows if row["provider"] == "anthropic"]
    openai_valid = sum(bool(row["success"]) for row in openai_rows)
    anthropic_valid = sum(bool(row["success"]) for row in anthropic_rows)

    checks = [
        _check(
            "complete_matrix",
            "all six predeclared conditions complete",
            {"completed": len(rows), "condition_ids": row_ids},
            complete,
            list(incomplete),
            complete=complete,
        ),
        _check(
            "setup_and_prompt_contracts",
            "6/6 setup and prompt contracts pass",
            EXPECTED_CONDITIONS - len(contract_failures),
            not contract_failures,
            contract_failures,
            complete=complete,
        ),
        _check(
            "gpt_no_obvious_regression",
            "GPT-5.6 Luna is valid on at least 2/3 conditions",
            {"valid": openai_valid, "completed": len(openai_rows)},
            len(openai_rows) == EXPECTED_PER_MODEL and openai_valid >= 2,
            [] if openai_valid >= 2 else ["fewer than two valid GPT conditions"],
            complete=complete,
        ),
        _check(
            "haiku_nonzero",
            "Claude Haiku 4.5 Thinking is valid on more than 0/3 conditions",
            {"valid": anthropic_valid, "completed": len(anthropic_rows)},
            len(anthropic_rows) == EXPECTED_PER_MODEL and anthropic_valid > 0,
            [] if anthropic_valid > 0 else ["no valid Haiku condition"],
            complete=complete,
        ),
        _check(
            "exhausted_retained_fallback",
            "every exhausted run with an eligible terminal candidate submits UNCERTIFIED_FALLBACK",
            EXPECTED_CONDITIONS - len(fallback_failures),
            not fallback_failures,
            fallback_failures,
            complete=complete,
        ),
        _check(
            "official_evaluator_once",
            "the official final evaluator is called exactly once per condition",
            EXPECTED_CONDITIONS - len(evaluator_failures),
            not evaluator_failures,
            evaluator_failures,
            complete=complete,
        ),
        _check(
            "rollback_and_no_leakage",
            "all rollback restoration and public-task leakage checks pass",
            EXPECTED_CONDITIONS - len(rollback_failures),
            not rollback_failures,
            rollback_failures,
            complete=complete,
        ),
    ]
    gate_passed = bool(complete and all(item["passed"] is True for item in checks))
    status = "PASS" if gate_passed else "FAIL" if complete else "PENDING"
    return {
        "schema_version": 1,
        "campaign_id": CAMPAIGN_ID,
        "framework_version": FRAMEWORK_VERSION,
        "framework_benchmark_version": FRAMEWORK_BENCHMARK_VERSION,
        "generated_at": frozen._utc_now(),
        "definition": manifest["acceptance_gate"],
        "definition_sha256": manifest["acceptance_gate_sha256"],
        "status": status,
        "passed": gate_passed if complete else None,
        "completed_conditions": len(rows),
        "incomplete_condition_ids": list(incomplete),
        "checks": checks,
    }


def report(campaign_dir: Path) -> Dict[str, Any]:
    manifest = verify(campaign_dir)
    rows: List[Dict[str, Any]] = []
    incomplete: List[str] = []
    for condition in manifest["conditions"]:
        condition_id = str(condition["condition_id"])
        artifact = _setup_complete_artifact(condition_id, campaign_dir)
        if artifact is None:
            incomplete.append(condition_id)
            continue
        rows.append(_condition_row(condition, artifact))

    groups: Dict[tuple[str, str], Dict[str, Any]] = defaultdict(
        lambda: {
            "completed": 0,
            "setup_verified": 0,
            "prompt_contract_verified": 0,
            "final_evaluator_once": 0,
            "rollback_no_leakage": 0,
            "fallback_policy": 0,
            "valid": 0,
            "optimal": 0,
            "calls": 0,
            "tokens": 0,
            "estimated_cost_usd": 0.0,
            "cost_complete": True,
        }
    )
    for row in rows:
        key = (row["provider"], row["model"])
        group = groups[key]
        group["completed"] += 1
        group["setup_verified"] += int(row["setup_verified"])
        group["prompt_contract_verified"] += int(
            row["prompt_contract_verified"]
        )
        group["final_evaluator_once"] += int(row["final_evaluator_once"])
        group["rollback_no_leakage"] += int(
            row["rollback_and_no_leakage_verified"]
        )
        group["fallback_policy"] += int(row["fallback_policy_verified"])
        group["valid"] += int(row["success"])
        group["optimal"] += int(row["optimal"])
        group["calls"] += row["model_calls"]
        group["tokens"] += row["tokens"]
        if row["estimated_cost_usd"] is None:
            group["cost_complete"] = False
        else:
            group["estimated_cost_usd"] += row["estimated_cost_usd"]

    aggregate_rows = []
    for key in sorted(groups):
        group = dict(groups[key])
        cost = group.pop("estimated_cost_usd")
        cost_complete = group.pop("cost_complete")
        aggregate_rows.append(
            {
                "provider": key[0],
                "model": key[1],
                "method": "dynaplan",
                **group,
                "expected": EXPECTED_PER_MODEL,
                "estimated_cost_usd": cost if cost_complete else None,
            }
        )

    gate = _gate_report(manifest, rows, incomplete)
    aggregate = {
        "schema_version": 1,
        "campaign_id": CAMPAIGN_ID,
        "framework_version": FRAMEWORK_VERSION,
        "framework_benchmark_version": FRAMEWORK_BENCHMARK_VERSION,
        "derived_from_campaign": manifest["derived_from_campaign"],
        "generated_at": frozen._utc_now(),
        "registered_conditions": EXPECTED_CONDITIONS,
        "completed_conditions": len(rows),
        "incomplete_conditions": incomplete,
        "complete": not incomplete,
        "acceptance_gate_status": gate["status"],
        "acceptance_gate_passed": gate["passed"],
        "groups": aggregate_rows,
        "conditions": rows,
    }
    frozen._write_json(campaign_dir / "aggregate.json", aggregate)
    frozen._write_json(campaign_dir / "acceptance_gate_report.json", gate)

    lines = [
        "# DynaPlan v1.3 six-condition smoke",
        "",
        f"Completed: **{len(rows)}/{EXPECTED_CONDITIONS}** conditions.",
        f"Acceptance gate: **{gate['status']}**.",
        "",
        "| Provider / model | Setup | Prompt | Evaluator once | Rollback/no leak | Fallback | Valid | Calls | Tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in aggregate_rows:
        lines.append(
            "| {provider} / `{model}` | {setup_verified}/{completed} | "
            "{prompt_contract_verified}/{completed} | "
            "{final_evaluator_once}/{completed} | "
            "{rollback_no_leakage}/{completed} | "
            "{fallback_policy}/{completed} | {valid}/{completed} | "
            "{calls:,} | {tokens:,} |".format(**row)
        )
    if incomplete:
        lines.extend(
            (
                "",
                "This is a progress report. Incomplete condition IDs are in "
                "`aggregate.json`; the acceptance gate remains pending.",
            )
        )
    (campaign_dir / "aggregate.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    gate_lines = [
        "# DynaPlan v1.3 smoke acceptance gate",
        "",
        f"Status: **{gate['status']}**",
        "",
        "| Check | Status | Requirement |",
        "|---|---|---|",
    ]
    for item in gate["checks"]:
        gate_lines.append(
            f"| `{item['check_id']}` | {item['status']} | "
            f"{item['requirement']} |"
        )
    (campaign_dir / "acceptance_gate_report.md").write_text(
        "\n".join(gate_lines) + "\n", encoding="utf-8"
    )
    print(
        f"Smoke aggregate written: {len(rows)}/{EXPECTED_CONDITIONS} "
        f"complete; gate={gate['status']}; "
        f"{campaign_dir / 'acceptance_gate_report.json'}"
    )
    return aggregate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--register", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--report", action="store_true")
    parser.add_argument("--campaign-dir", type=Path, default=DEFAULT_CAMPAIGN_DIR)
    parser.add_argument("--env-file", type=Path, default=DYNAPLAN_ROOT / ".env")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--provider", choices=frozen.EXPECTED_PROVIDERS)
    parser.add_argument(
        "--benchmark", choices=("logistics", "blocksworld", "flat-hanoi")
    )
    parser.add_argument("--condition-id", action="append", default=[])
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.jobs < 1:
        raise frozen.SweepError("--jobs must be positive")
    campaign_dir = args.campaign_dir.resolve()
    try:
        if args.register:
            register(campaign_dir)
        elif args.execute:
            execute(
                campaign_dir,
                env_file=args.env_file.resolve(),
                jobs=args.jobs,
                provider=args.provider,
                benchmark=args.benchmark,
                condition_ids=args.condition_id,
            )
        elif args.report:
            report(campaign_dir)
        else:
            manifest = verify(campaign_dir)
            print(
                f"Manifest verified: {manifest['condition_count']} conditions; "
                "no model inference performed"
            )
        return 0
    except frozen.SweepError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
