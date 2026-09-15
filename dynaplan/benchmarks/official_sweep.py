#!/usr/bin/env python3
"""Register, verify, and resume the frozen two-model DynaPlan comparison.

Registration is offline. Paid inference requires ``--execute`` and an existing
manifest whose Git identity, source hashes, task registry, and condition matrix
still match. Completed or partial artifacts are never overwritten.
"""

from __future__ import annotations

import argparse
import concurrent.futures
from collections import defaultdict
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


SCRIPT_PATH = Path(__file__).resolve()
BENCHMARKS_ROOT = SCRIPT_PATH.parent
DYNAPLAN_ROOT = BENCHMARKS_ROOT.parent
WORKSPACE_ROOT = DYNAPLAN_ROOT.parent
RUNNER_PATH = BENCHMARKS_ROOT / "benchmark.py"
SPEC_PATH = BENCHMARKS_ROOT / "official_sweep_v1.json"
DEFAULT_CAMPAIGN_DIR = (
    BENCHMARKS_ROOT / "results" / "official_two_model_sweep_registered_v1"
)
EXPECTED_METHODS = (
    "base",
    "dynaplan",
    "adaplan-h",
    "tdp",
    "adapt",
    "reactree",
    "aot-plus",
    "llm-p",
)
EXPECTED_PROVIDERS = ("openai", "anthropic")
EXPECTED_CONDITION_COUNT = 720


