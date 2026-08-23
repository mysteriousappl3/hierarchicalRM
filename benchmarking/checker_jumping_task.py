from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


PAPER_TASK_SIZES: Tuple[int, ...] = tuple(range(1, 16))


@dataclass(frozen=True)
class CheckerJumpingTask:
    id: str
    checkers_per_color: int
    initial: List[str]
    goal: List[str]
    optimal_move_count: int

    @property
    def total_checkers(self) -> int:
        return self.checkers_per_color * 2

    @property
    def board_length(self) -> int:
        return len(self.initial)


def build_paper_task(checkers_per_color: int) -> CheckerJumpingTask:
    if checkers_per_color < 1:
        raise ValueError("Checker Jumping requires at least one checker per color")
    initial = ["R"] * checkers_per_color + ["_"] + ["B"] * checkers_per_color
    goal = ["B"] * checkers_per_color + ["_"] + ["R"] * checkers_per_color
    return CheckerJumpingTask(
        id=f"checker_jumping_{checkers_per_color}",
        checkers_per_color=checkers_per_color,
        initial=initial,
        goal=goal,
        optimal_move_count=(checkers_per_color + 1) ** 2 - 1,
    )


def load_task(task_id: str) -> CheckerJumpingTask:
    match = re.fullmatch(r"checker_jumping_(\d+)", task_id.strip().lower())
    if not match:
        raise ValueError(
            "Task must be checker_jumping_N, for example checker_jumping_4"
        )
    return build_paper_task(int(match.group(1)))


def available_tasks() -> List[str]:
    return [f"checker_jumping_{size}" for size in PAPER_TASK_SIZES]


def validate_board(board: object, task: CheckerJumpingTask) -> List[str]:
    errors: List[str] = []
    if not isinstance(board, list):
        return ["board must be an array"]
    if len(board) != task.board_length:
        errors.append(
            f"board must contain {task.board_length} positions; got {len(board)}"
        )
    invalid = [value for value in board if value not in {"R", "B", "_"}]
    if invalid:
        errors.append(f"board contains invalid values: {invalid}")
    if board.count("R") != task.checkers_per_color:
        errors.append(
            f"board must contain {task.checkers_per_color} red checkers"
        )
    if board.count("B") != task.checkers_per_color:
        errors.append(
            f"board must contain {task.checkers_per_color} blue checkers"
        )
    if board.count("_") != 1:
        errors.append("board must contain exactly one empty position")
    return errors


__all__ = [
    "CheckerJumpingTask",
    "PAPER_TASK_SIZES",
    "available_tasks",
    "build_paper_task",
    "load_task",
    "validate_board",
]
