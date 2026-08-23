from __future__ import annotations

import json
from typing import List, Optional

from checker_jumping_task import CheckerJumpingTask


def direct_system_prompt() -> str:
    return "Checker Jumping direct planner."


def state_descriptor_system_prompt() -> str:
    return "Checker Jumping StateDescriptor generator."


def common_rules(task: CheckerJumpingTask) -> str:
    return f"""CHECKER JUMPING RULES:
- The board has {task.board_length} zero-indexed positions.
- R checkers move only right. B checkers move only left.
- A checker may slide forward by one position into the empty position.
- A checker may jump forward by two positions into the empty position only when the middle position contains one checker of the opposite color.
- Checkers cannot move backward.
- Every move is MoveChecker(color, source_position, target_position).
- The task succeeds only when the exact goal board is reached."""


def state_spec(
    task: CheckerJumpingTask, board: List[str], *, include_marker: bool = False
) -> str:
    payload = {
        "task_id": task.id,
        "checkers_per_color": task.checkers_per_color,
        "board": board,
        "goal": task.goal,
    }
    encoded = json.dumps(payload, separators=(",", ":"))
    return f"TASK_SPEC_JSON:\n{encoded}" if include_marker else encoded


def feedback_section(feedback: Optional[str]) -> str:
    if not feedback:
        return ""
    return f"\nREPLAN FEEDBACK:\n{feedback}\nCorrect the identified error.\n"


def direct_prompt(
    task: CheckerJumpingTask,
    board: List[str],
    feedback: Optional[str] = None,
) -> str:
    return f"""Solve this Checker Jumping puzzle.

{common_rules(task)}

Initial board: {json.dumps(board)}
Goal board: {json.dumps(task.goal)}
{feedback_section(feedback)}
Return the complete move sequence and no explanation in exactly this form:
moves = [["R", 0, 1], ["B", 2, 0], ...]

Each move is [checker_color, position_from, position_to]. Do not provide an algorithm, pseudocode, comments, or omitted moves.

{state_spec(task, board, include_marker=True)}
"""


def state_descriptor_prompt(
    task: CheckerJumpingTask,
    board: List[str],
    feedback: Optional[str] = None,
) -> str:
    return f"""Create a symbolic StateDescriptor for the current Checker Jumping scene.

{common_rules(task)}

AUTHORITATIVE STATE:
{state_spec(task, board)}
{feedback_section(feedback)}
Return exactly one JSON object between the flags:
```start_flag
{{
  "board": ["R", "_", "B"],
  "goal": ["B", "_", "R"],
  "empty_position": 1,
  "directions": {{"R": "right", "B": "left"}},
  "constraints": ["slide forward one into empty", "jump forward two over opposite color into empty", "no backward moves"]
}}
```end_flag

Copy board and goal exactly from the authoritative state and report the actual empty position.
"""


def inner_state_prompt(
    task: CheckerJumpingTask,
    board: List[str],
    descriptor: str,
) -> str:
    return f"""Check whether the StateDescriptor is complete and exactly faithful to the authoritative state.

{common_rules(task)}

AUTHORITATIVE STATE:
{state_spec(task, board)}

STATE DESCRIPTOR TO VERIFY:
{descriptor}

Return only:
```start_result
RESULT: YES or NO
REASON: N/A if YES, otherwise the first specific mismatch
```end_result
"""


def h1_prompt(task: CheckerJumpingTask, descriptor: str) -> str:
    return f"""Define the H1 action for this Checker Jumping task.

{common_rules(task)}

STATE DESCRIPTOR:
{descriptor}

H1 is fixed to one semantic checker move. Define exactly this mapping and no other mapping:
```start_mapping
MoveCheckerForward(color, source_position, target_position) = [
  MoveChecker(color, source_position, target_position)
]
```end_mapping
"""


def h2_prompt(
    task: CheckerJumpingTask,
    board: List[str],
    descriptor: str,
    h1_output: str,
    feedback: Optional[str] = None,
) -> str:
    return f"""Create one or more H2 functions that solve this concrete task by composing only H1 calls.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, board)}

STATE DESCRIPTOR:
{descriptor}

ALLOWED H1 MAPPING:
{h1_output}
{feedback_section(feedback)}
Every H2 body call must be exactly MoveCheckerForward(color, source_position, target_position).
Do not call MoveChecker directly from H2. Do not call an H2 function from another H2 function.
Concrete zero-argument H2 functions are allowed. Do not omit moves.

Return mappings only:
```start_mapping
H2Function(parameters) = [
  MoveCheckerForward(color, source_position, target_position),
  ...
]
```end_mapping
"""


def fixed_decision_prompt(
    task: CheckerJumpingTask,
    board: List[str],
    descriptor: str,
    h1_output: str,
    h2_output: str,
    feedback: Optional[str] = None,
) -> str:
    return f"""Select and call the supplied H2 functions to solve the task.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, board)}

STATE DESCRIPTOR:
{descriptor}

H1:
{h1_output}

H2:
{h2_output}
{feedback_section(feedback)}
Use only exact H2 function names and exact argument counts from the mappings. Do not emit H1 or H0 calls here.

Return one or more consecutive numbered call blocks:
```start_subtask_funcs_1
H2Function(arguments)
```end_subtask_funcs_1
"""


