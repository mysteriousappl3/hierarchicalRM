"""Authoritative paper-compatible scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional, Sequence

from .model import Instance, Move, State, validate_state
from .oracle import shortest_distance
from .parse import ParseError, parse_moves
from .state import IllegalMove, apply_move


class Classification(str, Enum):
    OPTIMAL = "optimal"
    SUBOPTIMAL = "suboptimal"
    INCORRECT = "incorrect"
    ILLEGAL = "illegal"


@dataclass(frozen=True)
class Evaluation:
    classification: Classification
    parseable: bool
    legal: bool
    valid: bool
    goal_reached: bool
    optimal: bool
    submitted_length: Optional[int]
    optimal_distance: int
    legal_prefix_length: int
    final_state: Optional[State]
    first_failure_index: Optional[int] = None
    failure_code: Optional[str] = None
    failure_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["classification"] = self.classification.value
        if self.final_state is not None:
            value["final_state"] = list(self.final_state)
        return value


def evaluate_moves(
    start: State,
    goal: State,
    moves: Sequence[Move],
    optimal_distance: Optional[int] = None,
) -> Evaluation:
    source = validate_state(start)
    target = validate_state(goal, len(source))
    exact_distance = shortest_distance(source, target)
    if optimal_distance is not None and optimal_distance != exact_distance:
        raise ValueError("stored optimal distance disagrees with the exact oracle")
    current = source
    for index, move in enumerate(moves, start=1):
        try:
            current = apply_move(current, move)
        except IllegalMove as exc:
            return Evaluation(
                classification=Classification.ILLEGAL,
                parseable=True,
                legal=False,
                valid=False,
                goal_reached=False,
                optimal=False,
                submitted_length=len(moves),
                optimal_distance=exact_distance,
                legal_prefix_length=index - 1,
                final_state=current,
                first_failure_index=index,
                failure_code=exc.code,
                failure_reason=exc.message,
            )
    reached = current == target
    if not reached:
        classification = Classification.INCORRECT
    elif len(moves) == exact_distance:
        classification = Classification.OPTIMAL
    elif len(moves) > exact_distance:
        classification = Classification.SUBOPTIMAL
    else:
        raise RuntimeError("a goal-reaching plan is shorter than the exact BFS optimum")
    return Evaluation(
        classification=classification,
        parseable=True,
        legal=True,
        valid=True,
        goal_reached=reached,
        optimal=classification == Classification.OPTIMAL,
        submitted_length=len(moves),
        optimal_distance=exact_distance,
        legal_prefix_length=len(moves),
        final_state=current,
    )


def evaluate_response(instance: Instance, response: str) -> Evaluation:
    try:
        moves = parse_moves(response)
    except ParseError as exc:
        return Evaluation(
            classification=Classification.ILLEGAL,
            parseable=False,
            legal=False,
            valid=False,
            goal_reached=False,
            optimal=False,
            submitted_length=None,
            optimal_distance=instance.optimal_distance,
            legal_prefix_length=0,
            final_state=instance.start,
            failure_code=exc.code,
            failure_reason=exc.message,
        )
    return evaluate_moves(
        instance.start,
        instance.goal,
        moves,
        optimal_distance=instance.optimal_distance,
    )
