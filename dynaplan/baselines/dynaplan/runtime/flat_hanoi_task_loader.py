"""Task loader for flat-to-flat Tower of Hanoi tasks.

Mirrors task_loader.HanoiTask closely enough that the existing, unmodified
scoring.py functions (apply_hanoi_move, simulate_hanoi, extract_moves_from_h0,
count_hierarchy_calls, etc.) work against FlatHanoiTask with no changes —
those functions only ever touch task.pegs, task.ring_sizes, task.initial,
task.goal, and task.id.

Unlike task_loader.HanoiTask, source_peg/auxiliary_peg/target_peg are
Optional and unset here: a flat task has no privileged source or auxiliary
peg, and leaving these set would let a "source_peg"/"auxiliary_peg" tower
framing leak back into prompts built for flat tasks.

optimal_move_count is computed once at generation time (see
generate_flat_hanoi_tasks.py) via hanoi_solver.shortest_hanoi_move_count and
baked into the task JSON, so load_task never needs to repeat the BFS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from task_loader import Ring, validate_task as _validate_tower_shaped_task

TASK_DIR = Path(__file__).resolve().parent / "tasks" / "flat"


@dataclass(frozen=True)
class FlatHanoiTask:
    id: str
    name: str
    pegs: List[str]
    rings: List[Ring]
    initial: Dict[str, List[str]]
    goal: Dict[str, List[str]]
    instruction: str
    optimal_move_count: Optional[int]
    source_peg: Optional[str] = None
    auxiliary_peg: Optional[str] = None
    target_peg: Optional[str] = None

    @property
    def ring_sizes(self) -> Dict[str, int]:
        return {ring.name: ring.size for ring in self.rings}

    @property
    def is_flat(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class PublicFlatHanoiTask:
    """Model-facing Flat-Hanoi instance with no evaluator-only fields.

    In particular, the shortest-path length and the legacy privileged-peg
    aliases are absent rather than merely set to ``None``.  Baseline code
    therefore cannot accidentally inspect them through the task object.
    """

    id: str
    name: str
    pegs: List[str]
    rings: List[Ring]
    initial: Dict[str, List[str]]
    goal: Dict[str, List[str]]
    instruction: str

    @property
    def ring_sizes(self) -> Dict[str, int]:
        return {ring.name: ring.size for ring in self.rings}

    @property
    def is_flat(self) -> bool:
        return True


def public_task_view(task: FlatHanoiTask) -> PublicFlatHanoiTask:
    """Return the complete public instance and omit all oracle metadata."""

    view = PublicFlatHanoiTask(
        id=task.id,
        name=task.name,
        pegs=list(task.pegs),
        rings=list(task.rings),
        initial={peg: list(stack) for peg, stack in task.initial.items()},
        goal={peg: list(stack) for peg, stack in task.goal.items()},
        instruction=task.instruction,
    )
    forbidden = (
        "optimal_move_count",
        "source_peg",
        "auxiliary_peg",
        "target_peg",
    )
    assert all(not hasattr(view, field) for field in forbidden)
    return view


def available_tasks() -> List[str]:
    return sorted(path.stem for path in TASK_DIR.glob("hanoi_flat_*.json"))


def load_task(task_id: str) -> FlatHanoiTask:
    path = TASK_DIR / f"{task_id}.json"
    if not path.exists():
        valid = ", ".join(available_tasks())
        raise ValueError(f"Unknown flat task '{task_id}'. Available tasks: {valid}")

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    task = FlatHanoiTask(
        id=raw["id"],
        name=raw["name"],
        pegs=list(raw["pegs"]),
        rings=[Ring(**ring) for ring in raw["rings"]],
        initial={peg: list(stack) for peg, stack in raw["initial"].items()},
        goal={peg: list(stack) for peg, stack in raw["goal"].items()},
        instruction=raw["instruction"],
        optimal_move_count=raw.get("optimal_move_count"),
    )
    validate_task(task)
    return task


def validate_task(task: FlatHanoiTask) -> None:
    # validate_task in task_loader.py only reads task.initial, task.goal,
    # task.pegs, task.rings, task.id, and task.ring_sizes -- all present on
    # FlatHanoiTask -- so it is reused as-is rather than duplicated.
    _validate_tower_shaped_task(task)  # type: ignore[arg-type]


__all__ = [
    "FlatHanoiTask",
    "PublicFlatHanoiTask",
    "TASK_DIR",
    "available_tasks",
    "load_task",
    "public_task_view",
    "validate_task",
]
