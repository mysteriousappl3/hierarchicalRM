"""Batch-result aggregation with every attempted instance in the denominator."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List

from .evaluate import Classification


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def summarize(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(records)
    total = len(rows)
    counts = Counter(str(row.get("classification", "missing")) for row in rows)
    optimal = counts[Classification.OPTIMAL.value]
    goal_reaching = optimal + counts[Classification.SUBOPTIMAL.value]
    parseable = sum(row.get("parseable") is True for row in rows)
    legal = sum(row.get("legal") is True for row in rows)
    by_n: Dict[str, Dict[str, Any]] = {}
    groups: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if "n" in row:
            groups[int(row["n"])].append(row)
    for n, group in sorted(groups.items()):
        group_counts = Counter(str(row.get("classification", "missing")) for row in group)
        group_total = len(group)
        group_optimal = group_counts[Classification.OPTIMAL.value]
        group_goal = group_optimal + group_counts[Classification.SUBOPTIMAL.value]
        group_parseable = sum(row.get("parseable") is True for row in group)
        group_legal = sum(row.get("legal") is True for row in group)
        by_n[str(n)] = {
            "total": group_total,
            "counts": dict(sorted(group_counts.items())),
            "optimal_accuracy": _rate(group_optimal, group_total),
            "goal_reaching_rate": _rate(group_goal, group_total),
            "parseable_rate": _rate(group_parseable, group_total),
            "legal_response_rate": _rate(group_legal, group_total),
        }
    numeric_usage = {}
    for key in ("input_tokens", "output_tokens", "reasoning_tokens", "total_tokens", "cost"):
        values = [row[key] for row in rows
                  if isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool)]
        if values:
            numeric_usage[key] = sum(values)
    return {
        "total": total,
        "counts": dict(sorted(counts.items())),
        "optimal_accuracy": _rate(optimal, total),
        "goal_reaching_rate": _rate(goal_reaching, total),
        "parseable_rate": _rate(parseable, total),
        "legal_response_rate": _rate(legal, total),
        "by_n": by_n,
        "usage_totals": numeric_usage,
    }
