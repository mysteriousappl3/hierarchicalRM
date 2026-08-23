from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional, Sequence, Tuple

from checker_jumping_benchmark import MODES, RESULTS_DIR, run_mode
from checker_jumping_task import build_paper_task
from models import create_client, load_env_file


BENCHMARK_DIR = Path(__file__).resolve().parent
FIGURES_DIR = BENCHMARK_DIR / "figures"
DEFAULT_ENV_FILE = BENCHMARK_DIR / ".env"
MODE_LABELS = {
    "no-framework": "Base model",
    "inner-outer": "Base + Inner/Outer",
    "h1-h2": "Inner/Outer + H1/H2",
    "complete-framework": "Complete N-level hierarchy",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a four-condition Checker Jumping complexity sweep."
    )
    parser.add_argument("--min-checkers", type=int, default=1)
    parser.add_argument("--max-checkers", type=int, default=15)
    parser.add_argument("--trials", type=int, default=25)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument(
        "--reasoning",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
        default="medium",
    )
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--max-replans", type=int, default=2)
    parser.add_argument(
        "--resume",
        default=None,
        help="Existing summary.json to resume without repeating completed cells.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.min_checkers < 1 or args.max_checkers < args.min_checkers:
        raise ValueError("Require 1 <= min-checkers <= max-checkers")
    if args.trials < 1:
        raise ValueError("trials must be positive")
    load_env_file(Path(args.env_file))
    client = create_client(args.provider, args.model, args.base_url, args.reasoning)
    if args.resume:
        summary_path = Path(args.resume).resolve()
        rows = list(read_json(summary_path).get("runs", []))
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", args.model)
        sweep_dir = RESULTS_DIR / safe_model / "sweeps" / f"checker_jumping_{stamp}"
        sweep_dir.mkdir(parents=True, exist_ok=False)
        summary_path = sweep_dir / "summary.json"
        rows: List[Dict[str, object]] = []

    completed = {
        (int(row["checkers_per_color"]), str(row["mode"]), int(row["trial_index"]))
        for row in rows
        if all(key in row for key in ("checkers_per_color", "mode", "trial_index"))
    }
    for size in range(args.min_checkers, args.max_checkers + 1):
        task = build_paper_task(size)
        for mode in MODES:
            for trial in range(1, args.trials + 1):
                key = (size, mode, trial)
                if key in completed:
                    continue
                print(f"START N={size} mode={mode} trial={trial}", flush=True)
                try:
                    row = run_mode(
                        task=task,
                        mode=mode,
                        client=client,
                        max_tokens=args.max_tokens,
                        max_replans=args.max_replans,
                        reasoning_effort=args.reasoning,
                    )
                except Exception as exc:
                    row = {
                        "task_id": task.id,
                        "checkers_per_color": size,
                        "total_checkers": size * 2,
                        "mode": mode,
                        "provider": args.provider,
                        "model": args.model,
                        "reasoning_effort": args.reasoning,
                        "solved": False,
                        "legal": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                row["trial_index"] = trial
                rows.append(row)
                write_summary(summary_path, args, rows)
                print(
                    f"DONE N={size} mode={mode} trial={trial} "
                    f"solved={row.get('solved')} calls={row.get('model_call_count', 0)}",
                    flush=True,
                )

    write_summary(summary_path, args, rows)
    csv_path = summary_path.with_name("summary.csv")
    aggregate_path = summary_path.with_name("aggregate.csv")
    write_csv(csv_path, rows)
    aggregates = aggregate_rows(rows)
    write_csv(aggregate_path, aggregates)
    figure_path = FIGURES_DIR / figure_filename(args)
    plot_results(aggregates, figure_path, args)
    print(f"SUMMARY={summary_path}")
    print(f"CSV={csv_path}")
    print(f"AGGREGATE={aggregate_path}")
    print(f"FIGURE={figure_path}")
    return 0


def write_summary(path: Path, args: argparse.Namespace, rows: List[Dict[str, object]]) -> None:
    payload = {
        "benchmark": "checker_jumping_four_condition_sweep",
        "model": args.model,
        "provider": args.provider,
        "reasoning_effort": args.reasoning,
        "min_checkers_per_color": args.min_checkers,
        "max_checkers_per_color": args.max_checkers,
        "trials_per_cell": args.trials,
        "max_replans": args.max_replans,
        "max_tokens": args.max_tokens,
        "success_definition": "legal=true and exact goal reached",
        "optimality_required_for_success": False,
        "runs": rows,
    }
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def aggregate_rows(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    output: List[Dict[str, object]] = []
    for size in sorted({int(row["checkers_per_color"]) for row in rows}):
        for mode in MODES:
            group = [
                row
                for row in rows
                if int(row["checkers_per_color"]) == size and row.get("mode") == mode
            ]
            if not group:
                continue
            successes = sum(bool(row.get("solved")) and bool(row.get("legal")) for row in group)
            low, high = wilson_interval(successes, len(group))
            output.append(
                {
                    "checkers_per_color": size,
                    "total_checkers": size * 2,
                    "mode": mode,
                    "trial_count": len(group),
                    "success_count": successes,
                    "success_rate": successes / len(group),
                    "success_ci_low": low,
                    "success_ci_high": high,
                    "legal_rate": mean(float(bool(row.get("legal"))) for row in group),
                    "mean_first_failure_move": optional_mean(row.get("first_failure_move") for row in group),
                    "mean_move_count": optional_mean(row.get("move_count") for row in group),
                    "mean_model_calls": optional_mean(row.get("model_call_count") for row in group),
                    "mean_total_tokens": optional_mean(
                        token_total(row) for row in group
                    ),
                    "mean_max_hierarchy_level": optional_mean(
                        row.get("max_hierarchy_level") for row in group
                    ),
                }
            )
    return output


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    if trials <= 0:
        return 0.0, 0.0
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * trials)) / trials) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def optional_mean(values) -> Optional[float]:
    present = [float(value) for value in values if value is not None]
    return mean(present) if present else None


