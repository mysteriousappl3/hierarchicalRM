"""Canonical data types and validation for Flat Hanoi."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

State = Tuple[int, ...]
Move = Tuple[int, int, int]


def _exact_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_state(state: Iterable[int], n: Optional[int] = None) -> State:
    """Return a canonical state or raise ``ValueError``.

    ``state[disk_id - 1]`` is the peg containing that disk. Disk 1 is the
    smallest. Because disk order on a peg is implicit, every assignment of
    disks to pegs is a legal Hanoi configuration.
    """

    try:
        canonical = tuple(state)
    except TypeError as exc:
        raise ValueError("state must be an iterable of peg integers") from exc
    if n is not None and len(canonical) != n:
        raise ValueError("state length does not match n")
    if len(canonical) < 1:
        raise ValueError("a state must contain at least one disk")
    for peg in canonical:
        if not _exact_int(peg) or peg not in (0, 1, 2):
            raise ValueError("each state entry must be an integer peg in {0,1,2}")
    return canonical


def validate_move_shape(move: Iterable[int]) -> Move:
    try:
        values = tuple(move)
    except TypeError as exc:
        raise ValueError("move must be an iterable") from exc
    if len(values) != 3:
        raise ValueError("move must contain exactly [disk, source, destination]")
    if any(not _exact_int(value) for value in values):
        raise ValueError("move fields must be integers (booleans are not accepted)")
    return values[0], values[1], values[2]


def state_to_index(state: State) -> int:
    """Encode a state as a base-3 integer, smallest disk first."""

    canonical = validate_state(state)
    result = 0
    multiplier = 1
    for peg in canonical:
        result += peg * multiplier
        multiplier *= 3
    return result


def index_to_state(index: int, n: int) -> State:
    if not _exact_int(index) or not _exact_int(n) or n < 1:
        raise ValueError("index and positive n must be integers")
    limit = 3 ** n
    if index < 0 or index >= limit:
        raise ValueError("state index out of range")
    pegs = []
    remaining = index
    for _ in range(n):
        pegs.append(remaining % 3)
        remaining //= 3
    return tuple(pegs)


def peg_stacks(state: State) -> Tuple[Tuple[int, ...], ...]:
    """Return three stacks in bottom-to-top display order."""

    canonical = validate_state(state)
    stacks = []
    for peg in range(3):
        stacks.append(tuple(disk for disk in range(len(canonical), 0, -1)
                            if canonical[disk - 1] == peg))
    return tuple(stacks)


def is_strict_flat(state: State) -> bool:
    """Whether a state occupies at least two pegs."""

    return len(set(validate_state(state))) >= 2


@dataclass(frozen=True)
class Instance:
    schema_version: int
    instance_id: str
    n: int
    start: State
    goal: State
    optimal_distance: int
    sampling_profile: str
    generator_seed: int
    split: Optional[str] = None

    def __post_init__(self) -> None:
        if not _exact_int(self.schema_version) or self.schema_version != 1:
            raise ValueError("unsupported schema_version")
        if not self.instance_id or not isinstance(self.instance_id, str):
            raise ValueError("instance_id must be a non-empty string")
        if not _exact_int(self.n) or self.n < 1:
            raise ValueError("n must be a positive integer")
        object.__setattr__(self, "start", validate_state(self.start, self.n))
        object.__setattr__(self, "goal", validate_state(self.goal, self.n))
        if self.start == self.goal:
            raise ValueError("benchmark instances must have distinct endpoints")
        if not _exact_int(self.optimal_distance) or self.optimal_distance < 1:
            raise ValueError("optimal_distance must be a positive integer")
        if not isinstance(self.sampling_profile, str) or not self.sampling_profile:
            raise ValueError("sampling_profile must be a non-empty string")
        if not _exact_int(self.generator_seed):
            raise ValueError("generator_seed must be an integer")
        if self.split not in (None, "train", "validation"):
            raise ValueError("split must be train, validation, or null")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Instance":
        required = {
            "schema_version", "instance_id", "n", "start", "goal",
            "optimal_distance", "sampling_profile", "generator_seed",
        }
        missing = required.difference(value)
        if missing:
            raise ValueError("missing instance fields: " + ", ".join(sorted(missing)))
        return cls(
            schema_version=value["schema_version"],
            instance_id=value["instance_id"],
            n=value["n"],
            start=tuple(value["start"]),
            goal=tuple(value["goal"]),
            optimal_distance=value["optimal_distance"],
            sampling_profile=value["sampling_profile"],
            generator_seed=value["generator_seed"],
            split=value.get("split"),
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "instance_id": self.instance_id,
            "n": self.n,
            "start": list(self.start),
            "goal": list(self.goal),
            "optimal_distance": self.optimal_distance,
            "sampling_profile": self.sampling_profile,
            "generator_seed": self.generator_seed,
        }
        if self.split is not None:
            result["split"] = self.split
        return result
