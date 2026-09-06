"""Prompt builders for flat-to-flat Tower of Hanoi, mirroring prompts.py.

prompts.py's build_scene_description, build_goal_description, build_h1_prompt,
build_h2_prompt, build_innerbot_state_prompt, build_innerbot_plan_prompt, and
build_outerbot_prompt are already endpoint-agnostic -- they only read
task.pegs, task.rings, task.initial/task.goal, or take pre-built JSON as
arguments -- so they are imported and reused unchanged.

Only task_spec_for_prompt, build_decision_prompt, build_innerbot_direct_plan_prompt,
and build_direct_hanoi_prompt reference source_peg/auxiliary_peg/target_peg or
narrate "using X as the auxiliary peg". Those get flat-specific counterparts
here that omit the tower framing entirely: a flat task has no privileged
source or auxiliary peg, and leaking that framing into the prompt would
invite the memorized tower-to-tower recursive template the flat variant
exists to defeat.
"""

from __future__ import annotations

from typing import Dict, List

from flat_hanoi_task_loader import FlatHanoiTask
from prompts import (
    H0_ACTIONS_DESCRIPTION,
    JSON_EQUIVALENT_NOTE,
    PREDICATES_DESCRIPTION,
    as_json,
    build_goal_description,
    build_h1_prompt,
    build_h2_prompt,
    build_innerbot_plan_prompt,
    build_innerbot_state_prompt,
    build_outerbot_prompt,
    build_scene_description,
    split_framework_feedback,
)

__all__ = [
    "as_json",
    "build_goal_description",
    "build_h1_prompt",
    "build_h2_prompt",
    "build_innerbot_plan_prompt",
    "build_innerbot_state_prompt",
    "build_outerbot_prompt",
    "build_scene_description",
    "task_spec_for_prompt",
    "build_state_prompt",
    "build_decision_prompt",
    "build_innerbot_direct_plan_prompt",
    "build_direct_hanoi_prompt",
]


def task_spec_for_prompt(task: FlatHanoiTask) -> str:
    raw = {
        "id": task.id,
        "pegs": task.pegs,
        "rings": [ring.__dict__ for ring in task.rings],
        "initial": task.initial,
        "goal": task.goal,
        "instruction": task.instruction,
    }
    return as_json(raw)


def build_state_prompt(
    task: FlatHanoiTask,
    scene_json: Dict[str, object],
    previous_state_output: str = "N/A",
    feedback: str = "N/A",
) -> str:
    expected_state = build_goal_description(task)
    return f"""
            Using the given JSON scene description and user instruction,
            create a dictionary called "goal_spatial_relations". Also don't forget to generate another dictionary
            that is called "constraint_spatial_relations" so that it contains any restrictions/constraints on action performed by the robot at any time given in the user instruction.
            Both "goal_spatial_relations" and "constraint_spatial_relations" should follow the format of spatial_relations.
            Note that spatial_relations denotes the list of relationships between objects. Use only the following objects to describe these relations. [A, B] means A AND B and you may use (A OR B) and NOT A to indicate disjunction and negation. Make sure your predicate only contains object names as parameters.
            {PREDICATES_DESCRIPTION}
            If there are no constraints that the robot must follow in every action, it should be empty.
            Please take note of the following:
            1. The response should be a Python dictionary only, without any explanatory text (e.g., Do not include a sentence like "here is the environment").

            VLM output format:
            {{
                "goal_spatial_relations": {{
                    "<object_one>": ["predicate_one(<object_three>)"],
                    "<object_two>": [...],
                    ...
                }},
                "constraint_spatial_relations": {{
                    "<object_one>": [
                        "NOT(predicate_two(<another_object>))",
                        "NOT(predicate_three(<another_object_2>))"
                    ],
                    "<object_two>": [
                        "predicate_five(<another_object_3>)"
                    ],
                    ...
                }}
            }}


            Also, a previous response of this VLM and a feedback on either the state descriptor dictionary or a generated plan are provided OPTIONALLY.
            If the feedback is on the state descriptor JSON OR you think your previous response do not interpret the user instruction accurately,
            generate a new state descriptor JSON. Otherwise, JUST RETURN the previous state descriptor JSON without any changes.
            If the feedback is on the generated plan and you don't think it has anything to do with the goal state or constrinst you defined, you can ignore it and just return the previous state descriptor JSON.
            If the previous state descriptor JSON is not provided, you can generate a new state descriptor JSON.

            {JSON_EQUIVALENT_NOTE}
            For this JSON equivalent, the wrapped dictionary must be valid JSON with double-quoted keys and strings.
            For Tower of Hanoi, the StateDescriptor output has a strict benchmark contract:
            - goal_spatial_relations must contain every ring in the final target stack.
            - constraint_spatial_relations must include the global Hanoi action constraints under "<all_rings>".
            - The required constraints are exactly:
              1. Move one ring at a time
              2. Only move the top ring of a peg
              3. Never place a larger ring on top of a smaller ring
            - These procedural constraint strings are valid for this JSON equivalent, even though they are not spatial predicates.

            REQUIRED_STATE_DESCRIPTOR_JSON:
            {as_json(expected_state)}

            Now, solve the following task:
            User Instruction: {task.instruction}
            Scene Description JSON: {as_json(scene_json)}
            Previous state description JSON: {previous_state_output}
            Previous feedback: {feedback}

            Make sure to wrap the entire JSON definition for both dictionary within a ```start_flag and ```end_flag for parsing purposes.
            For this benchmark, the wrapped JSON should match REQUIRED_STATE_DESCRIPTOR_JSON unless the current task specification differs.

BENCHMARK JSON EQUIVALENT TASK_SPEC_JSON:
{task_spec_for_prompt(task)}
""".strip()


