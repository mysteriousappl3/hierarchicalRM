"""Level-generic hierarchy analysis for the dynamic (n-level) planner.

scoring.py assumes exactly two composed levels: all_h2_calls_known accepts a
callee only if it appears in h1_mappings, and count_hierarchy_calls returns a
fixed (h1, h2) pair. Both reject or mis-count a hierarchy deeper than H2 even
though parse_mappings and expand_calls already handle arbitrary depth.

This module replaces those two assumptions with inferred levels. Nothing here
changes scoring.py, so the existing hierarchy mode is unaffected.

Levels are never declared by the model. They are derived from the call graph:

    level(primitive) = 0
    level(f)         = 1 + max(level(callee) for callee in body(f))

so a hierarchy is valid when every callee resolves to a primitive or another
known mapping and the graph is acyclic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple

from scoring import (
    FunctionCall,
    FunctionMapping,
    PRIMITIVES,
    expand_calls,
    extract_between_flags,
)


# scoring.expand_calls defaults to max_depth=20, which caps an unrolled Hanoi
# tower at 19 levels. Depth is the point of this mode, so the ceiling is raised
# and stated explicitly rather than inherited.
DEFAULT_MAX_DEPTH = 64

# The H0 sequence a level-1 function must expand to for one Hanoi move. Passed
# as a parameter so another domain can supply its own primitive pattern.
H0_MOVE_PATTERN: Tuple[str, ...] = (
    "MoveCoroutine",
    "GrabCoroutine",
    "MoveCoroutine",
    "DropCoroutine",
)


# Canonical owners in the router verdict. "both" takes the same correction path
# as "decision", because a changed plan invalidates the hierarchy below it.
OWNER_DECISION = "decision"
OWNER_HIERARCHY = "hierarchy"
OWNER_BOTH = "both"

SUBTASK_PATTERN = re.compile(
    r"```start_subtask_(\d+)\s*(.*?)\s*```end_subtask_\1",
    re.DOTALL,
)
SUBTASK_GOALSTATE_PATTERN = re.compile(
    r"```start_subtask_goalstate_(\d+)\s*(.*?)\s*```end_subtask_goalstate_\1",
    re.DOTALL,
)


@dataclass
class HierarchyAnalysis:
    levels: Dict[str, int]
    max_level: int
    mapping_count_by_level: Dict[int, int]
    base_pattern_valid: bool
    errors: List[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors and self.max_level >= 1


def infer_levels(
    mappings: Dict[str, FunctionMapping],
    primitives: Iterable[str] = PRIMITIVES,
) -> Tuple[Dict[str, int], List[str]]:
    """Assign each mapping a level from its call graph.

    Returns (levels, errors). Errors cover cycles, callees that resolve to
    neither a primitive nor a known mapping, and empty bodies.
    """
    primitive_names = set(primitives)
    levels: Dict[str, int] = {}
    errors: List[str] = []
    state: Dict[str, str] = {}

    def record(message: str) -> None:
        if message not in errors:
            errors.append(message)

    def level_of(name: str) -> int:
        if name in primitive_names:
            return 0
        if state.get(name) == "done":
            return levels[name]
        if state.get(name) == "visiting":
            record(f"cycle detected through {name}")
            return 0

        mapping = mappings.get(name)
        if mapping is None:
            record(f"unresolvable callee: {name}")
            return 0
        if not mapping.calls:
            record(f"mapping {name} has an empty body")
            state[name] = "done"
            levels[name] = 0
            return 0

        state[name] = "visiting"
        level = 1 + max(level_of(child.name) for child in mapping.calls)
        state[name] = "done"
        levels[name] = level
        return level

    # Sorted for deterministic error ordering across runs.
    for name in sorted(mappings):
        level_of(name)
    return levels, errors


def has_valid_base_mapping(
    mappings: Dict[str, FunctionMapping],
    levels: Dict[str, int],
    pattern: Sequence[str] = H0_MOVE_PATTERN,
) -> bool:
    """Generalizes has_valid_h1_move_mapping to inferred level 1."""
    expected = tuple(pattern)
    for name, mapping in mappings.items():
        if levels.get(name) != 1:
            continue
        if tuple(call.name for call in mapping.calls) == expected:
            return True
    return False


def analyze_hierarchy(
    mappings: Dict[str, FunctionMapping],
    primitives: Iterable[str] = PRIMITIVES,
    base_pattern: Sequence[str] = H0_MOVE_PATTERN,
) -> HierarchyAnalysis:
    levels, errors = infer_levels(mappings, primitives)
    counts: Dict[int, int] = {}
    for level in levels.values():
        counts[level] = counts.get(level, 0) + 1
    return HierarchyAnalysis(
        levels=levels,
        max_level=max(levels.values(), default=0),
        mapping_count_by_level=counts,
        base_pattern_valid=has_valid_base_mapping(mappings, levels, base_pattern),
        errors=errors,
    )


def count_calls_by_level(
    calls: Sequence[FunctionCall],
    mappings: Dict[str, FunctionMapping],
    levels: Dict[str, int],
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Dict[int, int]:
    """Per-level call histogram, generalizing count_hierarchy_calls.

    Matches the traversal in scoring.count_hierarchy_calls: a call is counted at
    its own level, and only composed levels (2 and above) are descended into, so
    level-1 bodies are not expanded into their primitives. Argument substitution
    is skipped because counting depends on names alone.
    """
    histogram: Dict[int, int] = {}

    def count_one(call: FunctionCall, depth: int) -> None:
        if depth > max_depth:
            return
        level = levels.get(call.name)
        if level is None or level < 1:
            return
        histogram[level] = histogram.get(level, 0) + 1
        if level < 2:
            return
        mapping = mappings.get(call.name)
        if mapping is None:
            return
        for child in mapping.calls:
            count_one(child, depth + 1)

    for call in calls:
        count_one(call, 0)
    return histogram


def expand_hierarchy(
    calls: Sequence[FunctionCall],
    mappings: Dict[str, FunctionMapping],
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Tuple[List[FunctionCall], List[str]]:
    """scoring.expand_calls at the deeper default this mode needs."""
    return expand_calls(list(calls), mappings, max_depth=max_depth)


def legacy_call_counts(histogram: Dict[int, int]) -> Tuple[int, int]:
    """Map a level histogram back onto the (h1_call_count, h2_call_count) pair.

    For a two-level hierarchy this is exactly what count_hierarchy_calls
    returns. For deeper hierarchies every composed level is folded into the h2
    slot so existing figures keep working; level_call_counts carries the detail.
    """
    base = histogram.get(1, 0)
    composed = sum(count for level, count in histogram.items() if level >= 2)
    return base, composed


def legacy_validity(analysis: HierarchyAnalysis) -> Tuple[bool, bool]:
    """Map an analysis back onto the (h1_valid, h2_valid) pair."""
    return analysis.base_pattern_valid, analysis.valid and analysis.max_level >= 2


def parse_plan_subtasks(plan_output: str) -> Tuple[List[Dict[str, object]], List[str]]:
    """Read the plan-only DecisionBot output: descriptions plus goal states.

    The natural-language description is what the OuterBot needs as its subtask
    requirement, which the two-level pipeline had to synthesise from the call
    list because the planner never produced one.
    """
    errors: List[str] = []
    descriptions = {int(index): body for index, body in SUBTASK_PATTERN.findall(plan_output)}
    goal_states = {
        int(index): body for index, body in SUBTASK_GOALSTATE_PATTERN.findall(plan_output)
    }

    if not descriptions:
        errors.append("No start_subtask_{n}/end_subtask_{n} block found")
        return [], errors

    subtasks: List[Dict[str, object]] = []
    for index in sorted(descriptions):
        if index not in goal_states:
            errors.append(f"Subtask {index}: no goal state block")
        subtasks.append(
            {
                "subtask_index": index,
                "description": descriptions[index],
                "goal_state_text": goal_states.get(index, ""),
            }
        )

    expected = list(range(1, len(subtasks) + 1))
    if sorted(descriptions) != expected:
        errors.append(
            f"Subtask numbering is not 1..{len(subtasks)} without gaps: {sorted(descriptions)}"
        )
    if any(index not in descriptions for index in goal_states):
        orphans = sorted(index for index in goal_states if index not in descriptions)
        errors.append(f"Goal state blocks without a matching subtask: {orphans}")
    return subtasks, errors


def normalize_owner(value: str) -> str:
    """Map a free-text OWNER field onto a canonical owner."""
    text = value.strip().strip("`").strip('"').strip("'").lower()
    text = text.replace("_", " ").replace("-", " ")
    has_decision = "decision" in text or "planner bot" in text
    has_hierarchy = "hierarchy" in text
    if text == "both" or (has_decision and has_hierarchy):
        return OWNER_BOTH
    if has_hierarchy:
        return OWNER_HIERARCHY
    if has_decision:
        return OWNER_DECISION
    return ""


def parse_router_verdict(output: str) -> Tuple[bool, str, str]:
    """Read the three-field InnerBot router verdict.

    Returns (no_mistake, owner, reason). RESULT keeps the YES/NO polarity of the
    existing InnerBot so the router is a strict extension of that contract.
    An unreadable verdict is treated as a mistake owned by "both", which routes
    to a full re-plan: the conservative choice when attribution is unknown.
    """
    block = extract_between_flags(output, "```start_result", "```end_result") or output
    result = _labeled_value(block, "RESULT")
    owner = _labeled_value(block, "OWNER")
    reason = _labeled_value(block, "REASON") or "N/A"

    normalized = result.strip().strip("`").strip('"').upper()
    if normalized.startswith("YES"):
        return True, "NA", reason
    if normalized.startswith("NO"):
        canonical = normalize_owner(owner)
        if not canonical:
            return False, OWNER_BOTH, f"router gave no usable OWNER field; {reason}"
        return False, canonical, reason
    return False, OWNER_BOTH, f"could not parse router RESULT from verifier output: {_truncate(output)}"


def _labeled_value(text: str, label: str) -> str:
    pattern = rf"^\s*{label}\s*:\s*(.+?)\s*$"
    for line in text.splitlines():
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return ""


def _truncate(value: str, limit: int = 240) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def hierarchy_metrics(
    analysis: HierarchyAnalysis,
    histogram: Dict[int, int],
) -> Dict[str, object]:
    """Metrics payload: legacy fields plus the level-generic superset."""
    h1_call_count, h2_call_count = legacy_call_counts(histogram)
    h1_valid, h2_valid = legacy_validity(analysis)
    return {
        "h1_valid": h1_valid,
        "h2_valid": h2_valid,
        "h1_call_count": h1_call_count,
        "h2_call_count": h2_call_count,
        "max_hierarchy_level": analysis.max_level,
        "level_call_counts": {str(level): histogram[level] for level in sorted(histogram)},
        "mapping_count_by_level": {
            str(level): analysis.mapping_count_by_level[level]
            for level in sorted(analysis.mapping_count_by_level)
        },
        "hierarchy_errors": list(analysis.errors),
    }