class SweepError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SweepError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise SweepError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _append_jsonl(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(DYNAPLAN_ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SweepError(completed.stderr.strip() or "Git command failed")
    return completed.stdout.strip()


def _git_identity(require_clean: bool = True) -> Dict[str, str]:
    root = Path(_git("rev-parse", "--show-toplevel")).resolve()
    if root != DYNAPLAN_ROOT:
        raise SweepError(f"official Git root must be {DYNAPLAN_ROOT}, found {root}")
    status = _git("status", "--porcelain", "--untracked-files=all")
    if require_clean and status:
        raise SweepError("official repository is not clean; commit or remove changes")
    commit = _git("rev-parse", "HEAD")
    tag = _git("describe", "--exact-match", "--tags", "HEAD")
    return {"root": str(root), "commit": commit, "tag": tag}


def _selected_task_files(spec: Mapping[str, Any]) -> Iterable[Path]:
    lexicon = BENCHMARKS_ROOT / "LexiCon" / "domains"
    required = (
        "domain.pddl",
        "problem.pddl",
        "compiled_domain.pddl",
        "compiled_problem.pddl",
        "constrained_plan",
        "unconstrained_problem.pddl",
        "data",
        "nl",
    )
    for domain in ("logistics", "blocksworld"):
        for chain in spec["benchmarks"][domain]["chains"]:
            for constraint, packed_id in chain["packed_ids"].items():
                root = (
                    lexicon
                    / domain
                    / "data"
                    / f"data_{constraint}"
                    / str(packed_id)
                )
                for name in required:
                    path = root / name
                    if not path.is_file():
                        raise SweepError(f"registered task artifact is missing: {path}")
                    yield path
    data_root = BENCHMARKS_ROOT / "Flat-Hanoi" / "flat_hanoi" / "data"
    for name in (
        "paper_baseline_v1.jsonl",
        "paper_baseline_v1.manifest.json",
        "paper_extension_n6_n7_v1.jsonl",
        "paper_extension_n6_n7_v1.manifest.json",
    ):
        path = data_root / name
        if not path.is_file():
            raise SweepError(f"registered Hanoi artifact is missing: {path}")
        yield path


def _source_files(spec: Mapping[str, Any]) -> List[Path]:
    explicit = [
        SCRIPT_PATH,
        RUNNER_PATH,
        SPEC_PATH,
        BENCHMARKS_ROOT / "COMPARISON_PROMPT_PROTOCOL.md",
        DYNAPLAN_ROOT / "OFFICIAL_RUN_READINESS_REPORT.md",
        WORKSPACE_ROOT / "paper-tables" / "runs.md",
    ]
    recursive_roots = [
        DYNAPLAN_ROOT / "baselines" / "dynaplan",
        WORKSPACE_ROOT / "simmer-style-libero" / "benchmarking" / "baselines",
    ]
    shared_names = (
        "comparison_protocol.py",
        "models.py",
        "hanoi_benchmark.py",
        "lexicon_logistics_benchmark.py",
        "lexicon_logistics_task.py",
        "lexicon_baseline_benchmark.py",
        "lexicon_blocksworld_benchmark.py",
        "lexicon_blocksworld_task.py",
        "lexicon_blocksworld_baseline_benchmark.py",
        "flat_hanoi_task_loader.py",
        "flat_hanoi_baseline_core.py",
        "flat_hanoi_baseline_benchmark.py",
        "flat_hanoi_baselines.py",
        "scoring.py",
        "task_loader.py",
    )
    shared_root = WORKSPACE_ROOT / "simmer-style-libero" / "benchmarking"
    explicit.extend(shared_root / name for name in shared_names)
    files = set(explicit)
    for root in recursive_roots:
        files.update(
            path
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix in {".py", ".json", ".md"}
        )
    files.update(_selected_task_files(spec))
    missing = [path for path in files if not path.is_file()]
    if missing:
        raise SweepError(f"source lock contains missing files: {missing}")
    return sorted(files)


def _lock_key(path: Path) -> str:
    try:
        return "official/" + str(path.relative_to(DYNAPLAN_ROOT))
    except ValueError:
        return "workspace/" + str(path.relative_to(WORKSPACE_ROOT))


def _source_lock(spec: Mapping[str, Any]) -> Dict[str, str]:
    return {_lock_key(path): _sha256(path) for path in _source_files(spec)}


def _validate_task_registry(spec: Mapping[str, Any]) -> None:
    levels = {"1", "3", "5", "7", "10"}
    flat = spec["benchmarks"]["flat-hanoi"]["tasks"]
    if len(flat) != 15:
        raise SweepError("Flat-Hanoi registry must contain exactly 15 tasks")
    for rings in range(3, 8):
        tasks = [task for task in flat if int(task["rings"]) == rings]
        if len(tasks) != 3:
            raise SweepError(f"Flat-Hanoi n={rings} must contain three tasks")

    for domain in ("logistics", "blocksworld"):
        chains = spec["benchmarks"][domain]["chains"]
        if len(chains) != 3:
            raise SweepError(f"{domain} must contain exactly three chains")
        for chain in chains:
            if set(chain["packed_ids"]) != levels:
                raise SweepError(f"{domain} chain does not cover all c levels")
            expected = chain["unconstrained_problem_sha256"]
            for constraint, packed_id in chain["packed_ids"].items():
                path = (
                    BENCHMARKS_ROOT
                    / "LexiCon"
                    / "domains"
                    / domain
                    / "data"
                    / f"data_{constraint}"
                    / str(packed_id)
                    / "unconstrained_problem.pddl"
                )
                if _sha256(path) != expected:
                    raise SweepError(
                        f"{domain} c={constraint},id={packed_id} is not in its "
                        "registered underlying-world chain"
                    )


def _expand_tasks(spec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    for task in spec["benchmarks"]["flat-hanoi"]["tasks"]:
        tasks.append(
            {
                "benchmark": "flat-hanoi",
                "coordinate": task["task_id"],
                "hanoi_task": task["task_id"],
                "rings": int(task["rings"]),
            }
        )
    for domain in ("logistics", "blocksworld"):
        for chain_index, chain in enumerate(
            spec["benchmarks"][domain]["chains"], start=1
        ):
            for constraint in (1, 3, 5, 7, 10):
                packed_id = int(chain["packed_ids"][str(constraint)])
                tasks.append(
                    {
                        "benchmark": domain,
                        "coordinate": f"c{constraint}-id{packed_id}",
                        "constraints": constraint,
                        "lexicon_id": packed_id,
                        "chain_index": chain_index,
                        "generation_seed": chain.get("generation_seed"),
                    }
                )
    if len(tasks) != 45:
        raise SweepError(f"task expansion produced {len(tasks)}, expected 45")
    return tasks


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _conditions(spec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    conditions: List[Dict[str, Any]] = []
    for model in spec["models"]:
        for method in spec["methods"]:
            for task in _expand_tasks(spec):
                condition_id = "--".join(
                    (
                        _slug(model["provider"]),
                        _slug(model["model"]),
                        _slug(method),
                        _slug(task["benchmark"]),
                        _slug(task["coordinate"]),
                    )
                )
                conditions.append(
                    {
                        "condition_id": condition_id,
                        "provider": model["provider"],
                        "model": model["model"],
                        "reasoning": model["reasoning"],
                        "max_output_tokens": int(model["max_output_tokens"]),
                        "thinking_budget_tokens": model["thinking_budget_tokens"],
                        "method": method,
                        **task,
                    }
                )
    ids = [condition["condition_id"] for condition in conditions]
    if len(conditions) != EXPECTED_CONDITION_COUNT or len(set(ids)) != len(ids):
        raise SweepError("condition matrix is incomplete or contains duplicate IDs")
    return conditions


def _validate_spec(spec: Mapping[str, Any]) -> None:
    if tuple(spec.get("methods", ())) != EXPECTED_METHODS:
        raise SweepError("method ordering differs from the frozen eight-method matrix")
    providers = tuple(model.get("provider") for model in spec.get("models", ()))
    if providers != EXPECTED_PROVIDERS:
        raise SweepError("model/provider ordering differs from the frozen matrix")
    if spec.get("comparison_prompt_protocol") != "shared-public-semantics-v3":
        raise SweepError("comparison prompt protocol is not the frozen v3 policy")
    if int(spec["execution"]["official_condition_count"]) != EXPECTED_CONDITION_COUNT:
        raise SweepError("registered condition count must be 720")
    _validate_task_registry(spec)
    _conditions(spec)


def register(campaign_dir: Path) -> Path:
    if campaign_dir.exists():
        raise SweepError(f"campaign directory already exists: {campaign_dir}")
    spec = _read_json(SPEC_PATH)
    _validate_spec(spec)
    identity = _git_identity(require_clean=True)
    manifest = {
        "manifest_schema_version": 1,
        "registered_at": _utc_now(),
        "campaign_id": spec["campaign_id"],
        "spec": spec,
        "spec_sha256": _canonical_sha256(spec),
        "git": identity,
        "python_executable": str(Path(sys.executable).resolve()),
        "source_lock": _source_lock(spec),
        "conditions": _conditions(spec),
        "condition_count": EXPECTED_CONDITION_COUNT,
        "execution_started": False,
    }
    campaign_dir.mkdir(parents=True, exist_ok=False)
    path = campaign_dir / "registered_manifest.json"
    _write_json(path, manifest)
    print(f"Registered {EXPECTED_CONDITION_COUNT} conditions: {path}")
    return path


def verify(campaign_dir: Path) -> Dict[str, Any]:
    manifest_path = campaign_dir / "registered_manifest.json"
    manifest = _read_json(manifest_path)
    spec = _read_json(SPEC_PATH)
    _validate_spec(spec)
    if manifest.get("spec") != spec:
        raise SweepError("registered manifest spec differs from official_sweep_v1.json")
    if manifest.get("spec_sha256") != _canonical_sha256(spec):
        raise SweepError("registered spec digest is invalid")
    if manifest.get("conditions") != _conditions(spec):
        raise SweepError("registered condition matrix is invalid")
    if manifest.get("source_lock") != _source_lock(spec):
        raise SweepError("source or benchmark artifact drift detected")
    if manifest.get("git") != _git_identity(require_clean=True):
        raise SweepError("Git commit/tag identity differs from registration")
    if manifest.get("python_executable") != str(Path(sys.executable).resolve()):
        raise SweepError("Python interpreter differs from the registered interpreter")
    return manifest


def _condition_command(
    condition: Mapping[str, Any], campaign_dir: Path, attempt: int, env_file: Path
) -> List[str]:
    run_id = f"{condition['condition_id']}--attempt-{attempt:03d}"
    command = [
        sys.executable,
        str(RUNNER_PATH),
        "--provider",
        str(condition["provider"]),
        "--model",
        str(condition["model"]),
        "--reasoning",
        str(condition["reasoning"]),
        "--baseline",
        str(condition["method"]),
        "--benchmark",
        str(condition["benchmark"]),
        "--max-output-tokens",
        str(condition["max_output_tokens"]),
        "--timeout-seconds",
        str(_read_json(SPEC_PATH)["execution"]["timeout_seconds"]),
        "--env-file",
        str(env_file),
        "--results-dir",
        str(campaign_dir / "condition_runs"),
        "--run-id",
        run_id,
        "--execute",
    ]
    if condition["provider"] == "anthropic":
        command.extend(
            ("--anthropic-thinking-budget", str(condition["thinking_budget_tokens"]))
        )
    if condition["benchmark"] == "flat-hanoi":
        command.extend(("--hanoi-task", str(condition["hanoi_task"])))
    else:
        command.extend(
            (
                "--constraints",
                str(condition["constraints"]),
                "--lexicon-id",
                str(condition["lexicon_id"]),
            )
        )
    return command


def _existing_attempts(condition_id: str, runs_root: Path) -> List[Path]:
    return sorted(runs_root.glob(f"{condition_id}--attempt-*"))


def _run_condition(
    condition: Mapping[str, Any], campaign_dir: Path, env_file: Path
) -> Dict[str, Any]:
    runs_root = campaign_dir / "condition_runs"
    attempts = _existing_attempts(str(condition["condition_id"]), runs_root)
    complete = [path for path in attempts if (path / "summary.json").is_file()]
    if complete:
        return {
            "condition_id": condition["condition_id"],
            "status": "SKIPPED_COMPLETE",
            "artifact": str(complete[-1]),
            "completed_at": _utc_now(),
        }
    attempt = len(attempts) + 1
    command = _condition_command(condition, campaign_dir, attempt, env_file)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(DYNAPLAN_ROOT),
    )
    run_dir = runs_root / f"{condition['condition_id']}--attempt-{attempt:03d}"
    return {
        "condition_id": condition["condition_id"],
        "status": "COMPLETE" if (run_dir / "summary.json").is_file() else "INCOMPLETE",
        "returncode": completed.returncode,
        "artifact": str(run_dir),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "completed_at": _utc_now(),
    }


def execute(
    campaign_dir: Path,
    *,
    env_file: Path,
    jobs: int,
    provider: Optional[str],
    baseline: Optional[str],
    benchmark: Optional[str],
) -> None:
    manifest = verify(campaign_dir)
    selected = [
        condition
        for condition in manifest["conditions"]
        if (provider is None or condition["provider"] == provider)
        and (baseline is None or condition["method"] == baseline)
        and (benchmark is None or condition["benchmark"] == benchmark)
    ]
    if not selected:
        raise SweepError("execution filters selected no registered conditions")
    if not env_file.is_file():
        raise SweepError(f"environment file is missing: {env_file}")
    event_log = campaign_dir / "execution_log.jsonl"
    print(f"Executing/resuming {len(selected)} registered conditions with jobs={jobs}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(_run_condition, condition, campaign_dir, env_file): condition
            for condition in selected
        }
        for index, future in enumerate(
            concurrent.futures.as_completed(futures), start=1
        ):
            record = future.result()
            _append_jsonl(event_log, record)
            print(
                f"[{index}/{len(selected)}] {record['condition_id']}: "
                f"{record['status']} rc={record.get('returncode', '—')}",
                flush=True,
            )


def _completed_condition_artifact(
    condition_id: str, campaign_dir: Path
) -> Optional[Path]:
    attempts = _existing_attempts(condition_id, campaign_dir / "condition_runs")
    completed = [path for path in attempts if (path / "summary.json").is_file()]
    return completed[-1] if completed else None


def report(campaign_dir: Path) -> Dict[str, Any]:
    """Write an auditable progress/final aggregate from completed conditions."""

    manifest = verify(campaign_dir)
    rows: List[Dict[str, Any]] = []
    incomplete: List[str] = []
    for condition in manifest["conditions"]:
        condition_id = str(condition["condition_id"])
        artifact = _completed_condition_artifact(condition_id, campaign_dir)
        if artifact is None:
            incomplete.append(condition_id)
            continue
        summary = _read_json(artifact / "summary.json")
        results = summary.get("results")
        if not isinstance(results, list) or len(results) != 1:
            raise SweepError(f"{artifact} must contain exactly one condition result")
        if (
            summary.get("provider") != condition["provider"]
            or summary.get("model") != condition["model"]
            or summary.get("baseline_selection") != condition["method"]
            or summary.get("benchmarks") != [condition["benchmark"]]
        ):
            raise SweepError(f"condition metadata mismatch in {artifact}")
        evaluation = results[0].get("evaluation")
        if not isinstance(evaluation, dict):
            raise SweepError(f"condition evaluation is missing in {artifact}")
        usage = summary.get("usage")
        if not isinstance(usage, dict):
            raise SweepError(f"condition usage is missing in {artifact}")
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
                "estimated_cost_usd": float(cost) if cost is not None else None,
            }
        )

    groups: Dict[tuple[str, str, str, str], Dict[str, Any]] = defaultdict(
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
        key = (row["provider"], row["model"], row["method"], row["benchmark"])
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
                "method": key[2],
                "benchmark": key[3],
                **group,
                "expected": 15,
                "estimated_cost_usd": cost if cost_complete else None,
            }
        )

    aggregate = {
        "schema_version": 1,
        "campaign_id": manifest["campaign_id"],
        "generated_at": _utc_now(),
        "registered_conditions": EXPECTED_CONDITION_COUNT,
        "completed_conditions": len(rows),
        "incomplete_conditions": incomplete,
        "complete": not incomplete,
        "groups": aggregate_rows,
        "conditions": rows,
    }
    _write_json(campaign_dir / "aggregate.json", aggregate)

    lines = [
        "# Official sweep aggregate",
        "",
        f"Completed: **{len(rows)}/{EXPECTED_CONDITION_COUNT}** conditions.",
        "",
        "| Provider / model | Method | Benchmark | Setup | Valid | Optimal | Calls | Tokens |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in aggregate_rows:
        lines.append(
            "| {provider} / `{model}` | {method} | {benchmark} | "
            "{setup_verified}/{completed} | {valid}/{completed} | "
            "{optimal}/{completed} | {calls:,} | {tokens:,} |".format(**row)
        )
    if incomplete:
        lines.extend(
            (
                "",
                "This is a progress report; incomplete conditions are listed in "
                "`aggregate.json` and are not included in any denominator above.",
            )
        )
    (campaign_dir / "aggregate.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"Aggregate written: {len(rows)}/{EXPECTED_CONDITION_COUNT} complete; "
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
    parser.add_argument("--provider", choices=EXPECTED_PROVIDERS)
    parser.add_argument("--baseline", choices=EXPECTED_METHODS)
    parser.add_argument(
        "--benchmark", choices=("logistics", "blocksworld", "flat-hanoi")
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.jobs < 1:
        raise SweepError("--jobs must be positive")
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
                baseline=args.baseline,
                benchmark=args.benchmark,
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
    except SweepError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
