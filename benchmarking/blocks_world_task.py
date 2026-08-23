from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from itertools import zip_longest
from typing import Dict, List, Optional, Tuple


PAPER_TASK_SIZES = (2, 4, 6, 8, 10, 12, 16, 20, 24, 30, 36, 40)


@dataclass(frozen=True)
class BlocksWorldTask:
    id: str
    block_count: int
    initial: Dict[str, List[str]]
    goal: Dict[str, List[str]]
    stack_ids: Tuple[str, ...] = ("0", "1", "2")
    optimal_move_count: Optional[int] = None


def block_label(index: int) -> str:
    """Excel-style labels keep the paper's A, B, ... convention past Z."""
    value = index + 1
    chars: List[str] = []
    while value:
        value, remainder = divmod(value - 1, 26)
        chars.append(chr(ord("A") + remainder))
    return "".join(reversed(chars))


def build_paper_task(block_count: int) -> BlocksWorldTask:
    if block_count < 2:
        raise ValueError("Blocks World requires at least two blocks")
    labels = [block_label(index) for index in range(block_count)]
    split = (block_count + 1) // 2
    first = labels[:split]
    second = labels[split:]

    goal_stack: List[str] = []
    for right, left in zip_longest(reversed(second), reversed(first)):
        if right is not None:
            goal_stack.append(right)
        if left is not None:
            goal_stack.append(left)

    initial = {"0": first, "1": second, "2": []}
    goal = {"0": goal_stack, "1": [], "2": []}
    provisional = BlocksWorldTask(
        id=f"blocks_world_{block_count}",
        block_count=block_count,
        initial=initial,
        goal=goal,
    )
    optimal = shortest_move_count(provisional) if block_count <= 8 else None
    return BlocksWorldTask(
        id=provisional.id,
        block_count=block_count,
        initial=initial,
        goal=goal,
        optimal_move_count=optimal,
    )


def load_task(task_id: str) -> BlocksWorldTask:
    match = re.fullmatch(r"blocks_world_(\d+)", task_id.strip().lower())
    if not match:
        raise ValueError("Task must be blocks_world_N, for example blocks_world_4")
    return build_paper_task(int(match.group(1)))


def available_tasks() -> List[str]:
    return [f"blocks_world_{size}" for size in PAPER_TASK_SIZES]


def shortest_move_count(task: BlocksWorldTask) -> Optional[int]:
    """Exact BFS for small instances; large paper instances deliberately omit it."""
    start = state_key(task.initial, task.stack_ids)
    goal = state_key(task.goal, task.stack_ids)
    if start == goal:
        return 0
    queue = deque([(start, 0)])
    seen = {start}
    while queue:
        state, depth = queue.popleft()
        for source_index, source in enumerate(state):
            if not source:
                continue
            block = source[-1]
            for target_index in range(len(state)):
                if source_index == target_index:
                    continue
                next_stacks = [list(stack) for stack in state]
                next_stacks[source_index].pop()
                next_stacks[target_index].append(block)
                candidate = tuple(tuple(stack) for stack in next_stacks)
                if candidate == goal:
                    return depth + 1
                if candidate not in seen:
                    seen.add(candidate)
                    queue.append((candidate, depth + 1))
    return None


def state_key(
    state: Dict[str, List[str]], stack_ids: Tuple[str, ...]
) -> Tuple[Tuple[str, ...], ...]:
    return tuple(tuple(state[stack]) for stack in stack_ids)
