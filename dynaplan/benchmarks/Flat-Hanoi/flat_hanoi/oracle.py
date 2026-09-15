"""Exact breadth-first shortest paths for Flat Hanoi."""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Tuple

from .model import Move, State, validate_state
from .state import neighbors


def shortest_path(start: State, goal: State) -> List[Move]:
    source = validate_state(start)
    target = validate_state(goal, len(source))
    if source == target:
        return []
    queue = deque([source])
    parent: Dict[State, Tuple[Optional[State], Optional[Move]]] = {
        source: (None, None)
    }
    while queue:
        current = queue.popleft()
        for move, following in neighbors(current):
            if following in parent:
                continue
            parent[following] = (current, move)
            if following == target:
                path: List[Move] = []
                cursor = target
                while parent[cursor][0] is not None:
                    previous, edge = parent[cursor]
                    assert previous is not None and edge is not None
                    path.append(edge)
                    cursor = previous
                path.reverse()
                return path
            queue.append(following)
    raise RuntimeError("Hanoi state graph is unexpectedly disconnected")


def shortest_distance(start: State, goal: State) -> int:
    return len(shortest_path(start, goal))

