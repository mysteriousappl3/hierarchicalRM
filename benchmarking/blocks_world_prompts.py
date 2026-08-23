from __future__ import annotations

import json
from typing import Dict, List, Optional

from blocks_world_task import BlocksWorldTask


def as_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def task_spec(task: BlocksWorldTask) -> Dict[str, object]:
    return {
        "task_id": task.id,
        "domain": "blocks_world",
        "block_count": task.block_count,
        "stack_order": "bottom_to_top",
        "stack_ids": list(task.stack_ids),
        "initial": task.initial,
        "goal": task.goal,
        "primitive": "MoveBlock(block, source_stack, target_stack)",
    }


def state_spec(task: BlocksWorldTask, state: Dict[str, List[str]]) -> str:
    return as_json(
        {
            "stack_order": "bottom_to_top",
            "current": state,
            "goal": task.goal,
        }
    )


def common_rules(task: BlocksWorldTask) -> str:
    return f"""BLOCKS WORLD RULES:
- There are exactly three stacks: {', '.join(task.stack_ids)}.
- Every stack array is ordered bottom-to-top; the last item is the top block.
- Move exactly one block at a time.
- Only the top block of a nonempty source stack can move.
- A moved block is placed on top of the target stack.
- Source and target stacks must differ.
- Every block must occur exactly once.

The only executable primitive is exactly:
MoveBlock(block, source_stack, target_stack)

Do not invent other primitives. Success means the final state exactly equals the goal."""


def feedback_section(feedback: Optional[str]) -> str:
    if not feedback:
        return ""
    return f"\nPREVIOUS ATTEMPT FEEDBACK:\n{feedback}\nCorrect the identified mistake.\n"


def direct_system_prompt() -> str:
    return """Direct Blocks World agent.

You are a helpful assistant. Solve this puzzle for me.
In this puzzle, there are stacks of blocks, and the goal is to rearrange them into a target configuration using a sequence of moves where:
- Only the topmost block from any stack can be moved.
- A block can be placed either on an empty position or on top of another block.

Example: With initial state [["A", "B"], ["C"], []] and goal state [["A"], ["B"], ["C"]], a solution might be:
moves = [["C", 1, 2], ["B", 0, 1]]

The positions are 0-indexed. The final answer must include the complete list in this format:
moves = [[block, from_stack, to_stack], ...]"""


def direct_prompt(
    task: BlocksWorldTask,
    state: Dict[str, List[str]],
    feedback: Optional[str] = None,
) -> str:
    lines = [f"I have a puzzle with {task.block_count} blocks.", "Initial state:"]
    for stack in task.stack_ids:
        lines.append(f"Stack {stack}: {json.dumps(state[stack])} (last item is top)")
    lines.append("Goal state:")
    for stack in task.stack_ids:
        lines.append(f"Stack {stack}: {json.dumps(task.goal[stack])} (last item is top)")
    lines.extend(
        [
            "Find the minimum sequence of moves to transform the initial state into the goal state.",
            "Remember that only the topmost block of each stack can be moved.",
            feedback_section(feedback),
        ]
    )
    return "\n".join(lines).strip() + "\n"


def state_descriptor_prompt(
    task: BlocksWorldTask,
    state: Dict[str, List[str]],
    feedback: Optional[str] = None,
) -> str:
    return f"""Describe the current symbolic scene for a hierarchical planner.

{common_rules(task)}

AUTHORITATIVE STATE:
{state_spec(task, state)}
{feedback_section(feedback)}
Return one valid JSON object inside these exact flags:
```start_flag
{{
  "stack_order": "bottom_to_top",
  "current": {{"0": [...], "1": [...], "2": [...]}},
  "goal": {{"0": [...], "1": [...], "2": [...]}},
  "constraints": ["..."]
}}
```end_flag

Copy current and goal exactly. Arrays are bottom-to-top.
"""


def inner_state_prompt(
    task: BlocksWorldTask,
    state: Dict[str, List[str]],
    descriptor: str,
) -> str:
    return f"""Check whether the StateDescriptor is complete and exactly faithful to the authoritative state.

{common_rules(task)}

AUTHORITATIVE STATE:
{state_spec(task, state)}

STATE DESCRIPTOR TO VERIFY:
{descriptor}

Return only:
```start_result
RESULT: YES or NO
REASON: N/A if YES, otherwise the specific mismatch
```end_result
"""


