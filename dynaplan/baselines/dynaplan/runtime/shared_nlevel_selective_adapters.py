"""Adapter refinements required by the selective-repair N-level pipeline.

LexiCon already provides a standalone deterministic H1 validator.  The
original Flat-Hanoi adapter predates validated caching and therefore validates
H1 only as part of the combined hierarchy compiler.  This module supplies the
missing standalone check without changing the v2 adapter used by registered
experiments.
"""

from __future__ import annotations

from typing import Any, Dict, List

from dynamic_scoring import H0_MOVE_PATTERN, analyze_hierarchy
from scoring import FunctionMapping, parse_mappings
from shared_nlevel_flat_hanoi import FlatHanoiNLevelAdapter
from shared_nlevel_pipeline import ArtifactCheck


class SelectiveFlatHanoiNLevelAdapter(FlatHanoiNLevelAdapter):
    """Flat-Hanoi adapter with a deterministic, standalone H1 contract."""

    # The inherited validator intentionally accepts every descriptor and
    # delegates semantic checking to InnerBot.  The selective loop therefore
    # repairs StateDescriptor, not InnerBot, when this adapter's InnerBot says
    # NO.  LexiCon's exact deterministic descriptor validator is authoritative.
    state_descriptor_validation_authoritative = False

    def validate_h1(self, task: Any, output: str) -> ArtifactCheck:
        del task
        mappings, parse_errors = parse_mappings(output)
        analysis = analyze_hierarchy(mappings)
        errors: List[str] = [f"H1: {error}" for error in parse_errors]
        errors.extend(f"H1: {error}" for error in analysis.errors)

        # The Flat prompt declares one exact interface.  Checking only call
        # names is insufficient: swapped source/target arguments would pass
        # call-graph analysis, be cached, and make every later projection fail.
        if set(mappings) != {"MoveSingleRing"}:
            errors.append("H1: must define exactly MoveSingleRing")
        mapping = mappings.get("MoveSingleRing")
        if mapping is not None:
            if mapping.params != ["source_peg", "target_peg"]:
                errors.append(
                    "H1: MoveSingleRing parameters must be exactly "
                    "(source_peg, target_peg)"
                )
            expected_calls = [
                ("MoveCoroutine", ["source_peg"]),
                ("GrabCoroutine", []),
                ("MoveCoroutine", ["target_peg"]),
                ("DropCoroutine", []),
            ]
            actual_calls = [(call.name, call.args) for call in mapping.calls]
            if actual_calls != expected_calls:
                errors.append(
                    "H1: MoveSingleRing body must be exactly "
                    "MoveCoroutine(source_peg), GrabCoroutine(), "
                    "MoveCoroutine(target_peg), DropCoroutine()"
                )
        if mappings and not analysis.base_pattern_valid:
            errors.append(
                "H1: mapping does not match primitive move pattern "
                f"{list(H0_MOVE_PATTERN)}"
            )

        metadata: Dict[str, object] = {
            "mappings": mappings,
            "levels": dict(analysis.levels),
            "mapping_count_by_level": dict(analysis.mapping_count_by_level),
            "base_pattern_valid": analysis.base_pattern_valid,
        }
        value: Dict[str, FunctionMapping] = mappings
        return ArtifactCheck(
            valid=bool(mappings) and not errors,
            value=value if mappings else None,
            errors=tuple(errors),
            metadata=metadata,
        )

    def canonicalize_h1(
        self, task: Any, output: str, check: ArtifactCheck
    ) -> str:
        """Strip model prose/state references from a validated H1 artifact."""

        del task, output, check
        return """```start_flag
void MoveSingleRing(string source_peg, string target_peg)
{
    MoveCoroutine(source_peg);
    GrabCoroutine();
    MoveCoroutine(target_peg);
    DropCoroutine();
}
```end_flag

```start_mapping
MoveSingleRing(source_peg, target_peg) = [MoveCoroutine(source_peg), GrabCoroutine(), MoveCoroutine(target_peg), DropCoroutine()]
```end_mapping"""


__all__ = ["SelectiveFlatHanoiNLevelAdapter"]
