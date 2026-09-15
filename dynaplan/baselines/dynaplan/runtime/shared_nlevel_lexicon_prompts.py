"""Model prompts for the shared N-level LexiCon Logistics adapter.

The shared pipeline owns orchestration.  This module owns only the Logistics
wording and serialization contract.  In particular, no function accepts an
oracle plan or an optimal length: those are evaluator-only fields and must
never enter a model prompt.
"""

from __future__ import annotations

import json
from typing import Mapping, Optional, Sequence


SYSTEM_STATE_DESCRIPTOR = (
    "StateDescriptor: produce the complete current LexiCon Logistics state, "
    "goal, and temporal constraints."
)
SYSTEM_INNERBOT_STATE = (
    "InnerBot state verifier: compare a LexiCon Logistics StateDescriptor "
    "with the authoritative task view."
)
SYSTEM_H1 = (
    "H1ActionGenerator: define the six single-state-change Logistics H1 "
    "wrappers over the PDDL H0 actions."
)
SYSTEM_DECISION = (
    "DecisionBot planner: produce numbered Logistics subtasks and symbolic "
    "checkpoints only, with no actions."
)
SYSTEM_HIERARCHY = (
    "HierarchyPlanner: compose H2 through Hn Logistics mappings and calls "
    "for the DecisionBot checkpoints."
)
SYSTEM_ROUTER = (
    "InnerBot router: attribute a LexiCon planning or hierarchy error to "
    "DecisionBot, HierarchyPlanner, or both."
)
SYSTEM_OUTERBOT = (
    "OuterBot execution verifier: judge a deterministically simulated "
    "LexiCon Logistics subtask transition."
)


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _feedback(value: Optional[str]) -> str:
    if not value:
        return "N/A"
    return value


def state_descriptor_prompt(
    problem_text: str,
    authoritative_view: Mapping[str, object],
    feedback: Optional[str] = None,
) -> str:
    """Ask for a lossless descriptor of the *current* execution prefix."""

    return f"""You are the StateDescriptor for a LexiCon Logistics task.

Read the task and copy the complete authoritative current-state view exactly.
The view contains the current public PDDL facts and the already executed action
prefix because temporal constraints depend on history.  Do not infer, omit,
reorder, rename, or add anything.

LEXICON TASK:
{problem_text}

AUTHORITATIVE CURRENT-STATE VIEW:
{_json(authoritative_view)}

PREVIOUS FEEDBACK:
{_feedback(feedback)}

Return exactly one JSON object between these flags and no other text:
```start_flag
{{
  "task_id": "...",
  "objects_by_type": {{...}},
  "current_facts": ["..."],
  "goals": ["..."],
  "constraints": ["..."],
  "executed_actions": ["..."]
}}
```end_flag

Every field and value, including list ordering, must equal the authoritative
view.  Evaluator-only oracle plans and optimal lengths are neither needed nor
available.
"""


def innerbot_state_prompt(
    authoritative_view: Mapping[str, object], descriptor_output: str
) -> str:
    return f"""You are the InnerBot state verifier for LexiCon Logistics.

Compare the candidate with the authoritative current-state view.  It is valid
only if all six fields and every nested value match exactly.

AUTHORITATIVE CURRENT-STATE VIEW:
{_json(authoritative_view)}

CANDIDATE STATE DESCRIPTOR:
{descriptor_output}

Return only:
```start_result
RESULT: YES or NO
REASON: N/A if YES, otherwise the precise mismatch
```end_result
"""


def h1_prompt(
    problem_text: str,
    h0_spec: Mapping[str, object],
    current_view: Mapping[str, object],
) -> str:
    """Match the Flat-Hanoi H1-generation stage with typed Logistics H0."""

    return f"""You are the H1 action generator for LexiCon Logistics.

H0 is the executable PDDL action layer.  Generate exactly six generic H1
functions, one for each H0 action.  An H1 function represents one state change
and its body must contain exactly the corresponding H0 call with identical
parameter order.  Do not solve the task and do not use concrete task objects in
a mapping definition.

LEXICON TASK (for domain context only):
{problem_text}

CURRENT TASK VIEW (for legal identifier context only):
{_json(current_view)}

AUTHORITATIVE H0 ACTIONS AND SIGNATURES:
{_json(h0_spec)}

Required H1 names:
- LoadTruck -> loadtruck
- LoadAirplane -> loadairplane
- UnloadTruck -> unloadtruck
- UnloadAirplane -> unloadairplane
- DriveTruck -> drivetruck
- FlyAirplane -> flyairplane

Return all six mappings inside one flag pair and no other mapping block:
```start_mapping
LoadTruck(package, truck, location) = [loadtruck(package, truck, location)],
LoadAirplane(package, airplane, location) = [loadairplane(package, airplane, location)],
UnloadTruck(package, truck, location) = [unloadtruck(package, truck, location)],
UnloadAirplane(package, airplane, location) = [unloadairplane(package, airplane, location)],
DriveTruck(truck, from_location, to_location, city) = [drivetruck(truck, from_location, to_location, city)],
FlyAirplane(airplane, from_airport, to_airport) = [flyairplane(airplane, from_airport, to_airport)]
```end_mapping

Parameter names may differ, but arity, type compatibility, primitive choice,
and argument order must be exact.  Return no plan and no concrete calls.
"""