def h1_prompt(task: BlocksWorldTask, descriptor: str) -> str:
    return f"""Define the H1 action for this Blocks World task.

{common_rules(task)}

STATE DESCRIPTOR:
{descriptor}

H1 is fixed to one semantic block move. Define exactly this mapping and no other mapping:
```start_mapping
MoveTopBlock(block, source_stack, target_stack) = [
  MoveBlock(block, source_stack, target_stack)
]
```end_mapping
"""


def h2_prompt(
    task: BlocksWorldTask,
    state: Dict[str, List[str]],
    descriptor: str,
    h1_output: str,
    feedback: Optional[str] = None,
) -> str:
    return f"""Create one or more H2 functions that solve this concrete task by composing only H1 calls.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, state)}

STATE DESCRIPTOR:
{descriptor}

ALLOWED H1 MAPPING:
{h1_output}
{feedback_section(feedback)}
Every H2 body call must be exactly MoveTopBlock(block, source_stack, target_stack).
Do not call MoveBlock directly from H2. Do not call an H2 function from another H2 function.
Concrete zero-argument H2 functions are allowed.

Return mappings only:
```start_mapping
H2Function(parameters) = [
  MoveTopBlock(block, source_stack, target_stack),
  ...
]
```end_mapping
"""


def fixed_decision_prompt(
    task: BlocksWorldTask,
    state: Dict[str, List[str]],
    descriptor: str,
    h1_output: str,
    h2_output: str,
    feedback: Optional[str] = None,
) -> str:
    return f"""Select and call the supplied H2 functions to solve the task.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, state)}

STATE DESCRIPTOR:
{descriptor}

H1:
{h1_output}

H2:
{h2_output}
{feedback_section(feedback)}
Use only exact H2 function names and exact argument counts from the mappings. Do not emit H1 or H0 calls here.

Return one or more numbered call blocks:
```start_subtask_funcs_1
H2Function(arguments)
```end_subtask_funcs_1
"""


def plan_only_prompt(
    task: BlocksWorldTask,
    state: Dict[str, List[str]],
    descriptor: str,
    feedback: Optional[str] = None,
) -> str:
    return f"""Decompose the Blocks World objective into a concise ordered subtask plan. Do not define functions or moves yet.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, state)}

STATE DESCRIPTOR:
{descriptor}
{feedback_section(feedback)}
For each subtask, provide its natural-language objective and the complete exact state after it.
- IDs must be consecutive integers starting at 1.
- Every goal_state must contain stacks 0, 1, and 2 and every block exactly once.
- The final goal_state must exactly equal the task goal.

Return one JSON object and no Markdown or explanatory text:
{{
  "subtasks": [
    {{
      "id": 1,
      "objective": "concise requirement",
      "goal_state": {{"0": ["..."], "1": ["..."], "2": ["..."]}}
    }}
  ]
}}
"""


