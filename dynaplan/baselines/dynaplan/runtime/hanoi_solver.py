"""Shared BFS optimum solver for Tower of Hanoi, tower-to-tower or flat.

Standalone: takes plain initial/goal peg->stack dicts and a ring-size map,
with no dependency on task_loader.HanoiTask. This keeps the existing
tower-to-tower pipeline (task_loader.py, scoring.py) untouched while letting
both the tower and flat task loaders validate optima against the same code.

Adapted from shortest_move_count in blocks_world_task.py, with the added
Hanoi-specific legality filter: a ring can never be placed on a smaller ring.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Tuple


def shortest_hanoi_move_count(
    initial: Dict[str, List[str]],
    goal: Dict[str, List[str]],
    ring_sizes: Dict[str, int],
    max_ring_count: int = 10,
) -> Optional[int]:
    """Exact BFS shortest-path move count from initial to goal.

    Returns None if the ring count exceeds max_ring_count (state space is
    3^n; 10 rings is ~59k states, 12 is ~531k and slow to repeat per task) or
    if goal is unreachable, which should not happen for validly generated
    Hanoi tasks but must not raise.
    """
    if len(ring_sizes) > max_ring_count:
        return None

    pegs = sorted(initial)
    start = _state_key(initial, pegs)
    end = _state_key(goal, pegs)
    if start == end:
        return 0

    queue: deque[Tuple[Tuple[Tuple[str, ...], ...], int]] = deque([(start, 0)])
    seen = {start}
    while queue:
        state, depth = queue.popleft()
        for source_index, source_stack in enumerate(state):
            if not source_stack:
                continue
            ring = source_stack[-1]
            for target_index in range(len(state)):
                if source_index == target_index:
                    continue
                target_stack = state[target_index]
                if target_stack and ring_sizes[ring] > ring_sizes[target_stack[-1]]:
                    continue
                next_state = list(state)
                next_state[source_index] = source_stack[:-1]
                next_state[target_index] = target_stack + (ring,)
                candidate = tuple(next_state)
                if candidate == end:
                    return depth + 1
                if candidate not in seen:
                    seen.add(candidate)
                    queue.append((candidate, depth + 1))
    return None


def shortest_hanoi_path(
    initial: Dict[str, List[str]],
    goal: Dict[str, List[str]],
    ring_sizes: Dict[str, int],
    max_ring_count: int = 10,
) -> Optional[List[Tuple[str, str]]]:
    """Exact BFS shortest move sequence (source_peg, target_peg) from initial to goal.

    Used by the flat-aware mock provider, which needs an actual legal plan
    rather than just its length.
    """
    if len(ring_sizes) > max_ring_count:
        return None

    pegs = sorted(initial)
    start = _state_key(initial, pegs)
    end = _state_key(goal, pegs)
    if start == end:
        return []

    queue: deque[Tuple[Tuple[Tuple[str, ...], ...], int]] = deque([(start, 0)])
    seen = {start}
    parents: Dict[
        Tuple[Tuple[str, ...], ...],
        Tuple[Tuple[Tuple[str, ...], ...], str, str],
    ] = {}
    while queue:
        state, depth = queue.popleft()
        for source_index, source_stack in enumerate(state):
            if not source_stack:
                continue
            ring = source_stack[-1]
            for target_index in range(len(state)):
                if source_index == target_index:
                    continue
                target_stack = state[target_index]
                if target_stack and ring_sizes[ring] > ring_sizes[target_stack[-1]]:
                    continue
                next_state = list(state)
                next_state[source_index] = source_stack[:-1]
                next_state[target_index] = target_stack + (ring,)
                candidate = tuple(next_state)
                if candidate in seen:
                    continue
                seen.add(candidate)
                parents[candidate] = (state, pegs[source_index], pegs[target_index])
                if candidate == end:
                    return _reconstruct_path(parents, end)
                queue.append((candidate, depth + 1))
    return None


def _reconstruct_path(
    parents: Dict[
        Tuple[Tuple[str, ...], ...],
        Tuple[Tuple[Tuple[str, ...], ...], str, str],
    ],
    end: Tuple[Tuple[str, ...], ...],
) -> List[Tuple[str, str]]:
    path: List[Tuple[str, str]] = []
    state = end
    while state in parents:
        prev_state, source, target = parents[state]
        path.append((source, target))
        state = prev_state
    path.reverse()
    return path


def _state_key(
    state: Dict[str, List[str]], pegs: List[str]
) -> Tuple[Tuple[str, ...], ...]:
    return tuple(tuple(state[peg]) for peg in pegs)
