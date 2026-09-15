"""Legal Flat Hanoi state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional, Sequence, Tuple

from .model import Move, State, validate_move_shape, validate_state


@dataclass
class IllegalMove(ValueError):
    code: str
    message: str
    move: Optional[Move] = None

    def __str__(self) -> str:
        return self.message


def top_disks(state: State) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    canonical = validate_state(state)
    tops = [None, None, None]  # type: ignore[var-annotated]
    for disk, peg in enumerate(canonical, start=1):
        if tops[peg] is None:
            tops[peg] = disk
    return tops[0], tops[1], tops[2]


def apply_move(state: State, move: Sequence[int]) -> State:
    """Apply one asserted move, rejecting every rule violation."""

    canonical = validate_state(state)
    try:
        disk, source, destination = validate_move_shape(move)
    except ValueError as exc:
        raise IllegalMove("malformed_move", str(exc)) from exc
    checked = (disk, source, destination)
    if disk < 1 or disk > len(canonical):
        raise IllegalMove("disk_out_of_range", "disk id is outside 1..n", checked)
    if source not in (0, 1, 2) or destination not in (0, 1, 2):
        raise IllegalMove("peg_out_of_range", "peg id is outside 0..2", checked)
    if source == destination:
        raise IllegalMove("same_peg", "source and destination pegs are identical", checked)
    if canonical[disk - 1] != source:
        raise IllegalMove("wrong_source", "asserted disk is not on the source peg", checked)
    tops = top_disks(canonical)
    if tops[source] != disk:
        raise IllegalMove("not_top_disk", "asserted disk is not the source peg's top disk", checked)
    target_top = tops[destination]
    if target_top is not None and disk > target_top:
        raise IllegalMove("larger_on_smaller", "cannot place a larger disk on a smaller disk", checked)
    updated = list(canonical)
    updated[disk - 1] = destination
    return tuple(updated)


def neighbors(state: State) -> Iterator[Tuple[Move, State]]:
    """Yield legal neighbors in stable source/destination order."""

    canonical = validate_state(state)
    tops = top_disks(canonical)
    for source in range(3):
        disk = tops[source]
        if disk is None:
            continue
        for destination in range(3):
            if source == destination:
                continue
            target_top = tops[destination]
            if target_top is None or disk < target_top:
                move = (disk, source, destination)
                yield move, apply_move(canonical, move)


def replay(state: State, moves: Sequence[Sequence[int]]) -> State:
    current = validate_state(state)
    for move in moves:
        current = apply_move(current, move)
    return current

