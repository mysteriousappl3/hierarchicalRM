from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from model_registry import DEFAULT_REGISTRY, get_model


HERE = Path(__file__).resolve().parent
BENCHMARK_DIR = HERE.parent
BENCHMARK_SCRIPT = BENCHMARK_DIR / "hanoi_benchmark.py"
DYNAMIC_BENCHMARK_SCRIPT = BENCHMARK_DIR / "dynamic_hierarchy_benchmark.py"
MANIFEST_DIR = BENCHMARK_DIR / "results" / "_batch_manifests"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Hanoi tasks against a registered local model.")
    parser.add_argument("model_key")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--task", default="all", help="hanoi_3 through hanoi_12, or all")
    parser.add_argument(
        "--mode",
        choices=["direct", "inner-outer", "hierarchy", "dynamic-hierarchy"],
        default="hierarchy",
    )
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--max-replans", type=int, default=15)
    parser.add_argument("--fixed-goal", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def benchmark_command(args: argparse.Namespace, config: dict) -> List[str]:
    port = args.port if args.port is not None else int(config["port"])
    script = DYNAMIC_BENCHMARK_SCRIPT if args.mode == "dynamic-hierarchy" else BENCHMARK_SCRIPT
    command = [
        sys.executable,
        str(script),
        "--task",
        args.task,
        "--provider",
        "local",
        "--model",
        str(config["served_model_name"]),
        "--base-url",
        f"http://{args.host}:{port}/v1/chat/completions",
        "--max-tokens",
        str(args.max_tokens),
        "--max-replans",
        str(args.max_replans),
    ]
    if args.mode == "direct":
        command.append("--no-framework")
    elif args.mode == "inner-outer":
        command.extend(["--no-framework", "--inner-outer"])
    if args.fixed_goal:
        command.append("--fixed-goal")
    return command


def main() -> int:
    args = parse_args()
    if args.repetitions < 1:
        raise ValueError("--repetitions must be at least 1")
    config = get_model(args.model_key, args.registry)
    command = benchmark_command(args, config)
    print(subprocess.list2cmdline(command))
    if args.dry_run:
        return 0

    started = datetime.now(timezone.utc)
    runs = []
    for repetition in range(1, args.repetitions + 1):
        run_started = time.perf_counter()
        completed = subprocess.run(command, cwd=BENCHMARK_DIR.parent, check=False)
        runs.append(
            {
                "repetition": repetition,
                "return_code": completed.returncode,
                "elapsed_seconds": round(time.perf_counter() - run_started, 3),
            }
        )
        if completed.returncode != 0:
            break

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = started.strftime("%Y%m%d_%H%M%S")
    manifest_path = MANIFEST_DIR / f"{args.model_key}_{args.mode}_{args.task}_{timestamp}.json"
    manifest = {
        "model_key": args.model_key,
        "model": config,
        "mode": args.mode,
        "task": args.task,
        "requested_repetitions": args.repetitions,
        "started_at": started.isoformat(),
        "command": command,
        "runs": runs,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Batch manifest: {manifest_path}")
    succeeded = len(runs) == args.repetitions and all(run["return_code"] == 0 for run in runs)
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
