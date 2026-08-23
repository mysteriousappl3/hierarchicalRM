from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from blocks_world_benchmark import MODES, RESULTS_DIR, run_mode
from blocks_world_task import build_paper_task
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
        description="Run and plot a four-condition Blocks World complexity sweep."
    )
    parser.add_argument("--min-blocks", type=int, default=4)
    parser.add_argument("--max-blocks", type=int, default=12)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument(
        "--reasoning",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
        default="medium",
    )
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument(
        "--max-replans",
        type=int,
        default=2,
        help="Additional attempts allowed for verifier/framework conditions.",
    )
    parser.add_argument(
        "--resume",
        default=None,
        help="Existing sweep summary.json to resume without repeating completed cells.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.min_blocks < 2 or args.max_blocks < args.min_blocks:
        raise ValueError("Require 2 <= min-blocks <= max-blocks")
    load_env_file(Path(args.env_file))
    client = create_client(args.provider, args.model, args.base_url, args.reasoning)

    if args.resume:
        summary_path = Path(args.resume).resolve()
        summary = read_json(summary_path)
        rows = list(summary.get("runs", []))
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", args.model)
        sweep_dir = (
            RESULTS_DIR
            / safe_model
            / "sweeps"
            / f"blocks_world_{args.min_blocks}_to_{args.max_blocks}_{stamp}"
        )
        sweep_dir.mkdir(parents=True, exist_ok=False)
        summary_path = sweep_dir / "summary.json"
        rows: List[Dict[str, object]] = []

    completed = {
        (int(row["block_count"]), str(row["mode"]))
        for row in rows
        if "block_count" in row and "mode" in row
    }
    for block_count in range(args.min_blocks, args.max_blocks + 1):
        task = build_paper_task(block_count)
        for mode in MODES:
            if (block_count, mode) in completed:
                continue
            print(f"START N={block_count} mode={mode}", flush=True)
            try:
                row = run_mode(
                    task=task,
                    mode=mode,
                    client=client,
                    max_tokens=args.max_tokens,
                    max_replans=args.max_replans,
                    reasoning_effort=args.reasoning,
                )
            except Exception as exc:  # Persist API failures so the sweep can resume.
                row = {
                    "task_id": task.id,
                    "block_count": block_count,
                    "mode": mode,
                    "provider": args.provider,
                    "model": args.model,
                    "reasoning_effort": args.reasoning,
                    "solved": False,
                    "legal": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            rows.append(row)
            write_summary(summary_path, args, rows)
            print(
                f"DONE N={block_count} mode={mode} solved={row.get('solved')} "
                f"moves={row.get('move_count', 0)} calls={row.get('model_call_count', 0)}",
                flush=True,
            )

    write_summary(summary_path, args, rows)
    csv_path = summary_path.with_name("summary.csv")
    write_csv(csv_path, rows)
    figure_path = FIGURES_DIR / figure_filename(args)
    plot_results(rows, figure_path, args)
    print(f"SUMMARY={summary_path}")
    print(f"CSV={csv_path}")
    print(f"FIGURE={figure_path}")
    return 0


def write_summary(
    path: Path, args: argparse.Namespace, rows: List[Dict[str, object]]
) -> None:
    payload = {
        "benchmark": "blocks_world_four_condition_sweep",
        "model": args.model,
        "provider": args.provider,
        "reasoning_effort": args.reasoning,
        "min_blocks": args.min_blocks,
        "max_blocks": args.max_blocks,
        "max_replans": args.max_replans,
        "max_tokens": args.max_tokens,
        "trials_per_cell": 1,
        "success_definition": "solved=true and legal=true",
        "runs": rows,
    }
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    fields = [
        "block_count",
        "mode",
        "solved",
        "legal",
        "move_count",
        "optimal_move_count",
        "attempt_count",
        "replan_count",
        "model_call_count",
        "h0_call_count",
        "h1_call_count",
        "h2_call_count",
        "max_hierarchy_level",
        "runtime_seconds",
        "result_dir",
        "illegal_reason",
        "error",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def plot_results(
    rows: List[Dict[str, object]], path: Path, args: argparse.Namespace
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    path.parent.mkdir(parents=True, exist_ok=True)
    styles = {
        "no-framework": {"color": "#30343B", "marker": "o", "linestyle": "-"},
        "inner-outer": {"color": "#168B79", "marker": "s", "linestyle": "--"},
        "h1-h2": {"color": "#D17B21", "marker": "^", "linestyle": "-."},
        "complete-framework": {"color": "#3E67B1", "marker": "D", "linestyle": ":"},
    }
    fig, (success_ax, calls_ax) = plt.subplots(
        2,
        1,
        figsize=(11, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [1.3, 1]},
    )
    ordered_rows = sorted(rows, key=lambda row: (int(row["block_count"]), str(row["mode"])))
    for mode in MODES:
        values = [row for row in ordered_rows if row.get("mode") == mode]
        x = [int(row["block_count"]) for row in values]
        success = [100 if row.get("solved") and row.get("legal") else 0 for row in values]
        calls = [int(row.get("model_call_count") or 0) for row in values]
        success_ax.plot(
            x,
            success,
            linewidth=2,
            markersize=6,
            label=MODE_LABELS[mode],
            **styles[mode],
        )
        calls_ax.plot(x, calls, linewidth=2, markersize=6, **styles[mode])

    success_ax.set_title(
        f"Blocks World: {args.model} ({args.reasoning} reasoning)",
        fontsize=15,
        pad=54,
    )
    success_ax.set_ylabel("Exact task success (%)")
    success_ax.set_ylim(-8, 108)
    success_ax.set_yticks([0, 100], labels=["0 (failed)", "100 (solved)"])
    success_ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.08),
        frameon=False,
        ncol=2,
    )
    calls_ax.set_ylabel("Model calls")
    calls_ax.set_xlabel("Complexity (number of blocks, N)")
    calls_ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    calls_ax.set_xticks(range(args.min_blocks, args.max_blocks + 1))
    for axis in (success_ax, calls_ax):
        axis.grid(axis="both", color="#D9DDE3", linewidth=0.8)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
    fig.text(
        0.5,
        0.015,
        f"One run per condition; max {args.max_replans} replans. Success requires legal execution and exact final goal.",
        ha="center",
        fontsize=9,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_filename(args: argparse.Namespace) -> str:
    safe_model = re.sub(r"[^A-Za-z0-9]+", "_", args.model).strip("_").lower()
    return (
        f"blocks_world_{safe_model}_{args.reasoning}_n"
        f"{args.min_blocks}_to_n{args.max_blocks}_four_conditions.png"
    )


def read_json(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


if __name__ == "__main__":
    raise SystemExit(main())