def build_decision_prompt(
    task: FlatHanoiTask,
    scene_json: Dict[str, object],
    state_output: str,
    h1_output: str,
    h2_output: str,
    feedback: str = "",
) -> str:
    inner_feedback, outer_feedback = split_framework_feedback(feedback)
    return f"""
            This is the task that we want to perform: (Look carefully at the user instruction and constraints)
            {task.instruction}

            Divide the task into subtasks and generate a goal state dictionary for each subtask, then use the H2 and H1 level action function(s)
            to plan this task. Give the result as a sequence of function calls.
            It is important that in your subtasks, you mention all objects explicity and not in any vague terminology.
            Also, try your best to include more than one function call in each subtask, if possible, to make the plan more efficient, unless the entire plan has only one call.
            However, try to come up with a plan that uses fewest number of function calls to achieve the goal state.
            If after two to three rounds of planning, you are not able to generate a plan that satisfies goal state and contraints, you MUST generate a plan regardless of that.
            Hint: If you don't know how to solve the task, you can reduce it to a problem you know and try to solve that problem but remember your ultimate goal is to solve the given task.

            Example: Output should be like this:

            For each subtask, print:
            - Subtask's description
            - Subtask's goal state dictionary
            - Call(s) to complete the subtask

            Then, finally, give the sequence of all H2/H1 function calls together like this:

            FunctionA()
            FunctionB()
            .
            .
            .

            Do not output any parameter in the format "<object_black>" or similar. Strictly refer to them of the format of "object_black".

            CRITICAL: When calling functions, you MUST substitute the actual peg names from the scene description (e.g., "green_peg", "red_peg", "blue_peg") as arguments.
            Do NOT pass abstract parameter placeholder names from the function signatures.
            Every argument in every function call must be a concrete object name that exists in the scene.

            You MUST follow the above output format and do not put any additional text or explanation in the output.

            In the state description, the state objects are ordered bottom-up, left-to-right order.

            Please remember when generating goal state JSON for each subtask, you match the structure with all objects in scene as down in scene JSON representation shown.

            Assume that the given scene and state description JSON are for the current state of the scene and any planning must happen relative to this given input description.

            Here is the scene description JSON that shows the objects in the scene:

            {as_json(scene_json)}

            Here is the state description JSON that shows the constraints on objects' relative positions:

            {state_output}

            Here are the H1 level functions:

            {h1_output}

            Here are the H2 level functions:

            {h2_output}

            Here is the feedback given by the InnerBot Verifier from previous plan generation:

            {inner_feedback}

            Here is the feedback given by the OuterBot Verifier from previous plan generation:

            {outer_feedback}

            Wrap the sequence of all function calls in ```start_all_functions and ```end_all_functions flags.

            Wrap each of the subtasks in ```start_subtask_{{num}} and ```end_subtask_{{num}} flags.

            Wrap each of the subtasks goal states in ```start_subtask_goalstate_{{num}} and ```end_subtask_goalstate_{{num}} flags.

            Wrap each of the subtasks function calls in ```start_subtask_funcs_{{num}} and ```end_subtask_funcs_{{num}} flags.

            {JSON_EQUIVALENT_NOTE}
            In this JSON equivalent, the concrete peg names are: {", ".join(task.pegs)}.

BENCHMARK JSON EQUIVALENT TASK_SPEC_JSON:
{task_spec_for_prompt(task)}
""".strip()


