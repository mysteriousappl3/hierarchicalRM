"""Prompts for the dynamic (n-level) hierarchy pipeline.

Three prompts replace the two-stage DecisionBot arrangement in prompts.py:

  build_plan_prompt              DecisionBot, planning only, emits no function calls
  build_hierarchy_planner_prompt composes H2..Hn from the plan and the H1 base action
  build_router_prompt            InnerBot as router: is there a mistake, and whose is it

Everything reuses the flag formats the existing parsers already understand
(start_mapping, start_subtask_funcs_N, start_result), so no new parsing
machinery is introduced. build_h1_prompt, build_state_prompt,
build_scene_description, build_goal_description and build_outerbot_prompt are
imported unchanged from prompts.py by the caller.
"""

from __future__ import annotations

from typing import Dict, Optional

from prompts import (
    JSON_EQUIVALENT_NOTE,
    as_json,
    build_goal_description,
    task_spec_for_prompt,
)
from task_loader import HanoiTask


# A deliberately domain-neutral nesting example. It teaches the mechanics of
# composing a level from the level below without revealing the recursive
# decomposition of Hanoi, which is the thing the benchmark is measuring.
NESTING_EXAMPLE = """
            BaseAction(x, y) = [H0_first(x), H0_second(), H0_third(y), H0_fourth()].
            Level2Action(x, y, z) = [BaseAction(x, y), BaseAction(y, z)].
            Level3Action(x, y, z) = [Level2Action(x, y, z), BaseAction(z, x), Level2Action(y, z, x)].

            Level2Action is built only from BaseAction. Level3Action is built from
            Level2Action and BaseAction. There is no limit on how many levels you stack.
""".strip()

RECURSION_NOTE = """
            A function must never call itself, and two functions must never call each other.
            This notation has no arithmetic, no conditionals, and no base case, so a
            self-referential definition cannot terminate and will be rejected.
            To express a repeating structure, define a separate numbered function per
            level, where each one is written in terms of the level below it.
""".strip()


def build_plan_prompt(
    task: HanoiTask,
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
    task: HanoiTask,
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


def build_router_prompt(
    task: HanoiTask,
    scene_json: Dict[str, object],
    state_output: str,
    plan_output: str,
    hierarchy_output: str,
    symbolic_reason: str = "",
    execution_feedback: str = "",
) -> str:
    """InnerBot as router: is there a mistake, and which component owns it.

    Used at both entry points. Before execution, symbolic_reason carries any
    deterministic validation failure. After execution, execution_feedback
    carries the OuterBot's finding and the bot re-diagnoses whether the plan or
    the hierarchy was at fault.

    The router is only ever invoked once symbolic validation has passed, so the
    prompt states what is already machine-verified. Without that, the router
    re-checks the expansion itself and reports false positives, most commonly
    claiming that a hierarchy bottoming out in an H1 function is not executable.
    """
    expected_state = build_goal_description(task)
    return f"""
            Prompt for inner bot:

            You are misjudgement robot. Two components produced the material below.

            The planner produced a plan: a list of subtasks in natural language with the goal
            state expected after each one. The planner does not produce actions.

            The hierarchy planner produced hierarchical action definitions and the calls that
            carry out each subtask of that plan.

            The benchmark harness has ALREADY verified the following mechanically.
            Do not re-check any of it and do not report any of it as a mistake:

            - Every function used in the calls resolves through the lower levels of the
              hierarchy down to the executable H0 primitives. Nothing is undefined.
            - A function that bottoms out in an H1 function is fully executable, because the
              H1 function is itself defined as a sequence of H0 primitives. This is correct
              and complete. It is NOT a missing decomposition.
            - The fully expanded sequence of primitives has been simulated and every
              resulting move is legal in the current state under the environment constraints.

            Your job is to decide three things, and only these three:

            1. Is there a mistake at all?
            2. If there is, which component must fix it?
            3. What exactly went wrong?

            Judge meaning, not mechanics: does the plan actually reach the user's goal, and
            do the hierarchical actions actually carry out that plan?

            Use these rules to decide who owns the mistake:

            - DecisionBot: the plan itself is wrong. The subtasks or their goal states do not
              lead to the user's goal, violate the environment constraints, or skip something
              required. The hierarchy may be a faithful realisation of a bad plan.
            - HierarchyPlanner: the plan is correct, but the hierarchical actions or the calls
              do not carry it out. Wrong composition, wrong arguments, wrong ordering, calls that
              do not reach the subtask goal state, or definitions that are not logically sound.
            - both: the plan is wrong AND the hierarchy has faults of its own that would remain
              after the plan is corrected.

            Judge the plan and the hierarchy separately before you decide. Do not blame the
            hierarchy for faithfully carrying out a bad plan, and do not blame the plan when the
            subtasks are sound but the actions are wrong.

            Add a field called RESULT: and reply YES if there is no mistake, or NO if there is.
            Add a field called OWNER: and reply with exactly one of DecisionBot, HierarchyPlanner,
            or both. If RESULT is YES, reply with NA.
            Add a field called REASON: and give your reason in 3 to 4 sentences. If RESULT is YES,
            reply with N/A.

            It is very important to wrap the result within a ```start_result and ```end_result flag
            for parsing purposes.
            For example,
            ```start_result
            RESULT: ...
            OWNER: ...
            REASON: ...
            ```end_result

            Now, solve the task for the following information:
            Current State: {as_json(scene_json)}
            Goal State natural language: {task.instruction}
            Goal State and constraints in JSON: {state_output}

            Planner plan with subtasks and goal states:
            {plan_output}

            Hierarchy planner definitions and subtask calls:
            {hierarchy_output}

            Deterministic validation result from the benchmark harness:
            {symbolic_reason or "N/A"}

            Feedback from execution and the OuterBot verifier:
            {execution_feedback or "N/A"}

            {JSON_EQUIVALENT_NOTE}

            EXPECTED_STATE_DESCRIPTOR_JSON:
            {as_json(expected_state)}
""".strip()