def token_total(row: Dict[str, object]) -> Optional[int]:
    usage = row.get("token_usage")
    return int(usage.get("total_tokens", 0)) if isinstance(usage, dict) else None


def write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def plot_results(rows: Sequence[Dict[str, object]], path: Path, args: argparse.Namespace) -> None:
    import matplotlib.pyplot as plt

    styles = {
        "no-framework": {"color": "#30343B", "marker": "o", "linestyle": "-"},
        "inner-outer": {"color": "#168B79", "marker": "s", "linestyle": "--"},
        "h1-h2": {"color": "#D17B21", "marker": "^", "linestyle": "-."},
        "complete-framework": {"color": "#3E67B1", "marker": "D", "linestyle": ":"},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(3, 2, figsize=(12, 13), sharex=True)
    panels = [
        ("success_rate", "Exact success (%)", 100),
        ("legal_rate", "Legal-plan rate (%)", 100),
        ("mean_first_failure_move", "Mean first failure move", 1),
        ("mean_model_calls", "Mean model calls", 1),
        ("mean_total_tokens", "Mean total tokens", 1),
        ("mean_max_hierarchy_level", "Mean maximum hierarchy level", 1),
    ]
    for mode in MODES:
        values = sorted(
            (row for row in rows if row.get("mode") == mode),
            key=lambda row: int(row["checkers_per_color"]),
        )
        x = [int(row["checkers_per_color"]) for row in values]
        for axis, (field, ylabel, scale) in zip(axes.flat, panels):
            y = [
                float(row[field]) * scale if row.get(field) is not None else float("nan")
                for row in values
            ]
            axis.plot(x, y, linewidth=2, markersize=5, label=MODE_LABELS[mode], **styles[mode])
            axis.set_ylabel(ylabel)
            axis.grid(color="#D9DDE3", linewidth=0.8)
            axis.spines["top"].set_visible(False)
            axis.spines["right"].set_visible(False)
        success_axis = axes.flat[0]
        lower = [float(row["success_ci_low"]) * 100 for row in values]
        upper = [float(row["success_ci_high"]) * 100 for row in values]
        success_axis.fill_between(x, lower, upper, color=styles[mode]["color"], alpha=0.1)
    for axis in axes[-1]:
        axis.set_xlabel("Complexity (checkers per color, N)")
        axis.set_xticks(range(args.min_checkers, args.max_checkers + 1))
    axes.flat[0].set_ylim(-5, 105)
    fig.suptitle(
        f"Checker Jumping: {args.model} ({args.reasoning} reasoning, {args.trials} trials/cell)",
        fontsize=15,
    )
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.965), ncol=2, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_filename(args: argparse.Namespace) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", args.model).strip("_").lower()
    return (
        f"checker_jumping_{safe}_{args.reasoning}_n{args.min_checkers}_to_"
        f"n{args.max_checkers}_{args.trials}_trials_four_conditions.png"
    )


def read_json(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


if __name__ == "__main__":
    raise SystemExit(main())