def dynamic_hierarchy_prompt(
    task: BlocksWorldTask,
    state: Dict[str, List[str]],
    descriptor: str,
    plan_output: str,
    feedback: Optional[str] = None,
) -> str:
    return f"""You are the HierarchyPlanner. Create the action hierarchy needed to implement the supplied DecisionBot plan.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, state)}

STATE DESCRIPTOR:
{descriptor}

DECISIONBOT SUBTASK PLAN:
{plan_output}
{feedback_section(feedback)}
Infer as many hierarchy levels as are useful. The hierarchy must have at least H1 and H2.
- H1 must be exactly MoveTopBlock(block, source_stack, target_stack) = [MoveBlock(block, source_stack, target_stack)].
- Every H2-or-higher body may call only known lower-level functions.
- No cycles, unknown functions, direct H0 calls above H1, or same-level calls.
- Every body argument must be a declared parameter or a concrete block/stack literal.
- Every dispatch argument must be a concrete block/stack literal, never a parameter placeholder.
- A function's declared level must equal 1 + the maximum level of its callees.
- Each H2-or-higher function must either be reused or contain multiple lower-level calls that compress the top-level plan.
- Concrete zero-argument functions are allowed and are usually best for a task-specific plan.
- Dispatch must contain exactly one H2-or-higher call for every DecisionBot subtask ID.

Represent each function call as {{"function": "Name", "arguments": ["arg", "..."]}}.
Return one JSON object and no Markdown or explanatory text:
{{
  "functions": [
    {{
      "name": "MoveTopBlock",
      "level": 1,
      "parameters": ["block", "source_stack", "target_stack"],
      "body": [{{"function": "MoveBlock", "arguments": ["block", "source_stack", "target_stack"]}}]
    }},
    {{
      "name": "UsefulHigherFunction",
      "level": 2,
      "parameters": [],
      "body": [
        {{"function": "MoveTopBlock", "arguments": ["A", "0", "2"]}},
        {{"function": "MoveTopBlock", "arguments": ["B", "1", "0"]}}
      ]
    }}
  ],
  "dispatch": [
    {{"subtask_id": 1, "function": "UsefulHigherFunction", "arguments": []}}
  ]
}}
"""


def inner_plan_prompt(
    task: BlocksWorldTask,
    state: Dict[str, List[str]],
    proposed_output: str,
    deterministic_summary: str,
    *,
    hierarchy_output: Optional[str] = None,
) -> str:
    hierarchy = f"\nHIERARCHY MAPPINGS:\n{hierarchy_output}\n" if hierarchy_output else ""
    return f"""Verify the proposed plan against the current state, goal, action contract, and Blocks World rules.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, state)}
{hierarchy}
PROPOSED PLAN:
{proposed_output}

DETERMINISTIC VALIDATOR SUMMARY:
{deterministic_summary}

Return only:
```start_result
RESULT: YES or NO
REASON: N/A if YES, otherwise the first specific error
```end_result
"""


def router_prompt(
    task: BlocksWorldTask,
    state: Dict[str, List[str]],
    plan_output: str,
    hierarchy_output: str,
    deterministic_summary: str,
) -> str:
    return f"""You are the InnerBot router. Verify that DecisionBot chose correct subtasks and HierarchyPlanner implemented them with a valid executable hierarchy.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, state)}

DECISIONBOT OUTPUT:
{plan_output}

HIERARCHYPLANNER OUTPUT:
{hierarchy_output}

DETERMINISTIC VALIDATOR SUMMARY:
{deterministic_summary}

If there is a mistake, assign OWNER as DecisionBot, HierarchyPlanner, or both. Return only:
```start_result
RESULT: YES or NO
OWNER: NA or DecisionBot or HierarchyPlanner or both
REASON: N/A if YES, otherwise the first specific error
```end_result
"""


def outer_prompt(
    task: BlocksWorldTask,
    previous_state: Dict[str, List[str]],
    current_state: Dict[str, List[str]],
    expected_state: Dict[str, List[str]],
    subtask_requirement: str,
) -> str:
    return f"""You are OuterBot. Compare the observed post-execution state with the subtask requirement, expected state, and final task goal.

{common_rules(task)}

SUBTASK REQUIREMENT:
{subtask_requirement}

PREVIOUS STATE:
{as_json(previous_state)}

EXPECTED STATE AFTER SUBTASK:
{as_json(expected_state)}

OBSERVED CURRENT STATE:
{as_json(current_state)}

FINAL TASK GOAL:
{as_json(task.goal)}

Choose exactly one status: TASK SUCCESS, SUBTASK SUCCESS, EXECUTE REMAINING ACTIONS, RECOVERABLE, or NON-RECOVERABLE.
Return only:
```start_error_type
Error: STATUS
Reason: N/A for success, otherwise a specific mismatch
```end_error_type
"""


__all__ = [
    "as_json",
    "direct_prompt",
    "direct_system_prompt",
    "dynamic_hierarchy_prompt",
    "fixed_decision_prompt",
    "h1_prompt",
    "h2_prompt",
    "inner_plan_prompt",
    "inner_state_prompt",
    "outer_prompt",
    "plan_only_prompt",
    "state_descriptor_prompt",
    "state_spec",
    "task_spec",
]
