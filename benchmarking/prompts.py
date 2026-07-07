from __future__ import annotations

import json
from typing import Dict, List

from task_loader import HanoiTask


H0_ACTIONS_DESCRIPTION = """
            MoveCoroutine(reachable_object): Move robot arm above 'REACHABLE' input object. Objects not reachable cannot be passed as input.
            GrabCoroutine(): Pick up top 'GRABBABLE' object below current position. Objects not GRABBABLE cannot be passed as input.
            DropCoroutine(): Drop picked up object at current position.
            PushCoroutine(final_dest): Push object at current position to specified position.
            RollCoroutine(direction): Roll object at current position in specified direction.
            CutCoroutine(): Cut top object below current position.
""".strip()

PREDICATES_DESCRIPTION = (
    "Here are the predicates to be used: [in(), above()].\n"
    "For example, 'in(<obj_1>)' indicates that an object is in obj_1 and "
    "'above(<obj_2>)' means an object is DIRECTLY above obj_2 and there are no objects between them."
)

JSON_EQUIVALENT_NOTE = """
BENCHMARK JSON EQUIVALENT:
This Python benchmark does not pass camera images to a VLM. The SceneDescriptor output below is the symbolic JSON equivalent of the Unity scene descriptor for the current Hanoi state.
For Hanoi execution in this Python harness, only MoveCoroutine, GrabCoroutine, and DropCoroutine are executable H0 primitives.
""".strip()


