"""Optional-optimum-aware wrappers around scoring.py for flat Hanoi tasks.

scoring.py's score_direct_output and score_from_execution compute
`optimal = solved and len(moves) == task.optimal_move_count`. If
optimal_move_count is None (BFS could not compute an optimum -- see
hanoi_solver.shortest_hanoi_move_count's max_ring_count cap), Python
evaluates `len(moves) == None` as False rather than raising, so `optimal`
would silently become False instead of the correct "unknown" (None).

flat_hanoi_task_loader.FlatHanoiTask.optimal_move_count is always populated
for the generated task grid (n <= 10, well within the BFS cap), so this is a
latent-but-currently-unreachable case for generated tasks. It is guarded here
rather than left to (accidentally) never trigger, since scoring.py itself is
not edited -- this wrapper is the one place that correction belongs.
"""

from __future__ import annotations

from typing import Optional

from scoring import ScoreResult, score_direct_output as _score_direct_output
from scoring import score_from_execution as _score_from_execution


def _correct_optimal(score: ScoreResult, optimal_move_count: Optional[int]) -> ScoreResult:
    if optimal_move_count is None:
        score.optimal = None  # type: ignore[assignment]
    return score


def score_direct_output(task, direct_output: str) -> ScoreResult:
    score = _score_direct_output(task, direct_output)
    return _correct_optimal(score, task.optimal_move_count)


def score_from_execution(task, **kwargs) -> ScoreResult:
    score = _score_from_execution(task, **kwargs)
    return _correct_optimal(score, task.optimal_move_count)
