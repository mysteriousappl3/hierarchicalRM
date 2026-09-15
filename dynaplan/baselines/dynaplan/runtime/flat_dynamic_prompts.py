"""Prompts for the dynamic (n-level) hierarchy pipeline, flat-to-flat variant.

Mirrors dynamic_prompts.py. build_router_prompt is imported unchanged: it
never calls task_spec_for_prompt and references no source/auxiliary/target
peg field, so it is already flat-agnostic.

build_plan_prompt and build_hierarchy_planner_prompt are the two that leak
tower framing -- both call prompts.task_spec_for_prompt internally, which
emits source_peg/auxiliary_peg/target_peg. Their flat counterparts here are
otherwise byte-for-byte identical, but call flat_prompts.task_spec_for_prompt
instead, which omits those fields entirely.

NESTING_EXAMPLE and RECURSION_NOTE are reused verbatim from dynamic_prompts.py
-- NESTING_EXAMPLE is already deliberately domain-neutral by its own design
comment, precisely so it does not leak Hanoi's decomposition, tower or flat.
"""

from __future__ import annotations

from typing import Dict, Optional

from dynamic_prompts import NESTING_EXAMPLE, RECURSION_NOTE, build_router_prompt
from flat_hanoi_task_loader import FlatHanoiTask
from flat_prompts import task_spec_for_prompt
from prompts import JSON_EQUIVALENT_NOTE, as_json

__all__ = [
    "NESTING_EXAMPLE",
    "RECURSION_NOTE",
    "build_router_prompt",
    "build_plan_prompt",
    "build_hierarchy_planner_prompt",
]


def build_plan_prompt(
    task: FlatHanoiTask,
    scene_json: Dict[str, object],
    state_output: str,
    h1_output: str,
    feedback: str = "",
) -> str:
    """DecisionBot restricted to planning.

    The H1 actions are shown as a validity boundary only. The bot is given no
    composed actions to plan with, and is told explicitly not to emit calls, so
    its output is a plan rather than a solution.
    """
    return f"""
            This is the task that we want to perform: (Look carefully at the user instruction and constraints)
            {task.instruction}

            Your job is ONLY to plan. You must NOT solve the task.

            Divide the task into subtasks. For each subtask give:
            - A description in natural language.
            - A goal state dictionary describing the scene once that subtask is complete.

            It is important that in your subtasks, you mention all objects explicitly and not in any vague terminology.
            Subtasks should be checkpoints on the way to the final goal state, ordered so that
            completing them in sequence completes the task.

            Do NOT output any function calls.
            Do NOT output any sequence of actions.
            Do NOT output any code.
            A separate hierarchy planner will decide which actions achieve your subtasks.

            Below are the H0 and H1 level actions available in this environment.
            They are given to you as a validity boundary, NOT as building blocks.
            You do not need to use them and you must not call them. Their only purpose is to
            tell you what this environment can physically do, so that every subtask you invent
            is reachable by some sequence of these actions rather than being impossible.

            Here are the H1 level functions:

            {h1_output}

            In the state description, the state objects are ordered bottom-up, left-to-right order.

            Please remember when generating the goal state JSON for each subtask, you match the structure
            with all objects in scene as shown in the scene JSON representation.

            Assume that the given scene and state description JSON are for the current state of the scene
            and any planning must happen relative to this given input description.

            Here is the scene description JSON that shows the objects in the scene:

            {as_json(scene_json)}

            Here is the state description JSON that shows the constraints on objects' relative positions:

            {state_output}

            Here is the feedback from the previous planning round:

            {feedback or "N/A"}

            Wrap each of the subtask descriptions in ```start_subtask_{{num}} and ```end_subtask_{{num}} flags.

            Wrap each of the subtask goal states in ```start_subtask_goalstate_{{num}} and ```end_subtask_goalstate_{{num}} flags.

            Number the subtasks from 1 with no gaps.

            You MUST follow the above output format and do not put any additional text or explanation in the output.

            {JSON_EQUIVALENT_NOTE}
            In this JSON equivalent, the concrete peg names are: {", ".join(task.pegs)}.

BENCHMARK JSON EQUIVALENT TASK_SPEC_JSON:
{task_spec_for_prompt(task)}
""".strip()


