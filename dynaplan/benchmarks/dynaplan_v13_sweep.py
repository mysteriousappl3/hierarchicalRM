#!/usr/bin/env python3
"""Run the frozen 90-condition DynaPlan v1.3 two-model campaign.

The models, reasoning budgets, generation policy, and 45 tasks are inherited
byte-for-byte from the official v1 registry; this launcher selects only the
DynaPlan method.  Registration and verification are offline.  Paid inference
occurs only when this script is invoked explicitly with ``--execute``.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import concurrent.futures
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

import official_sweep as frozen


SCRIPT_PATH = Path(__file__).resolve()
BENCHMARKS_ROOT = SCRIPT_PATH.parent
DYNAPLAN_ROOT = BENCHMARKS_ROOT.parent
SPEC_PATH = BENCHMARKS_ROOT / "official_sweep_v1.json"
DEFAULT_CAMPAIGN_DIR = (
    BENCHMARKS_ROOT
    / "results"
    / "dynaplan_v13_compact_fallback_two_model_matched_3x_20260915"
)
CAMPAIGN_ID = "dynaplan_v13_compact_fallback_two_model_matched_3x_20260915"
DEFAULT_SMOKE_CAMPAIGN_DIR = (
    BENCHMARKS_ROOT
    / "results"
    / "dynaplan_v13_compact_fallback_smoke_6_20260915"
)
SMOKE_CAMPAIGN_ID = "dynaplan_v13_compact_fallback_smoke_6_20260915"
SMOKE_GATE_REVISION = "dynaplan_v13_smoke_acceptance_gate_v1"
FRAMEWORK_VERSION = "dynaplan_v1_3_compact_fallback"
FRAMEWORK_BENCHMARK_VERSION = 61
EXPECTED_CONDITIONS = 90
FROZEN_SPEC_SHA256 = (
    "67bf3e8b35d975a72d43c7384f426a26f4247a09e5dc9e531e78d533bb4a0d7b"
)
V13_FEATURE_FLAGS = (
    "compact_generation_contracts",
    "exhaustion_candidate_fallback",
    "lenient_irrelevant_evidence_fields",
)


def _spec() -> Dict[str, Any]:
    spec = frozen._read_json(SPEC_PATH)
    frozen._validate_spec(spec)
    if frozen._canonical_sha256(spec) != FROZEN_SPEC_SHA256:
        raise frozen.SweepError("official frozen sweep registry digest changed")
    return spec


def _conditions(spec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    conditions = [
        condition
        for condition in frozen._conditions(spec)
        if condition["method"] == "dynaplan"
    ]
    if len(conditions) != EXPECTED_CONDITIONS:
        raise frozen.SweepError(
            f"DynaPlan matrix has {len(conditions)} conditions; "
            f"expected {EXPECTED_CONDITIONS}"
        )
    if len({item["condition_id"] for item in conditions}) != len(conditions):
        raise frozen.SweepError("DynaPlan condition IDs are not unique")
    return conditions


def _source_lock(spec: Mapping[str, Any]) -> Dict[str, str]:
    lock = frozen._source_lock(spec)
    lock["official/benchmarks/dynaplan_v13_sweep.py"] = frozen._sha256(
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


def _validated_smoke_prerequisite(smoke_campaign_dir: Path) -> Dict[str, Any]:
    report_path = smoke_campaign_dir.resolve() / "acceptance_gate_report.json"
    report = frozen._read_json(report_path)
    definition = report.get("definition")
    if (
        report.get("campaign_id") != SMOKE_CAMPAIGN_ID
        or report.get("framework_version") != FRAMEWORK_VERSION
        or report.get("framework_benchmark_version")
        != FRAMEWORK_BENCHMARK_VERSION
        or report.get("status") != "PASS"
        or report.get("passed") is not True
        or report.get("completed_conditions") != 6
        or not isinstance(definition, Mapping)
        or definition.get("revision") != SMOKE_GATE_REVISION
        or definition.get("declared_before_execution") is not True
    ):
        raise frozen.SweepError(
            "full v1.3 registration requires the matching six-condition "
            "smoke acceptance gate to pass"
        )
    return {
        "campaign_id": SMOKE_CAMPAIGN_ID,
        "campaign_dir": str(smoke_campaign_dir.resolve()),
        "framework_version": FRAMEWORK_VERSION,
        "framework_benchmark_version": FRAMEWORK_BENCHMARK_VERSION,
        "gate_revision": SMOKE_GATE_REVISION,
        "report_path": str(report_path),
        "report_sha256": frozen._sha256(report_path),
        "status": "PASS",
        "passed": True,
    }


def _verify_smoke_prerequisite(value: object) -> None:
    if not isinstance(value, Mapping):
        raise frozen.SweepError("registered smoke prerequisite is missing")
    report_value = value.get("report_path")
    if not isinstance(report_value, str):
        raise frozen.SweepError("registered smoke report path is missing")
    expected = _validated_smoke_prerequisite(Path(report_value).parent)
    if dict(value) != expected:
        raise frozen.SweepError(
            "registered smoke acceptance report changed after full registration"
        )


def register(
    campaign_dir: Path,
    *,
    smoke_campaign_dir: Path = DEFAULT_SMOKE_CAMPAIGN_DIR,
) -> None:
    if campaign_dir.exists():
        raise frozen.SweepError(
            f"campaign directory already exists: {campaign_dir}"
        )
    spec = _spec()
    conditions = _conditions(spec)
    framework = _framework_manifest()
    smoke_prerequisite = _validated_smoke_prerequisite(smoke_campaign_dir)
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
        "smoke_gate_prerequisite": smoke_prerequisite,
        "resumability": "completed conditions are skipped; partial attempts are retained",
        "execution_requires_explicit_flag": "--execute",
        "automatically_triggered_by_smoke": False,
        "execution_started": False,
    }
    campaign_dir.mkdir(parents=True, exist_ok=False)
    frozen._write_json(campaign_dir / "registered_manifest.json", manifest)
    print(
        f"Registered {EXPECTED_CONDITIONS} DynaPlan v1.3 conditions: "
        f"{campaign_dir / 'registered_manifest.json'}"
    )


def verify(campaign_dir: Path) -> Dict[str, Any]:
    manifest = frozen._read_json(campaign_dir / "registered_manifest.json")
    spec = _spec()
    expected_conditions = _conditions(spec)
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
        raise frozen.SweepError("registered DynaPlan condition matrix changed")
    if manifest.get("condition_count") != EXPECTED_CONDITIONS:
        raise frozen.SweepError("registered condition count mismatch")
    if manifest.get("source_lock") != _source_lock(spec):
        raise frozen.SweepError("DynaPlan v1.3 source or task artifact drifted")
    if manifest.get("git_commit") != frozen._git("rev-parse", "HEAD"):
        raise frozen.SweepError("Git commit changed after registration")
    if manifest.get("python_executable") != str(Path(sys.executable).resolve()):
        raise frozen.SweepError("Python interpreter changed after registration")
    if manifest.get("automatically_triggered_by_smoke") is not False:
        raise frozen.SweepError("full sweep explicit-invocation policy changed")
    _verify_smoke_prerequisite(manifest.get("smoke_gate_prerequisite"))
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
        f"Executing/resuming {len(ordered)} DynaPlan v1.3 conditions "
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


def _condition_row(
    condition: Mapping[str, Any], artifact: Path
) -> Dict[str, Any]:
    summary = frozen._read_json(artifact / "summary.json")
    results = summary.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise frozen.SweepError(f"{artifact} must contain exactly one result")
    result = results[0]
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
    expected_thinking = condition["thinking_budget_tokens"]
    observed_thinking = summary.get("anthropic_thinking_budget_tokens")
    if observed_thinking != expected_thinking:
        raise frozen.SweepError(f"thinking budget mismatch in {artifact}")
    if result.get("architecture_version") != FRAMEWORK_VERSION:
        raise frozen.SweepError(f"condition architecture mismatch in {artifact}")
    method_metrics = result.get("method_metrics")
    if not isinstance(method_metrics, Mapping) or any(
        method_metrics.get(name) is not True for name in V13_FEATURE_FLAGS
    ):
        raise frozen.SweepError(f"v1.3 feature telemetry mismatch in {artifact}")
    native_dir_value = result.get("native_result_dir")
    native_dir = Path(native_dir_value) if isinstance(native_dir_value, str) else None
    if (
        native_dir is None
        or not native_dir.is_dir()
        or not (native_dir / "metrics.json").is_file()
    ):
        candidates = sorted(
            path.parent
            for path in artifact.rglob("metrics.json")
            if (path.parent / "steps.json").is_file()
        )
        native_dir = candidates[0] if len(candidates) == 1 else None
    if native_dir is None:
        raise frozen.SweepError(f"native DynaPlan metrics are missing in {artifact}")
    try:
        native_dir.resolve().relative_to(artifact.resolve())
    except ValueError as error:
        raise frozen.SweepError(
            f"native DynaPlan metrics resolve outside {artifact}"
        ) from error
    native_metrics = frozen._read_json(native_dir / "metrics.json")
    if (
        native_metrics.get("architecture_version") != FRAMEWORK_VERSION
        or native_metrics.get("benchmark_version")
        != FRAMEWORK_BENCHMARK_VERSION
    ):
        raise frozen.SweepError(f"native version mismatch in {artifact}")
    cost = summary.get("estimated_cost_usd")
    return {
        **condition,
        "artifact": str(artifact),
        "setup_verified": bool(result.get("setup_verified")),
        "prompt_contract_verified": bool(
            result.get("prompt_contract_verified")
        ),
        "final_evaluator_once": bool(result.get("final_evaluator_once")),
        "success": bool(evaluation.get("success")),
        "optimal": bool(evaluation.get("optimal")),
        "status": evaluation.get("status"),
        "submitted_length": evaluation.get("submitted_length"),
        "optimal_length": evaluation.get("optimal_length"),
        "model_calls": int(summary.get("model_call_count", 0)),
        "tokens": int(usage.get("total_tokens", 0)),
        "estimated_cost_usd": float(cost) if cost is not None else None,
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

    groups: Dict[tuple[str, str, str], Dict[str, Any]] = defaultdict(
        lambda: {
            "completed": 0,
            "setup_verified": 0,
            "prompt_contract_verified": 0,
            "final_evaluator_once": 0,
            "valid": 0,
            "optimal": 0,
            "calls": 0,
            "tokens": 0,
            "estimated_cost_usd": 0.0,
            "cost_complete": True,
        }
    )
    for row in rows:
        key = (row["provider"], row["model"], row["benchmark"])
        group = groups[key]
        group["completed"] += 1
        group["setup_verified"] += int(row["setup_verified"])
        group["prompt_contract_verified"] += int(
            row["prompt_contract_verified"]
        )
        group["final_evaluator_once"] += int(row["final_evaluator_once"])
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
                "benchmark": key[2],
                **group,
                "expected": 15,
                "estimated_cost_usd": cost if cost_complete else None,
            }
        )

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
        "groups": aggregate_rows,
        "conditions": rows,
    }
    frozen._write_json(campaign_dir / "aggregate.json", aggregate)

    lines = [
        "# DynaPlan v1.3 compact/fallback matched two-model sweep",
        "",
        f"Completed: **{len(rows)}/{EXPECTED_CONDITIONS}** conditions.",
        "",
        "| Provider / model | Benchmark | Setup | Prompt | Evaluator once | Valid | Optimal | Calls | Tokens |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in aggregate_rows:
        lines.append(
            "| {provider} / `{model}` | {benchmark} | "
            "{setup_verified}/{completed} | "
            "{prompt_contract_verified}/{completed} | "
            "{final_evaluator_once}/{completed} | "
            "{valid}/{completed} | {optimal}/{completed} | "
            "{calls:,} | {tokens:,} |".format(**row)
        )
    if incomplete:
        lines.extend(
            (
                "",
                "This is a progress report. Incomplete condition IDs are in "
                "`aggregate.json` and excluded from denominators above.",
            )
        )
    (campaign_dir / "aggregate.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(
        f"Aggregate written: {len(rows)}/{EXPECTED_CONDITIONS} complete; "
        f"{campaign_dir / 'aggregate.json'}"
    )
    return aggregate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--register", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--report", action="store_true")
    parser.add_argument("--campaign-dir", type=Path, default=DEFAULT_CAMPAIGN_DIR)
    parser.add_argument(
        "--smoke-campaign-dir",
        type=Path,
        default=DEFAULT_SMOKE_CAMPAIGN_DIR,
        help="passing v1.3 smoke campaign required only for --register",
    )
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
            register(
                campaign_dir,
                smoke_campaign_dir=args.smoke_campaign_dir.resolve(),
            )
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
