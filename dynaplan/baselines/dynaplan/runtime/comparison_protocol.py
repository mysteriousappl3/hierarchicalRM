"""Shared model-facing objectives and Flat-Hanoi comparison conventions.

This module defines prompt content that must be byte-identical across the
direct condition and every mechanism-preserving literature port.  Individual
methods may add their own control-flow instructions and, where intrinsic to the
published method, evaluation-disjoint retrieval/search demonstrations.  They
must not replace or weaken this common benchmark-level contract.
"""

from __future__ import annotations


COMPARISON_PROMPT_PROTOCOL_VERSION = "shared-public-semantics-v3"

MINIMUM_ACTION_OBJECTIVE = (
    "Optimization objective: Among all valid plans, minimize the number of "
    "primitive actions in the final submitted plan."
)

COMMON_TEMPORAL_SEMANTICS = """SHARED FINITE-TRACE SEMANTICS
Use state 0 for the initial state and state i for the state after primitive
action i. Ordinary final goals must hold in the last state, not merely once.
All temporal constraints include the initial and final states.
- always(P): P holds in every state.
- sometime(P): P holds in at least one state.
- at-most-once(P): P has at most one contiguous true interval.
- sometime-before(A,B): every A state has a strictly earlier B state. A in
  state 0 fails; no A states satisfies the implication.
- sometime-after(A,B): every A state has B in the same or a later state. A B
  witness before the latest A is insufficient; no A states satisfies the
  implication.
Apply these definitions to the exact formulas and their negations. Facts not
changed by an action persist."""

COMMON_LOGISTICS_SEMANTICS = """SHARED LOGISTICS ACTION SEMANTICS
Loading requires the package and named vehicle at the named location; it
deletes the package's at_ fact and adds in(package,vehicle). Unloading requires
that exact in(package,vehicle) fact and the vehicle at the named location; it
deletes in and adds the package's at_ fact. A package inside one vehicle is not
inside another and cannot be unloaded twice without another load.
Driving or flying requires the vehicle at its stated source and the declared
city or airport restrictions. It replaces the vehicle's source at_ fact with
its destination at_ fact. Vehicle movement does not create an at_ fact for a
package inside it. Use declared object types and exact action arguments."""

COMMON_BLOCKSWORLD_SEMANTICS = """SHARED BLOCKSWORLD ACTION SEMANTICS
Facts not changed by an action persist; only listed arguments are affected.
- pickup(x): requires ontable(x), clear(x), handempty; adds holding(x); deletes
  ontable(x), clear(x), handempty.
- putdown(x): requires holding(x); adds ontable(x), clear(x), handempty;
  deletes holding(x).
- unstack(x,y): requires on(x,y), clear(x), handempty; adds holding(x),
  clear(y); deletes on(x,y), clear(x), handempty.
- stack(x,y): requires holding(x), clear(y); adds on(x,y), clear(x),
  handempty; deletes holding(x), clear(y).
A held block is not clear. Conversely, not clear(x) does not prove that another
block is above x because x may be held. Ending while holding a block is allowed
when the actual goals and constraints permit it."""

COMMON_FLAT_HANOI_SEMANTICS = """SHARED FLAT-HANOI ACTION SEMANTICS
Peg stacks are listed bottom-to-top. MoveHoop(source_peg,target_peg) requires a
non-empty source and moves exactly its last (top) ring. The target must be empty
or its top ring must be larger than the moved ring. Its effect removes that
same ring from the source and appends it to the target. Ring identity and size
remain unchanged. The final stacks must exactly equal the stated goal stacks."""

_COMMON_DOMAIN_SEMANTICS = {
    "logistics": COMMON_LOGISTICS_SEMANTICS + "\n\n" + COMMON_TEMPORAL_SEMANTICS,
    "blocksworld": COMMON_BLOCKSWORLD_SEMANTICS + "\n\n" + COMMON_TEMPORAL_SEMANTICS,
    "flat-hanoi": COMMON_FLAT_HANOI_SEMANTICS,
}