def build_hierarchy_planner_prompt(
    task: FlatHanoiTask,
    scene_json: Dict[str, object],
    state_output: str,
    h1_output: str,
    plan_output: str,
    feedback: str = "",
    previous_hierarchies: Optional[str] = None,
    include_code_block: bool = True,
) -> str:
    """Composes H2..Hn from the plan, at whatever depth it judges useful.

    include_code_block keeps parity with the existing H1/H2 prompts, which ask
    for C# definitions alongside the mappings. Nothing parses that block, so it
    can be switched off as a token ablation.
    """
    code_block_section = (
        """
            Make sure to wrap all the function definitions within a ```start_flag and ```end_flag for parsing purposes.
            Only give the function definition without wrapping it inside any class.
            Assume the functions take string inputs.
"""
        if include_code_block
        else ""
    )
    previous_section = (
        f"""
            Here are hierarchical actions that were validated in an earlier round:

            {previous_hierarchies}

            You may reuse them unchanged, modify some of them, or discard them and start again.
            State which of those three you are doing and why before you give your output.
"""
        if previous_hierarchies
        else ""
    )

    return f"""
            Here is the scene description for a task in JSON format.

            {as_json(scene_json)}

            Here is the goal state and the constraints on this scene:

            {state_output}

            Here is the plan produced by the planner. It is a list of subtasks with the goal state
            expected after each one:

            {plan_output}

            Here are the H1 level function(s). These are the ONLY base actions you may build on:

            {h1_output}

            Your job is to build the hierarchy of actions that carries out this plan.

            An H2 level function is composed of a sequence of H1 level function(s).
            An H3 level function is composed of H2 and/or H1 level function(s).
            You may keep going: an H(n) level function may be composed of any function(s) at
            lower levels. There is no fixed number of levels. Decide how deep to go.

            This is the important part of the task. A flat list of H1 calls is almost always the
            wrong answer for a long task, because the sequence becomes too long to write correctly.
            Build higher level functions that capture repeated structure, then build functions on
            top of those, so the final plan is a small number of calls.

            Balance depth against breadth. Too flat and the plan is long and error prone.
            Too deep and each level stops being meaningful.

            Here is what nesting looks like:

            {NESTING_EXAMPLE}

            {RECURSION_NOTE}

            A single hierarchical action may cover one subtask or several subtasks. You decide.
            You do not have to produce one function per subtask.

            The plan may be wrong. That is not your concern. Build the hierarchy that carries out
            the plan you were given. A separate verifier decides whether the plan itself was correct.

            Rules for the function bodies:
            - Every function body must contain only calls to functions you have defined at a lower
              level, or to the H1 function(s) above.
            - Do not call H0 primitives directly from any function above H1.
            - Do not invent helper functions, loops, recursion, conditionals, variables, or pseudocode.
            - Remove any parameter that is not used in the body.
            - Functions must be generic. Use parameter names in the definitions, not concrete
              scene objects.
{code_block_section}{previous_section}
            Represent every function you define as a mapping from its signature to its sequence of
            lower level calls, comma separated, in this format:

            H2_function() = [H1_func1(), H1_func2()],
            H3_function() = [H2_function(), H1_func1()].

            Wrap ALL the mappings together inside a single ```start_mapping and ```end_mapping flag pair.

            Then give the calls that carry out each subtask of the plan, using the concrete object
            names from the scene. Wrap the calls for each subtask in
            ```start_subtask_funcs_{{num}} and ```end_subtask_funcs_{{num}} flags,
            numbered to match the subtask numbers in the plan.

            CRITICAL: When calling functions, you MUST substitute the actual peg names from the scene
            description (e.g. "green_peg", "red_peg", "blue_peg") as arguments.
            Do NOT pass abstract parameter placeholder names from the function signatures.
            Every argument in every call must be a concrete object name that exists in the scene.
            Do not output any parameter in the format "<object_black>" or similar. Strictly refer to
            them in the format "object_black".

            Here is the feedback from the previous round:

            {feedback or "N/A"}

            {JSON_EQUIVALENT_NOTE}
            In this JSON equivalent, the concrete peg names are: {", ".join(task.pegs)}.

BENCHMARK JSON EQUIVALENT TASK_SPEC_JSON:
{task_spec_for_prompt(task)}
""".strip()
