"""Prompt contracts for the shared N-level LexiCon Blocksworld adapter.

The model sees only released task text, public state, and public verifier
evidence.  Oracle actions, optimal lengths, and compiled monitor predicates
remain evaluator-only.
"""

from __future__ import annotations

import json
from typing import Mapping, Optional, Sequence


SYSTEM_STATE_DESCRIPTOR = (
    "StateDescriptor: produce the complete current LexiCon Blocksworld state, "
    "goal, and temporal constraints."
)
SYSTEM_INNERBOT_STATE = (
    "InnerBot state verifier: compare a LexiCon Blocksworld StateDescriptor "
    "with the authoritative task view."
)
SYSTEM_H1 = (
    "H1ActionGenerator: define the four single-state-change Blocksworld H1 "
    "wrappers over the PDDL H0 actions."
)
SYSTEM_DECISION = (
    "DecisionBot planner: produce numbered Blocksworld subtasks and symbolic "
    "checkpoints only, with no actions."
)
SYSTEM_HIERARCHY = (
    "HierarchyPlanner: compose H2 through Hn Blocksworld mappings and calls "
    "for the DecisionBot checkpoints."
)
SYSTEM_ROUTER = (
    "InnerBot router: attribute a LexiCon Blocksworld planning or hierarchy "
    "error to DecisionBot, HierarchyPlanner, or both."
)
SYSTEM_OUTERBOT = (
    "OuterBot execution verifier: judge a deterministically simulated "
    "LexiCon Blocksworld subtask transition."
)


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _feedback(value: Optional[str]) -> str:
    return value or "N/A"


def state_descriptor_prompt(
    problem_text: str,
    authoritative_view: Mapping[str, object],
    feedback: Optional[str] = None,
) -> str:
    return f"""You are the StateDescriptor for a LexiCon Blocksworld task.

Copy the complete authoritative current-state view exactly.  It contains the
current public PDDL facts and executed-action prefix because temporal
constraints depend on history.  Do not infer, omit, reorder, rename, or add.

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

Every field and nested value, including ordering, must equal the authoritative
view.  Evaluator-only oracle plans and optimal lengths are unavailable.
"""


def innerbot_state_prompt(
    authoritative_view: Mapping[str, object], descriptor_output: str
) -> str:
    return f"""You are the InnerBot state verifier for LexiCon Blocksworld.

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
    return f"""You are the H1 action generator for LexiCon Blocksworld.

H0 is the executable PDDL action layer.  Generate exactly four generic H1
functions, one per H0 action.  Each H1 function represents one state change
and contains exactly its corresponding H0 call in identical parameter order.
Do not solve the task or put concrete block names in a mapping definition.

LEXICON TASK (domain context only):
{problem_text}

CURRENT TASK VIEW (legal identifier context only):
{_json(current_view)}

AUTHORITATIVE H0 ACTIONS AND SIGNATURES:
{_json(h0_spec)}

Required H1 names:
- Pickup -> pickup
- Putdown -> putdown
- Stack -> stack
- Unstack -> unstack

Return all four mappings in exactly one block:
```start_mapping
Pickup(block) = [pickup(block)],
Putdown(block) = [putdown(block)],
Stack(block, support) = [stack(block, support)],
Unstack(block, support) = [unstack(block, support)]
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
    return f"""You are the DecisionBot plan-only planner for LexiCon Blocksworld.

Decompose the task into concise ordered semantic checkpoints.  Plan only: do
not emit PDDL actions, arm motions, hierarchy functions, or function calls.
The HierarchyPlanner implements checkpoints later.

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
A natural-language objective naming every relevant block and relation.
```end_subtask_N
```start_subtask_goalstate_N
{{
  "required_true": ["(on red_block_1 blue_block_1)"],
  "required_false": ["(holding red_block_1)"],
  "constraints_addressed": [1]
}}
```end_subtask_goalstate_N

Rules:
- Number subtasks consecutively from 1 without gaps.
- Checkpoint facts are canonical ground `clear`, `ontable`, `handempty`,
  `holding`, or `on` atoms.  `(handempty)` has no arguments.
- `required_false` contains positive atoms that must be absent, never `(not ...)`.
- A fact may not occur in both lists.
- The final checkpoint's `required_true` contains every final task goal.
- Constraint indices are one-based and collectively cover every listed
  temporal constraint.  They encode intent; compiled PDDL remains authoritative.
- Return no executable action or function-call syntax anywhere.
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
    return f"""You are the dynamic HierarchyPlanner for LexiCon Blocksworld.

Implement the DecisionBot checkpoints as an arbitrary-depth hierarchy.  H0 is
the PDDL action layer.  H1 is generated and verified below.  Define H2, H3,
and deeper functions when useful, then give concrete top-level calls for each
DecisionBot subtask.

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
- A custom body calls only known lower-level functions, never raw H0.
- No recursion, cycles, conditionals, loops, prose actions, or unknown helpers.
- Definitions are generic: every body argument is a declared parameter, not a
  concrete task object.
- Use every parameter and remove unused parameters.
- Do not declare level labels; the evaluator infers levels from the call graph.
- No minimum reuse or compression is required.  Correctness is separate from
  hierarchy-quality metrics.
- {code_instruction}

Put every custom mapping in one block, for example:
```start_mapping
ClearToTable(block, support) = [Unstack(block, support), Putdown(block)],
MoveTableBlock(block, destination) = [Pickup(block), Stack(block, destination)]
```end_mapping

Then provide exactly one numbered block per DecisionBot subtask in the same
order.  Blocks contain one or more calls using only task objects:
```start_subtask_funcs_1
ClearToTable(red_block_1, blue_block_1)
```end_subtask_funcs_1

Every custom function must infer to H2 or deeper.  Direct H1 calls in numbered
blocks are valid; hierarchy usefulness is only reported as a metric.  Return
no oracle references.
"""


def router_prompt(
    problem_text: str,
    descriptor_output: str,
    decision_output: str,
    hierarchy_output: str,
    deterministic_evidence: Mapping[str, object],
    feedback: Optional[str] = None,
) -> str:
    return f"""You are the InnerBot ownership router for LexiCon Blocksworld.

DecisionBot specified semantic checkpoints without actions.  HierarchyPlanner
specified mappings and concrete calls.  Decide whether they are jointly
correct and, if not, which component must change.

LEXICON TASK:
{problem_text}

CURRENT STATE:
{descriptor_output}

DECISIONBOT PLAN:
{decision_output}

HIERARCHYPLANNER OUTPUT:
{hierarchy_output}

DETERMINISTIC COMPILED-PDDL EVIDENCE:
{_json(deterministic_evidence)}

ADDITIONAL FEEDBACK:
{_feedback(feedback)}

Treat parser, call-graph, binding, and simulator facts as authoritative.
- DecisionBot: a checkpoint/decomposition is impossible, incomplete, wrongly
  ordered, or incompatible with goals or temporal constraints.
- HierarchyPlanner: checkpoints are sound but mappings/calls do not realize them.
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
Blocksworld subtask.

The PDDL simulator's facts are authoritative.  Explain and classify the
transition, but never override applicability, checkpoint, goal, or temporal
constraint results.

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
- TASK SUCCESS: only when deterministic final verification is valid.
- SUBTASK SUCCESS: the transition and checkpoint hold, but the full task is not
  yet certified.
- EXECUTE REMAINING ACTIONS: this transition is sound and later subtasks remain.
- RECOVERABLE: a corrected plan/hierarchy can continue from current state.
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