def plan_only_prompt(
    task: CheckerJumpingTask,
    board: List[str],
    descriptor: str,
    feedback: Optional[str] = None,
) -> str:
    return f"""Decompose the Checker Jumping objective into a concise ordered subtask plan. Do not define functions or moves yet.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, board)}

STATE DESCRIPTOR:
{descriptor}
{feedback_section(feedback)}
For each subtask, provide its natural-language objective and the complete exact board after it.
- IDs must be consecutive integers starting at 1.
- Every goal_state must contain all checkers and exactly one empty position.
- The final goal_state must exactly equal the task goal.

Return one JSON object and no Markdown or explanatory text:
{{
  "subtasks": [
    {{"id": 1, "objective": "concise requirement", "goal_state": ["B", "_", "R"]}}
  ]
}}
"""


def dynamic_hierarchy_prompt(
    task: CheckerJumpingTask,
    board: List[str],
    descriptor: str,
    plan_output: str,
    feedback: Optional[str] = None,
) -> str:
    return f"""You are the HierarchyPlanner. Create the action hierarchy needed to implement the supplied DecisionBot plan.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, board)}

STATE DESCRIPTOR:
{descriptor}

DECISIONBOT SUBTASK PLAN:
{plan_output}
{feedback_section(feedback)}
Infer as many hierarchy levels as are useful. The hierarchy must have at least H1 and H2.
- H1 must be exactly MoveCheckerForward(color, source_position, target_position) = [MoveChecker(color, source_position, target_position)].
- Every H2-or-higher body may call only known lower-level functions.
- No cycles, unknown functions, direct H0 calls above H1, or same-level calls.
- Every body argument must be a declared parameter or a concrete R, B, or board-position literal.
- Every dispatch argument must be a concrete literal, never a parameter placeholder.
- A function's declared level must equal 1 + the maximum level of its callees.
- Each H2-or-higher function must either be reused or contain multiple lower-level calls that compress the top-level plan.
- Concrete zero-argument functions are allowed.
- Dispatch must contain exactly one H2-or-higher call for every DecisionBot subtask ID.
- Do not encode omitted moves, loops, recursion, conditionals, or pseudocode. Every function must expand to a finite explicit MoveChecker sequence.

Represent each function call as {{"function": "Name", "arguments": ["arg", "..."]}}.
Return one JSON object and no Markdown or explanatory text:
{{
  "functions": [
    {{
      "name": "MoveCheckerForward",
      "level": 1,
      "parameters": ["color", "source_position", "target_position"],
      "body": [{{"function": "MoveChecker", "arguments": ["color", "source_position", "target_position"]}}]
    }},
    {{
      "name": "UsefulHigherFunction",
      "level": 2,
      "parameters": [],
      "body": [
        {{"function": "MoveCheckerForward", "arguments": ["R", "0", "1"]}},
        {{"function": "MoveCheckerForward", "arguments": ["B", "2", "0"]}}
      ]
    }}
  ],
  "dispatch": [
    {{"subtask_id": 1, "function": "UsefulHigherFunction", "arguments": []}}
  ]
}}
"""


def inner_plan_prompt(
    task: CheckerJumpingTask,
    board: List[str],
    proposed_output: str,
    deterministic_summary: str,
    *,
    hierarchy_output: Optional[str] = None,
) -> str:
    hierarchy = f"\nHIERARCHY MAPPINGS:\n{hierarchy_output}\n" if hierarchy_output else ""
    return f"""Verify the proposed plan against the current state, goal, action contract, and Checker Jumping rules.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, board)}
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
    task: CheckerJumpingTask,
    board: List[str],
    plan_output: str,
    hierarchy_output: str,
    deterministic_summary: str,
) -> str:
    return f"""You are the InnerBot router. Verify that DecisionBot chose correct subtasks and HierarchyPlanner implemented them with a valid executable hierarchy.

{common_rules(task)}

CURRENT STATE AND GOAL:
{state_spec(task, board)}

DECISIONBOT PLAN:
{plan_output}

HIERARCHYPLANNER OUTPUT:
{hierarchy_output}

DETERMINISTIC VALIDATOR SUMMARY:
{deterministic_summary}

If there is an error, assign it to DecisionBot, HierarchyPlanner, or both.
Return only:
```start_result
RESULT: YES or NO
OWNER: NA, DecisionBot, HierarchyPlanner, or both
REASON: N/A if YES, otherwise the first specific error
```end_result
"""


def outer_prompt(
    task: CheckerJumpingTask,
    before: List[str],
    after: List[str],
    expected: List[str],
    requirement: str,
) -> str:
    return f"""You are the OuterBot execution-state verifier.

{common_rules(task)}

SUBTASK REQUIREMENT:
{requirement}

STATE BEFORE EXECUTION: {json.dumps(before)}
STATE AFTER EXECUTION: {json.dumps(after)}
EXPECTED STATE: {json.dumps(expected)}
FINAL TASK GOAL: {json.dumps(task.goal)}

Return only:
```start_error_type
Error: TASK SUCCESS, SUBTASK SUCCESS, EXECUTE REMAINING ACTIONS, RECOVERABLE, or NON-RECOVERABLE
Reason: N/A for success, otherwise the first specific mismatch
```end_error_type
"""


__all__ = [name for name in globals() if name.endswith("_prompt") or name in {"common_rules", "state_spec"}]
