"""Paper-derived Flat-to-Flat Tower of Hanoi benchmark."""

from .evaluate import Classification, Evaluation, evaluate_response, evaluate_moves
from .model import Instance, Move, State
from .oracle import shortest_distance, shortest_path

__all__ = [
    "Classification",
    "Evaluation",
    "Instance",
    "Move",
    "State",
    "evaluate_moves",
    "evaluate_response",
    "shortest_distance",
    "shortest_path",
]

__version__ = "0.1.0"

