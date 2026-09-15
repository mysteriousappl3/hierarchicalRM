from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


TASK_DIR = Path(__file__).resolve().parent / "tasks"


@dataclass(frozen=True)
class Ring:
    name: str
    size: int
    label: str


@dataclass(frozen=True)
class HanoiTask:
    id: str
    name: str
    pegs: List[str]
    source_peg: str
    auxiliary_peg: str
    target_peg: str
    rings: List[Ring]
    initial: Dict[str, List[str]]
    goal: Dict[str, List[str]]
    instruction: str

    @property
    def ring_sizes(self) -> Dict[str, int]:
        return {ring.name: ring.size for ring in self.rings}

    @property
    def optimal_move_count(self) -> int:
        return (2 ** len(self.rings)) - 1


def available_tasks() -> List[str]:
    return sorted((path.stem for path in TASK_DIR.glob("hanoi_*.json")), key=_task_sort_key)


def _task_sort_key(task_id: str) -> int:
    return int(task_id.rsplit("_", 1)[1])


def load_task(task_id: str) -> HanoiTask:
    path = TASK_DIR / f"{task_id}.json"
    if not path.exists():
        valid = ", ".join(available_tasks())
        raise ValueError(f"Unknown task '{task_id}'. Available tasks: {valid}")

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    task = HanoiTask(
        id=raw["id"],
        name=raw["name"],
        pegs=list(raw["pegs"]),
        source_peg=raw["source_peg"],
        auxiliary_peg=raw["auxiliary_peg"],
        target_peg=raw["target_peg"],
        rings=[Ring(**ring) for ring in raw["rings"]],
        initial={peg: list(stack) for peg, stack in raw["initial"].items()},
        goal={peg: list(stack) for peg, stack in raw["goal"].items()},
        instruction=raw["instruction"],
    )
    validate_task(task)
    return task


def validate_task(task: HanoiTask) -> None:
    if set(task.initial) != set(task.pegs):
        raise ValueError(f"{task.id}: initial pegs do not match pegs list")
    if set(task.goal) != set(task.pegs):
        raise ValueError(f"{task.id}: goal pegs do not match pegs list")

    ring_names = {ring.name for ring in task.rings}
    initial_rings = [ring for stack in task.initial.values() for ring in stack]
    goal_rings = [ring for stack in task.goal.values() for ring in stack]
    if set(initial_rings) != ring_names or len(initial_rings) != len(ring_names):
        raise ValueError(f"{task.id}: initial state must contain every ring exactly once")
    if set(goal_rings) != ring_names or len(goal_rings) != len(ring_names):
        raise ValueError(f"{task.id}: goal state must contain every ring exactly once")

    for stack_name, stack in task.initial.items():
        validate_stack_order(task, stack_name, stack)
    for stack_name, stack in task.goal.items():
        validate_stack_order(task, stack_name, stack)


def validate_stack_order(task: HanoiTask, stack_name: str, stack: List[str]) -> None:
    sizes = task.ring_sizes
    # Stacks are bottom-to-top. Sizes should strictly decrease as the stack rises.
    for lower, upper in zip(stack, stack[1:]):
        if sizes[lower] < sizes[upper]:
            raise ValueError(
                f"{task.id}: invalid stack on {stack_name}: "
                f"{upper} is larger than {lower}"
            )
