"""Generates the flat-to-flat Tower of Hanoi task grid.

Unlike the existing tower-to-tower tasks (all rings start on one peg, end on
another), flat tasks scatter rings across all three pegs in both the initial
and goal state. Per "Transformers Struggle to Use Their Emergent World
Models" (arxiv.org/html/2608.07077), the optimal path for a flat instance
depends on the specific (initial, goal) pair and cannot be produced by the
memorized tower-to-tower recursive template -- which is the entire point of
running this alongside, not instead of, the existing tower tasks.

Usage:
    python benchmarking/generate_flat_hanoi_tasks.py
    python benchmarking/generate_flat_hanoi_tasks.py --min-rings 3 --max-rings 8 --instances 25
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Dict, List, Tuple

from hanoi_solver import shortest_hanoi_move_count
from task_loader import Ring

OUTPUT_DIR = Path(__file__).resolve().parent / "tasks" / "flat"
PEGS = ["peg_a", "peg_b", "peg_c"]
RING_LABELS = [
    "smallest", "very small", "small", "medium small", "medium",
    "medium large", "large", "very large", "huge", "very huge",
    "massive", "largest",
]


def build_rings(n: int) -> List[Ring]:
    labels = RING_LABELS[:n]
    labels[-1] = "largest"
    return [Ring(name=f"ring_{i + 1}", size=i + 1, label=labels[i]) for i in range(n)]


def random_legal_state(rng: random.Random, ring_names: List[str]) -> Dict[str, List[str]]:
    """Randomly distributes rings across pegs, each peg's stack size-ordered.

    Assigns each ring (largest first) to a uniformly random peg, then appends
    it to that peg's stack. Since rings are placed largest-to-smallest, every
    resulting stack is automatically size-decreasing bottom-to-top.
    """
    state: Dict[str, List[str]] = {peg: [] for peg in PEGS}
    for ring_name in ring_names:  # already ordered largest to smallest
        peg = rng.choice(PEGS)
        state[peg].append(ring_name)
    return state


def states_equal(a: Dict[str, List[str]], b: Dict[str, List[str]]) -> bool:
    return all(a[peg] == b[peg] for peg in PEGS)


def generate_instance(
    rng: random.Random,
    n: int,
    min_optimal_moves: int,
    max_attempts: int = 200,
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]], int]:
    rings = build_rings(n)
    ring_names = [ring.name for ring in reversed(rings)]  # largest first
    sizes = {ring.name: ring.size for ring in rings}

    for _ in range(max_attempts):
        initial = random_legal_state(rng, ring_names)
        goal = random_legal_state(rng, ring_names)
        if states_equal(initial, goal):
            continue
        optimal = shortest_hanoi_move_count(initial, goal, sizes)
        if optimal is None or optimal < min_optimal_moves:
            continue
        return initial, goal, optimal

    raise RuntimeError(
        f"Could not generate a flat instance for n={n} rings after {max_attempts} attempts "
        f"(min_optimal_moves={min_optimal_moves}). Try lowering --min-optimal-moves."
    )


def build_task_json(
    task_id: str,
    n: int,
    initial: Dict[str, List[str]],
    goal: Dict[str, List[str]],
    optimal_move_count: int,
) -> Dict[str, object]:
    rings = build_rings(n)
    return {
        "id": task_id,
        "name": f"Tower of Hanoi (flat-to-flat) - {n} rings",
        "pegs": PEGS,
        "rings": [ring.__dict__ for ring in rings],
        "initial": initial,
        "goal": goal,
        "optimal_move_count": optimal_move_count,
        "instruction": (
            "Rearrange the rings so the scene matches the goal configuration. "
            "Move one ring at a time, only move the top ring of a peg, and "
            "never place a larger ring on top of a smaller ring."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate flat-to-flat Tower of Hanoi tasks.")
    parser.add_argument("--min-rings", type=int, default=3)
    parser.add_argument("--max-rings", type=int, default=8)
    parser.add_argument("--instances", type=int, default=25, help="Instances per ring count.")
    parser.add_argument("--seed", type=int, default=20260906, help="Base random seed.")
    parser.add_argument(
        "--min-optimal-moves",
        type=int,
        default=None,
        help="Reject instances whose optimal path is shorter than this. Defaults to the ring count.",
    )
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for n in range(args.min_rings, args.max_rings + 1):
        min_optimal = args.min_optimal_moves if args.min_optimal_moves is not None else n
        for instance_index in range(args.instances):
            # Deterministic, reproducible: one seed per (n, instance_index) pair.
            rng = random.Random(f"{args.seed}:{n}:{instance_index}")
            initial, goal, optimal = generate_instance(rng, n, min_optimal)
            task_id = f"hanoi_flat_{n}_{instance_index:02d}"
            payload = build_task_json(task_id, n, initial, goal, optimal)
            path = output_dir / f"{task_id}.json"
            with path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            total += 1
        print(f"n={n}: generated {args.instances} instances")

    print(f"\nTotal flat tasks generated: {total} -> {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