def decision_prompt(
    problem_text: str,
    descriptor_output: str,
    h1_output: str,
    feedback: Optional[str] = None,
) -> str:
    return f"""You are the DecisionBot plan-only planner for LexiCon Logistics.

Decompose the task into concise, ordered semantic checkpoints.  Plan only: do
not emit PDDL actions, vehicle routes, hierarchy functions, or function calls.
The HierarchyPlanner will implement the checkpoints later.

LEXICON TASK:
{problem_text}

VERIFIED CURRENT STATE DESCRIPTOR:
{descriptor_output}

VERIFIED H1 ACTION BOUNDARY (do not call these):
{h1_output}

PREVIOUS FEEDBACK:
{_feedback(feedback)}

For every subtask N, return exactly these adjacent blocks:
```start_subtask_N
A natural-language objective naming every relevant package, vehicle, and place.
```end_subtask_N
```start_subtask_goalstate_N
{{
  "required_true": ["(at_ p1 l1_1)"],
  "required_false": ["(in p1 t1)"],
  "constraints_addressed": [1]
}}
```end_subtask_goalstate_N

Rules:
- Number subtasks consecutively from 1 with no gaps.
- Checkpoint facts must be canonical, ground `at_`, `in`, or `incity` atoms.
- `required_false` contains positive atoms that must be absent, never `(not ...)`.
- A fact may not appear in both lists.
- The final checkpoint's `required_true` must contain every final task goal.
- Constraint indices are one-based and collectively cover every listed temporal
  constraint.  They state planning intent; the compiled PDDL simulator remains
  the authority on whether a constraint is actually satisfied.
- Return no executable actions or calls anywhere in the response.
"""


def hierarchy_prompt(
    problem_text: str,
    descriptor_output: str,
    h1_output: str,
    decision_output: str,
    feedback: Optional[str] = None,
    *,
    include_code_block: bool = False,
) -> str:
    code_instruction = (
        "You may additionally put human-readable pseudocode in one "
        "```start_flag/```end_flag block; it is never executed or parsed."
        if include_code_block
        else "Do not include source code or pseudocode."
    )
    return f"""You are the dynamic HierarchyPlanner for LexiCon Logistics.

Implement the DecisionBot checkpoints as an arbitrary-depth hierarchy.  H0 is
the PDDL action layer.  H1 is model-generated and verified below.  Define H2,
H3, and deeper functions as useful, then give the concrete top-level calls for
each DecisionBot subtask.

LEXICON TASK:
{problem_text}

VERIFIED CURRENT STATE DESCRIPTOR:
{descriptor_output}

VERIFIED H1 MAPPINGS (the only base functions custom mappings may call):
{h1_output}

DECISIONBOT CHECKPOINT PLAN:
{decision_output}

PREVIOUS FEEDBACK:
{_feedback(feedback)}

Mapping rules:
- A custom function body may call only known lower-level functions, never H0.
- No recursion, cycles, conditionals, loops, prose actions, or unknown helpers.
- Definitions are generic: body arguments must be declared parameters, not
  concrete task objects.
- Use every parameter and remove unused parameters.
- Do not write or declare `H2`, `H3`, or another level label.  The evaluator
  infers every level from the call graph.
- There is no minimum reuse or compression requirement.  Correct execution is
  separate from hierarchy-quality metrics.
- {code_instruction}

Put every custom mapping in one block:
```start_mapping
TruckPickup(package, truck, truck_start, pickup, city) = [DriveTruck(truck, truck_start, pickup, city), LoadTruck(package, truck, pickup)],
TruckDelivery(package, truck, truck_start, dropoff, city) = [DriveTruck(truck, truck_start, dropoff, city), UnloadTruck(package, truck, dropoff)]
```end_mapping

Then provide exactly one numbered call block for each DecisionBot subtask, in
the same order.  A block may contain one or more calls.  Calls use only concrete
objects from the task:
```start_subtask_funcs_1
TruckPickup(p1, t1, l1_5, l1_1, c1)
```end_subtask_funcs_1

Every custom function must infer to H2 or deeper.  Prefer meaningful H2-or-
higher calls where they compress the plan, but direct H1 calls in a numbered
subtask block are valid and hierarchy usefulness is reported only as a metric.
Return no oracle references.
"""