def build_innerbot_direct_plan_prompt(
    task: FlatHanoiTask,
    scene_json: Dict[str, object],
    current_state: Dict[str, List[str]],
    direct_output: str,
) -> str:
    return f"""
            Prompt for inner bot:

            You are misjudgement robot, and your main job is to determine whether the given direct robot action function calls are correct in the current environment.
            Add a field in your response called RESULT: and if the direct plan is correct, reply with YES. If it is incorrect, reply
            with NO and have a field called REASON: and give your reason. If the plan is correct, have the reason as N/A.
            Also, make sure to check that the functions used in the plan are logically correct by looking at the function definition provided.

            It is very important to wrap the RESULT within a ```start_result and ```end_result flag for parsing purposes.
            For example,
            ```start_result
            RESULT: ...
            REASON: ...
            ```end_result

            In addition, you will be given the current state JSON representation along with environment constraints for the task.

            Direct action function:
            MoveHoop(source_peg, target_peg): move the top ring from source_peg to target_peg.

            Rules:
            - Move one ring at a time.
            - Only move the top ring of a peg.
            - Never place a larger ring on top of a smaller ring.
            - Use only these peg names: {", ".join(task.pegs)}.

            Now, solve the task for the following information:
            Current State JSON: {as_json(scene_json)}
            Current symbolic stacks: {as_json(current_state)}
            Goal State natural language: {task.instruction}
            Goal State and constraints in JSON: {as_json(build_goal_description(task))}

            Direct Agent Plan with Function execution: {direct_output}

            {JSON_EQUIVALENT_NOTE}
""".strip()


def build_direct_hanoi_prompt(
    task: FlatHanoiTask,
    current_state: Dict[str, List[str]] | None = None,
    feedback: str = "",
) -> str:
    current_state = current_state or task.initial
    feedback_text = feedback or "N/A"
    return f"""
BENCHMARK DIRECT BASELINE:
This prompt is not from the Unity framework. It is the no-framework baseline for comparing a direct agent against the hierarchy pipeline.

Solve this Tower of Hanoi task directly as a standalone planning agent.

Do not create H1 functions.
Do not create H2 functions.
Do not describe a framework.
Only output the concrete move sequence needed to solve the task.

Allowed action:
MoveHoop(source_peg, target_peg): move the top ring from source_peg to target_peg.

Rules:
- Move one ring at a time.
- Only move the top ring of a peg.
- Never place a larger ring on top of a smaller ring.
- Use only these peg names: {", ".join(task.pegs)}.
- Use the fewest possible number of moves.

Current state:
{as_json(current_state)}

Previous verifier feedback:
{feedback_text}

Start from the current state above. If feedback is provided, correct the prior mistake and output a fresh complete move sequence from the current state to the goal.

TASK_SPEC_JSON:
{task_spec_for_prompt(task)}

Wrap the full move sequence exactly like this:
```start_all_functions
MoveHoop(peg_a, peg_c)
MoveHoop(peg_a, peg_b)
```end_all_functions
""".strip()
