#!/usr/bin/env python3
"""Run the matched 90-condition DynaPlan v1.1 two-model campaign.

This derives its models and 45-task matrix from ``official_sweep_v1.json`` but
selects only DynaPlan.  It deliberately writes to a new campaign directory and
uses a source-file lock instead of relabelling the completed frozen v1 sweep.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import concurrent.futures
import json
from pathlib import Path
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
    / "dynaplan_v11_two_model_matched_3x_20260915"
)
CAMPAIGN_ID = "dynaplan_v11_two_model_matched_3x_20260915"
FRAMEWORK_VERSION = "dynaplan_final_nlevel_hierarchy_v1_1"
EXPECTED_CONDITIONS = 90


def _spec() -> Dict[str, Any]:
    spec = frozen._read_json(SPEC_PATH)
    frozen._validate_spec(spec)
    return spec


def _conditions(spec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    conditions = [
        condition
        for condition in frozen._conditions(spec)
        if condition["method"] == "dynaplan"
    ]
    if len(conditions) != EXPECTED_CONDITIONS:
        raise frozen.SweepError(
            f"DynaPlan condition matrix has {len(conditions)} conditions; "
            f"expected {EXPECTED_CONDITIONS}"
        )
    return conditions


def _source_lock(spec: Mapping[str, Any]) -> Dict[str, str]:
    lock = frozen._source_lock(spec)
    lock["official/benchmarks/dynaplan_v11_sweep.py"] = frozen._sha256(
        SCRIPT_PATH
    )
    return lock


def _framework_manifest() -> Dict[str, Any]:
    path = DYNAPLAN_ROOT / "baselines" / "dynaplan" / "framework.json"
    manifest = frozen._read_json(path)
    if manifest.get("framework_version") != FRAMEWORK_VERSION:
        raise frozen.SweepError(
            "DynaPlan framework manifest is not the registered v1.1 variant"
        )
    return manifest


def register(campaign_dir: Path) -> None:
    if campaign_dir.exists():
        raise frozen.SweepError(
            f"campaign directory already exists: {campaign_dir}"
        )
    spec = _spec()
    conditions = _conditions(spec)
    framework = _framework_manifest()
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
        "execution_started": False,
    }
    campaign_dir.mkdir(parents=True, exist_ok=False)
    frozen._write_json(campaign_dir / "registered_manifest.json", manifest)
    print(
        f"Registered {EXPECTED_CONDITIONS} DynaPlan v1.1 conditions: "
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
    if manifest.get("framework_benchmark_version") != 59:
        raise frozen.SweepError("framework benchmark version mismatch")
    if manifest.get("spec_sha256") != frozen._canonical_sha256(spec):
        raise frozen.SweepError("frozen task/model spec changed")
    if manifest.get("conditions") != expected_conditions:
        raise frozen.SweepError("registered DynaPlan condition matrix changed")
    if manifest.get("source_lock") != _source_lock(spec):
        raise frozen.SweepError("DynaPlan v1.1 source or task artifact drifted")
    if manifest.get("git_commit") != frozen._git("rev-parse", "HEAD"):
        raise frozen.SweepError("Git commit changed after registration")
    if manifest.get("python_executable") != str(Path(sys.executable).resolve()):
        raise frozen.SweepError("Python interpreter changed after registration")
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
    selected = [
        condition
        for condition in manifest["conditions"]
        if (provider is None or condition["provider"] == provider)
        and (benchmark is None or condition["benchmark"] == benchmark)
        and (
            not condition_ids
            or condition["condition_id"] in set(condition_ids)
        )
    ]
    if not selected:
        raise frozen.SweepError("execution filters selected no conditions")
    if not env_file.is_file():
        raise frozen.SweepError(f"environment file is missing: {env_file}")
    ordered = _interleave_providers(selected)
    event_log = campaign_dir / "execution_log.jsonl"
    print(
        f"Executing/resuming {len(ordered)} DynaPlan v1.1 conditions "
        f"with jobs={jobs}",
        flush=True,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(
                frozen._run_condition, condition, campaign_dir, env_file
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


def report(campaign_dir: Path) -> Dict[str, Any]:
    manifest = verify(campaign_dir)
    rows: List[Dict[str, Any]] = []
    incomplete: List[str] = []
    for condition in manifest["conditions"]:
        condition_id = str(condition["condition_id"])
        artifact = frozen._completed_condition_artifact(
            condition_id, campaign_dir
        )
        if artifact is None:
            incomplete.append(condition_id)
            continue
        summary = frozen._read_json(artifact / "summary.json")
        results = summary.get("results")
        if not isinstance(results, list) or len(results) != 1:
            raise frozen.SweepError(
                f"{artifact} must contain exactly one result"
            )
        evaluation = results[0].get("evaluation")
        usage = summary.get("usage")
        if not isinstance(evaluation, dict) or not isinstance(usage, dict):
            raise frozen.SweepError(f"{artifact} is missing evaluation or usage")
        if (
            summary.get("provider") != condition["provider"]
            or summary.get("model") != condition["model"]
            or summary.get("baseline_selection") != "dynaplan"
            or summary.get("benchmarks") != [condition["benchmark"]]
        ):
            raise frozen.SweepError(f"condition metadata mismatch in {artifact}")
        cost = summary.get("estimated_cost_usd")
        rows.append(
            {
                **condition,
                "artifact": str(artifact),
                "setup_verified": int(summary.get("setup_verified", 0)) == 1,
                "success": bool(evaluation.get("success")),
                "optimal": bool(evaluation.get("optimal")),
                "status": evaluation.get("status"),
                "submitted_length": evaluation.get("submitted_length"),
                "optimal_length": evaluation.get("optimal_length"),
                "model_calls": int(summary.get("model_call_count", 0)),
                "tokens": int(usage.get("total_tokens", 0)),
                "estimated_cost_usd": (
                    float(cost) if cost is not None else None
                ),
            }
        )

    groups: Dict[tuple[str, str, str], Dict[str, Any]] = defaultdict(
        lambda: {
            "completed": 0,
            "setup_verified": 0,
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
        "# DynaPlan v1.1 matched two-model sweep",
        "",
        f"Completed: **{len(rows)}/{EXPECTED_CONDITIONS}** conditions.",
        "",
        "| Provider / model | Benchmark | Setup | Valid | Optimal | Calls | Tokens |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in aggregate_rows:
        lines.append(
            "| {provider} / `{model}` | {benchmark} | "
            "{setup_verified}/{completed} | {valid}/{completed} | "
            "{optimal}/{completed} | {calls:,} | {tokens:,} |".format(**row)
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