def router_prompt(
    problem_text: str,
    descriptor_output: str,
    decision_output: str,
    hierarchy_output: str,
    deterministic_evidence: Mapping[str, object],
    feedback: Optional[str] = None,
) -> str:
    return f"""You are the InnerBot ownership router for LexiCon Logistics.

DecisionBot specified semantic checkpoints but no actions.  HierarchyPlanner
specified mappings and concrete calls.  Determine whether the two artifacts
together are correct and, if not, which component must change.

LEXICON TASK:
{problem_text}

CURRENT STATE:
{descriptor_output}

DECISIONBOT PLAN:
{decision_output}

HIERARCHYPLANNNER OUTPUT:
{hierarchy_output}

DETERMINISTIC COMPILED-PDDL EVIDENCE:
{_json(deterministic_evidence)}

ADDITIONAL FEEDBACK:
{_feedback(feedback)}

Treat successful parsing, call-graph inference, binding checks, and simulator
facts in the deterministic evidence as authoritative.  Judge semantic
ownership:
- DecisionBot: a checkpoint/decomposition is impossible, incomplete, wrongly
  ordered, or incompatible with the goals or temporal constraints.
- HierarchyPlanner: the checkpoints are sound but mappings/calls fail to carry
  them out.
- both: both artifacts independently require changes.

Return only:
```start_result
RESULT: YES or NO
OWNER: NA if YES; otherwise DecisionBot, HierarchyPlanner, or both
REASON: N/A if YES; otherwise a precise concise reason
```end_result
"""


def outerbot_prompt(
    problem_text: str,
    subtask_description: str,
    checkpoint: Mapping[str, object],
    previous_state: Mapping[str, object],
    current_state: Mapping[str, object],
    executed_actions: Sequence[str],
    deterministic_evidence: Mapping[str, object],
) -> str:
    return f"""You are the OuterBot post-execution verifier for one LexiCon
Logistics subtask.

The PDDL simulator's facts are authoritative.  You may explain and classify
the transition, but may not override its applicability, checkpoint, goal, or
temporal-constraint result.

LEXICON TASK:
{problem_text}

SUBTASK OBJECTIVE:
{subtask_description}

SUBTASK CHECKPOINT:
{_json(checkpoint)}

PREVIOUS PUBLIC STATE:
{_json(previous_state)}

CURRENT PUBLIC STATE:
{_json(current_state)}

EXECUTED H0 ACTIONS FOR THIS SUBTASK:
{_json(list(executed_actions))}

DETERMINISTIC COMPILED-PDDL EVIDENCE:
{_json(deterministic_evidence)}

Choose exactly one status:
- TASK SUCCESS: permitted only when deterministic final verification is valid.
- SUBTASK SUCCESS: transition was applicable and its checkpoint is satisfied,
  but the full task is not yet certified complete.
- EXECUTE REMAINING ACTIONS: this transition is sound and later planned
  subtasks remain.
- RECOVERABLE: a corrected plan/hierarchy can continue from the current state.
- NON-RECOVERABLE: the recorded execution state itself is unusable.

Return only:
```start_result
VERDICT: one status above
REASON: concise evidence-grounded reason
```end_result
"""


__all__ = [
    "SYSTEM_DECISION",
    "SYSTEM_H1",
    "SYSTEM_HIERARCHY",
    "SYSTEM_INNERBOT_STATE",
    "SYSTEM_OUTERBOT",
    "SYSTEM_ROUTER",
    "SYSTEM_STATE_DESCRIPTOR",
    "decision_prompt",
    "h1_prompt",
    "hierarchy_prompt",
    "innerbot_state_prompt",
    "outerbot_prompt",
    "router_prompt",
    "state_descriptor_prompt",
]