def common_semantics_contract(domain: str) -> str:
    """Return the frozen benchmark-level contract for one supported domain."""

    normalized = str(domain).strip().lower().replace("_", "-")
    normalized = {
        "lexicon-logistics": "logistics",
        "lexicon-blocksworld": "blocksworld",
        "hanoi": "flat-hanoi",
    }.get(normalized, normalized)
    try:
        return _COMMON_DOMAIN_SEMANTICS[normalized]
    except KeyError as error:
        raise ValueError(f"unsupported comparison-contract domain: {domain!r}") from error

FLAT_HANOI_ACTION_REPRESENTATION = "MoveHoop(source_peg, target_peg)"

# ``_flat_task_signature`` in the Flat-Hanoi adapter uses this same public
# representation: peg count, sorted ring sizes, initial stacks, goal stacks.
# Keeping the example endpoint explicit lets offline tests prove that the
# demonstration is absent from every frozen evaluation dataset.
FLAT_HANOI_SHARED_EXAMPLE_SEMANTIC_SIGNATURE = (
    3,
    (1, 2, 3),
    ((3, 2, 1), (), ()),
    ((), (3, 2, 1), ()),
)

FLAT_HANOI_SHARED_SOLVED_EXAMPLE = """Shared benchmark-level solved example:
For three rings initially stacked on peg_0, largest to smallest, with the goal
of stacking them on peg_1, a shortest legal plan is:
MoveHoop(peg_0, peg_1)
MoveHoop(peg_0, peg_2)
MoveHoop(peg_1, peg_2)
MoveHoop(peg_0, peg_1)
MoveHoop(peg_2, peg_0)
MoveHoop(peg_2, peg_1)
MoveHoop(peg_0, peg_1)
The moved ring is always the current top ring of the source peg. This example
specifies the common syntax and rules; it is not an evaluated Flat-Hanoi pair."""

FLAT_HANOI_DIRECT_SYSTEM_PROMPT = (
    "You are the direct planning condition in a controlled Flat-Hanoi "
    "comparison. Follow the shared task, action, and output contracts exactly."
)


def with_minimum_action_objective(text: str) -> str:
    """Append the shared objective exactly once to public task text."""

    if not isinstance(text, str):
        raise TypeError("public task text must be a string")
    stripped = text.rstrip()
    if MINIMUM_ACTION_OBJECTIVE in stripped:
        return stripped
    return f"{stripped}\n\n{MINIMUM_ACTION_OBJECTIVE}"


def with_comparison_contract(text: str, domain: str) -> str:
    """Append the same public semantics and objective once for every method."""

    if not isinstance(text, str):
        raise TypeError("public task text must be a string")
    contract = common_semantics_contract(domain)
    prepared = text.rstrip()
    if contract not in prepared:
        prepared = f"{prepared}\n\n{contract}"
    return with_minimum_action_objective(prepared)


def flat_hanoi_direct_prompt(problem_text: str) -> str:
    """Wrap the shared Flat-Hanoi task body for the direct condition."""

    shared = with_comparison_contract(problem_text, "flat-hanoi")
    return f"""{shared}

Return only the complete primitive plan, with exactly one
MoveHoop(source_peg, target_peg) call per non-empty line. Do not include prose,
numbering, code fences, JSON, alternative plans, or hierarchy syntax."""


__all__ = [
    "COMPARISON_PROMPT_PROTOCOL_VERSION",
    "COMMON_BLOCKSWORLD_SEMANTICS",
    "COMMON_FLAT_HANOI_SEMANTICS",
    "COMMON_LOGISTICS_SEMANTICS",
    "COMMON_TEMPORAL_SEMANTICS",
    "FLAT_HANOI_ACTION_REPRESENTATION",
    "FLAT_HANOI_DIRECT_SYSTEM_PROMPT",
    "FLAT_HANOI_SHARED_EXAMPLE_SEMANTIC_SIGNATURE",
    "FLAT_HANOI_SHARED_SOLVED_EXAMPLE",
    "MINIMUM_ACTION_OBJECTIVE",
    "common_semantics_contract",
    "flat_hanoi_direct_prompt",
    "with_comparison_contract",
    "with_minimum_action_objective",
]