def as_json(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def build_scene_description(task: HanoiTask, state: Dict[str, List[str]] | None = None) -> Dict[str, object]:
    state = state or task.initial
    objects = [f"<{peg}>" for peg in task.pegs] + [f"<{ring.name}>" for ring in task.rings]
    object_properties: Dict[str, List[str]] = {}
    spatial_relations: Dict[str, List[str]] = {}

    for peg in task.pegs:
        object_properties[f"<{peg}>"] = ["REACHABLE"]
        spatial_relations[f"<{peg}>"] = []

    for ring in task.rings:
        object_properties[f"<{ring.name}>"] = ["GRABBABLE", ring.label]

    for peg, stack in state.items():
        for idx, ring in enumerate(stack):
            relations = [f"in(<{peg}>)"]
            if idx > 0:
                relations.append(f"above(<{stack[idx - 1]}>)")
            spatial_relations[f"<{ring}>"] = relations

    return {
        "objects": objects,
        "object_properties": object_properties,
        "spatial_relations": spatial_relations,
        "your_explanation": "Benchmark-provided symbolic Hanoi state; no image extraction was used.",
    }


def build_goal_description(task: HanoiTask) -> Dict[str, object]:
    goal_relations: Dict[str, List[str]] = {}
    for peg, stack in task.goal.items():
        for idx, ring in enumerate(stack):
            relations = [f"in(<{peg}>)"]
            if idx > 0:
                relations.append(f"above(<{stack[idx - 1]}>)")
            goal_relations[f"<{ring}>"] = relations

    return {
        "goal_spatial_relations": goal_relations,
        "constraint_spatial_relations": {
            "<all_rings>": [
                "Move one ring at a time",
                "Only move the top ring of a peg",
                "Never place a larger ring on top of a smaller ring",
            ]
        },
    }


def task_spec_for_prompt(task: HanoiTask) -> str:
    raw = {
        "id": task.id,
        "pegs": task.pegs,
        "source_peg": task.source_peg,
        "auxiliary_peg": task.auxiliary_peg,
        "target_peg": task.target_peg,
        "rings": [ring.__dict__ for ring in task.rings],
        "initial": task.initial,
        "goal": task.goal,
        "instruction": task.instruction,
    }
    return as_json(raw)


def build_state_prompt(
    task: HanoiTask,
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


def build_h1_prompt(scene_json: Dict[str, object]) -> str:
    return f"""
            We define a H0 level of robot control functions. These include the following:
            {H0_ACTIONS_DESCRIPTION}

            Here is the scene description for a task in JSON format.

            {as_json(scene_json)}

            Single State Change: For this scene, we consider moving a hoop from one pillar to another as a state change.

            An H1 level function is one that is composed of a sequence of H0 level functions.
            Come up with H1 level function(s) that represent a single state change for this scene.
            Provide code in C# that should only include calls to H0 level functions.
            Ensure you also add a docstring for each of the function you generate with details on what the function does and what each parameter means clearly.
            These functions should be generic, i.e., should not specify any specific scene object.
            Any input to H0 level functions should be input to the H1 function using them.
            Remove any input to H1 level function(s) that doesn't get used in H0 level function(s).

            For this benchmark, generate exactly one H1 function with this exact signature:
            MoveSingleRing(source_peg, target_peg)
            This is the only H1 function that later H2 functions are allowed to call.

            Make sure to wrap all the function definitions within a ```start_flag and ```end_flag for parsing purposes.
            Only give the function definition without wrapping it inside any class and assume H0 functions have already been defined.
            Assume the functions take string inputs.

            Additionally, make sure to represent each H1 function to its sequence of H0 functions with its parameters as comma separated of the format.
            If multiple function definitions exit, repsent each mapping by comma separated. Only include the function signature and any parameters as strings in this.
            The format is given below:

            H1_function() = [H0_func1(), H0_func2(), H0_func3()].

            It is important to remember that in the function call signature, any parameters that are not used in the function should be removed.
            Do NOT include any type for parameters, just the parameter names as strings, where each parameter is ONE SINGLE string in the function signature.

            Wrap ALL the functions generated by comma separated in tag ```start_mapping and ```end_mapping flags for parsing purposes.
            It it important that all the generated functions should come inside a single ```start_mapping and ```end_mapping flag being commma separated
            instead of each function having its own flag.

            {JSON_EQUIVALENT_NOTE}
""".strip()


def build_h2_prompt(scene_json: Dict[str, object], h1_output: str) -> str:
    return f"""
            Here is the scene description for a task in JSON format.

            {as_json(scene_json)}

            Here are the H1 level function(s):

            {h1_output}

            We plan to use VLMs for long-horizon planning of complex tasks and thus want to come up with another higher hierarchy of function(s) to potentially shorten the number of function steps the planner has to use for completing a complex task.

            H2 level functions are ones that are composed of a sequence of H1 level function(s).
            Come up with this H2 hierarchy of function(s) in C# that do more complex operations for the kind of objects in the scene than the H1 level functions.
            Provide code where the body of any H2 function should only include calls to H1 level function(s).
            Ensure you also add a docstring for each of the function you generate with details on what the function does and what each parameter means clearly.
            These functions should be generic, i.e., should not specify any specific scene object.
            You are not allowed to create any helper functions or assume or define any variables in the function body. Add as input anything you think is needed.

            Allowed H1 functions are exactly:
            - MoveSingleRing(source_peg, target_peg)

            Every H2 function body and mapping must call only MoveSingleRing with exactly two arguments in that order.
            Do not call H0 functions from H2.
            Do not call other H2 functions from H2.
            Do not invent helper functions, loops, recursion, conditionals, variables, or pseudocode.

            Generate as many H2 functions as you can, but ensure each function is meaningful and logically correct.
            By meaningful, make sure every H2 function has a clear purpose and is not just a combination of H1 functions without a logical flow.
            Also, do NOT create H2 functions that repeat calling the same H1 function with the same parameters.

            Make sure to wrap all the function definitions within a ```start_flag and ```end_flag for parsing purposes.
            Only give the function definition without wrapping it inside any class.
            Assume the functions take string inputs.

            Additionally, make sure to represent each H2 function to its sequence of H1 functions with its parameters as comma separated of the format.
            If multiple function definitions exit, repsent each mapping by comma separated. Only include the function signature and any parameters as strings in this.
            The format is given below:

            H2_function() = [H1_func1(), H1_func2(), H1_func3()].

            It is important to remember that in the function call signature, any parameters that are not used in the function should be removed.
            Also, ensure the H1 functions called have the correct parameters as specified in the H1 function signatures.

            Wrap all the mapping comma separated in tag ```start_mapping and ```end_mapping flags for parsing purposes.

            {JSON_EQUIVALENT_NOTE}
""".strip()


def build_decision_prompt(
    task: HanoiTask,
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


def build_innerbot_state_prompt(task: HanoiTask, scene_json: Dict[str, object], state_output: str) -> str:
    expected_state = build_goal_description(task)
    return f"""

            You are misjudgement robot, and you need to:
                Given the user instruction in natural language, check that the given goal state and constraints match the intention of the user instruction.
                For constraints, make sure following them in any state does not result in the user instruction being violated.
                If the goal state and/or constraints do not satisfy the user instruction, you must reply with NO and describe the reason behind in 3 to 4 sentences.
                Assume current state given does not violate any rules or constraints in the user instruction.

            Add a field in your response called RESULT: and if the job are correct, reply with YES. If the job is incorrect, reply
            with NO and have a field called REASON: and give your reason which should be 3 to 4 sentences. If the job is correct, have the reason as N/A.

            It is very important to wrap the RESULT within a ```start_result and ```end_result flag for parsing purposes.
            For example,
            ```start_result
            RESULT: ...
            REASON: ...
            ```end_result

            Now, solve the task for the following information:
            Current state: {as_json(scene_json)}
            Goal State natural language: {task.instruction}
            Goal State and constraints in JSON: {state_output}

            {JSON_EQUIVALENT_NOTE}
            For this Tower of Hanoi JSON equivalent, the following procedural constraints under "<all_rings>" are required and sufficient:
            - Move one ring at a time
            - Only move the top ring of a peg
            - Never place a larger ring on top of a smaller ring

            EXPECTED_STATE_DESCRIPTOR_JSON:
            {as_json(expected_state)}
""".strip()


def build_innerbot_plan_prompt(
    task: HanoiTask,
    scene_json: Dict[str, object],
    state_output: str,
    h1_output: str,
    h2_output: str,
    decision_output: str,
) -> str:
    return f"""
            Prompt for inner bot:

            You are misjudgement robot, and your main job is to determine whether the given subtasks in natural language and
            their sequence of robot action function calls passed from Decision Bot are correct in the current environment.
            Add a field in your response called RESULT: and if the subtasks are correct, reply with YES. If they are incorrect, reply
            with NO and have a field called REASON: and give your reason. If the plan is correct, have the reason as N/A.
            Also, make sure to check that the functions used in the plan are logically correct by looking at the function definitions provided.

            It is very important to wrap the RESULT within a ```start_result and ```end_result flag for parsing purposes.
            For example,
            ```start_result
            RESULT: ...
            REASON: ...
            ```end_result

            In addition, you will be given the current state JSON representation along with environment constraints for the task.
            You will also be given the function definitions at hierarchy level H2 and then at a lower level of H1 which are composed of the primitive
            actions of H0.

            Now, solve the task for the following information:
            Current State: {as_json(scene_json)}
            Goal State natural language: {task.instruction}
            Goal State and constraints in JSON: {state_output}

            H1 Functions: {h1_output}
            H2 Functions: {h2_output}

            Decision Bot Plan with Subtasks and Function execution: {decision_output}

            {JSON_EQUIVALENT_NOTE}
""".strip()


def build_innerbot_direct_plan_prompt(
    task: HanoiTask,
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


def build_outerbot_prompt(
    task: HanoiTask,
    env_constraint: object,
    subtask_nl: str,
    prev_state: object,
    curr_state: object,
    subtask_goal_state: object,
    final_goal_state: object,
) -> str:
    return f"""
            You are a vision language model that detects execution errors in subtask execution.
            You must reason about how objects move between previous and current state as a result of the specified subtask requirement.
            Based on this change of state information, determine which of the following error types the response falls under.
            Note that goal state refers to the expected state after ALL actions have been executed, not just the current action.
            The definitions are given below:

            Definitions:
            - TASK SUCCESS: current state == final goal state or equivalent representation.
                            You must output this when final subtask goal state is reached given that it is equivalent to the goal state.
            - SUBTASK SUCCESS: current state == subtask goal state or equivalent representation.
            - EXECUTE REMAINING ACTIONS: valid intermediate state but final goal state or subtask goal state not reached.
            - RECOVERABLE: Valid scene representation but subtask goal state not reached.
            - NON-RECOVERABLE: Major scene representation error or environment constraint violated. Requires human intervention.

            State terms:
            - prev state = scene just before executing subtask.
            - curr state = scene immediately after executing subtask.
            - Refer only to JSON keys, for example `<object_pink>`.

            Remember that the color of the objects defined in the goal state is what the environment contains.
            If you observe similar looking colours between current state and previous state when compared to the goal state,
            assume they refer to the same object and state this assumption in your reason.

            Wrap your answer exactly as below including the quotation mark:

            ```start_error_type
            Error : <TASK SUCCESS | SUBTASK SUCCESS | EXECUTE REMAINING ACTIONS | RECOVERABLE | NON-RECOVERABLE>
            Reason : <brief explanation>
            ```end_error_type

            Now solve for the following task information:

            Environment Constraint : {as_json(env_constraint)}

            Subtask Requirement : {subtask_nl}

            prev_state before subtask execution: {as_json(prev_state)}

            curr_state after subtask execution : {as_json(curr_state)}

            subtask_goal_state : {as_json(subtask_goal_state)}

            final_goal_state : {as_json(final_goal_state)}

            {JSON_EQUIVALENT_NOTE}

            User Instruction: {task.instruction}
""".strip()


def split_framework_feedback(feedback: str) -> tuple[str, str]:
    if not feedback:
        return "N/A", "N/A"
    if "outerbot" in feedback.lower():
        return "N/A", feedback
    return feedback, "N/A"


def build_direct_hanoi_prompt(
    task: HanoiTask,
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
