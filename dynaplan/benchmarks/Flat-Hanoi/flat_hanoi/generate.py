"""Deterministic benchmark instance generation."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Dict, Iterable, Iterator, List, Sequence, Tuple

from .model import Instance, State, index_to_state, is_strict_flat
from .oracle import shortest_distance

DEFAULT_SEED = 260807077
GENERATOR_VERSION = "flat-hanoi-paper-derived-v1"

PROFILE_COUNTS: Dict[str, Dict[int, int]] = {
    "paper-baseline-v1": {3: 34, 4: 33, 5: 33},
    "paper-extension-v1": {6: 33, 7: 33},
    "unrestricted-pairs-sensitivity-v1": {3: 34, 4: 33, 5: 33},
    "transformer-n4-v1": {4: 6480},
}


def _digest(seed: int, profile: str, n: int, counter: int) -> int:
    payload = "{}|{}|{}|{}".format(seed, profile, n, counter).encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest(), "big")


def pair_from_index(pair_index: int, n: int) -> Tuple[State, State]:
    state_count = 3 ** n
    total = state_count * (state_count - 1)
    if pair_index < 0 or pair_index >= total:
        raise ValueError("ordered-pair index out of range")
    start_index, goal_rank = divmod(pair_index, state_count - 1)
    goal_index = goal_rank if goal_rank < start_index else goal_rank + 1
    return index_to_state(start_index, n), index_to_state(goal_index, n)


def _sample_pairs(
    n: int,
    count: int,
    seed: int,
    profile: str,
    strict_flat: bool,
) -> List[Tuple[State, State]]:
    state_count = 3 ** n
    total = state_count * (state_count - 1)
    selected = []
    used = set()
    counter = 0
    ceiling = (1 << 256) - ((1 << 256) % total)
    while len(selected) < count:
        value = _digest(seed, profile, n, counter)
        counter += 1
        if value >= ceiling:
            continue
        pair_index = value % total
        if pair_index in used:
            continue
        start, goal = pair_from_index(pair_index, n)
        if strict_flat and (not is_strict_flat(start) or not is_strict_flat(goal)):
            continue
        used.add(pair_index)
        selected.append((start, goal))
    return selected


def _all_pairs(n: int) -> Iterator[Tuple[State, State]]:
    state_count = 3 ** n
    for pair_index in range(state_count * (state_count - 1)):
        yield pair_from_index(pair_index, n)


def _identifier(profile: str, n: int, ordinal: int) -> str:
    return "{}-n{}-{:04d}".format(profile, n, ordinal)


def generate_instances(profile: str, seed: int = DEFAULT_SEED) -> List[Instance]:
    if profile not in PROFILE_COUNTS:
        raise ValueError("unknown generation profile: {}".format(profile))
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    records: List[Instance] = []
    for n, count in sorted(PROFILE_COUNTS[profile].items()):
        if profile == "transformer-n4-v1":
            pairs: Iterable[Tuple[State, State]] = _all_pairs(n)
        else:
            pairs = _sample_pairs(
                n=n,
                count=count,
                seed=seed,
                profile=profile,
                strict_flat=profile in ("paper-baseline-v1", "paper-extension-v1"),
            )
        for ordinal, (start, goal) in enumerate(pairs):
            records.append(Instance(
                schema_version=1,
                instance_id=_identifier(profile, n, ordinal),
                n=n,
                start=start,
                goal=goal,
                optimal_distance=shortest_distance(start, goal),
                sampling_profile=profile,
                generator_seed=seed,
            ))
    if profile == "transformer-n4-v1":
        # Hash-ranking gives an exact, deterministic 80/20 split while retaining
        # every one of the 6,480 ordered nonidentical pairs.
        ranked = sorted(
            records,
            key=lambda item: hashlib.sha256(
                "{}|{}".format(seed, item.instance_id).encode("ascii")
            ).digest(),
        )
        train_ids = {item.instance_id for item in ranked[:5184]}
        records = [replace(item, split="train" if item.instance_id in train_ids
                           else "validation") for item in records]
    return records
