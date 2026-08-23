# Tower of Hanoi Benchmark Details

This document describes the text-only Tower of Hanoi benchmark, its prompts and JSON state, its verification flow, and the four model conditions used for comparison. Unity, camera images, and robot physics are not used here. The Python simulator is the authoritative environment.

## Task Setup

Task fixtures are stored in `benchmarking/tasks/hanoi_N.json`. Each fixture defines:

- Peg names.
- Ring names, sizes, and labels.
- Source, auxiliary, and target pegs.
- Initial and goal states.
- The natural-language instruction.

For `hanoi_3`:

```json
{
  "id": "hanoi_3",
  "pegs": ["peg_a", "peg_b", "peg_c"],
  "source_peg": "peg_a",
  "auxiliary_peg": "peg_b",
  "target_peg": "peg_c",
  "initial": {
    "peg_a": ["ring_3", "ring_2", "ring_1"],
    "peg_b": [],
    "peg_c": []
  },
  "goal": {
    "peg_a": [],
    "peg_b": [],
    "peg_c": ["ring_3", "ring_2", "ring_1"]
  }
}
```

Stack arrays are ordered **bottom to top**. The last ring in an array is the movable top ring. Complexity is the number of rings, and the optimal number of moves is `2^N - 1`.

## Rules and Success

Every executed move must satisfy:

1. Move exactly one ring.
2. Move only the top ring of a peg.
3. Never place a larger ring on a smaller ring.
4. Use only the three configured peg names.

Success requires a legal sequence whose final state exactly equals the fixture goal. The scorer separately records whether the successful sequence is optimal.

The deterministic simulator checks every primitive move before changing the state. It reports the first illegal move and keeps the state reached before that error.

## JSON State Representations

### Authoritative simulator state

The simulator stores the current state as peg-to-stack arrays:

```json
{
  "peg_a": ["ring_3", "ring_2", "ring_1"],
  "peg_b": [],
  "peg_c": []
}
```

This is the state passed directly to the base planner. It is also rebuilt after every executed subtask or partial replan.

### SceneDescriptor equivalent

Hierarchy modes convert the authoritative state into the symbolic JSON equivalent of the Unity SceneDescriptor:

```json
{
  "objects": [
    "<peg_a>", "<peg_b>", "<peg_c>",
    "<ring_1>", "<ring_2>", "<ring_3>"
  ],
  "object_properties": {
    "<peg_a>": ["REACHABLE"],
    "<peg_b>": ["REACHABLE"],
    "<peg_c>": ["REACHABLE"],
    "<ring_1>": ["GRABBABLE", "smallest"],
    "<ring_2>": ["GRABBABLE", "middle"],
    "<ring_3>": ["GRABBABLE", "largest"]
  },
  "spatial_relations": {
    "<peg_a>": [],
    "<peg_b>": [],
    "<peg_c>": [],
    "<ring_3>": ["in(<peg_a>)"],
    "<ring_2>": ["in(<peg_a>)", "above(<ring_3>)"],
    "<ring_1>": ["in(<peg_a>)", "above(<ring_2>)"]
  }
}
```

### StateDescriptor output

The StateDescriptor model receives the current scene, task instruction, previous descriptor, and feedback. It returns goal relations and persistent constraints:

```json
{
  "goal_spatial_relations": {
    "<ring_3>": ["in(<peg_c>)"],
    "<ring_2>": ["in(<peg_c>)", "above(<ring_3>)"],
    "<ring_1>": ["in(<peg_c>)", "above(<ring_2>)"]
  },
  "constraint_spatial_relations": {
    "<all_rings>": [
      "Move one ring at a time",
      "Only move the top ring of a peg",
      "Never place a larger ring on top of a smaller ring"
    ]
  }
}
```

The current prompt includes this expected value as `REQUIRED_STATE_DESCRIPTOR_JSON`. This stage therefore reformats and verifies the known goal rather than discovering an unknown goal. `--fixed-goal` bypasses model generation and injects this deterministic descriptor.

## Prompt Contracts

### Direct planning prompt

The base planner receives the current peg stacks, the complete task fixture, the movement rules, and optional feedback. The essential prompt is:

```text
Solve this Tower of Hanoi task directly as a standalone planning agent.

Do not create H1 functions.
Do not create H2 functions.
Only output the concrete move sequence needed to solve the task.

Allowed action:
MoveHoop(source_peg, target_peg)

Rules:
- Move one ring at a time.
- Only move the top ring of a peg.
- Never place a larger ring on top of a smaller ring.
- Use only the supplied peg names.
- Use the fewest possible number of moves.
```

The response contract is:

````text
```start_all_functions
MoveHoop(peg_a, peg_c)
MoveHoop(peg_a, peg_b)
...
```end_all_functions
````

The prompt provides the rules but does not provide the recursive Hanoi solution algorithm.

### Framework planning prompts

The hierarchy pipeline uses separate model roles:

| Stage | Inputs | Required output |
|---|---|---|
| StateDescriptor | Scene JSON, instruction, previous descriptor, feedback | Goal and constraint JSON |
| H1 generator | Scene JSON and H0 descriptions | Exact H1 mapping |
| H2 generator | Scene JSON and H1 mapping | H2 mappings composed only from H1 |
| Fixed DecisionBot | Instruction, scene, StateDescriptor, H1/H2 mappings, feedback | Subtasks and concrete H2/H1 calls |
| N-level DecisionBot | Instruction, scene, StateDescriptor, feedback | Natural-language subtasks and complete goal states only |
| N-level HierarchyPlanner | DecisionBot plan, scene, H1, constraints | Finite H2-through-Hn mappings and dispatch calls |
| InnerBot router | Plan, hierarchy, current state, deterministic summary | Verdict and error owner |
| OuterBot | Before/after state, subtask goal, final goal, constraints | Execution status |

## H0, H1, and H2 Actions

### H0 robot-style primitives

The hierarchy prompt exposes these H0 descriptions, but only three are executable in the JSON benchmark:

```text
MoveCoroutine(reachable_object)
GrabCoroutine()
DropCoroutine()
```

### Fixed H1 action

H1 represents one semantic ring transfer. It intentionally uses only source and target pegs; the top ring is determined by the environment state.

```text
MoveSingleRing(source_peg, target_peg) = [
  MoveCoroutine(source_peg),
  GrabCoroutine(),
  MoveCoroutine(target_peg),
  DropCoroutine()
]
```

### Example H2 action

An H2 function can compose multiple H1 calls:

```text
MoveTwoRingTower(source_peg, auxiliary_peg, target_peg) = [
  MoveSingleRing(source_peg, auxiliary_peg),
  MoveSingleRing(source_peg, target_peg),
  MoveSingleRing(auxiliary_peg, target_peg)
]
```

H2 may call only the exact H1 function with two arguments. It may not call H0 directly, call another H2 function, or use loops, recursion, conditionals, helper functions, or omitted steps.

### Example N-level composition

The dynamic hierarchy can build higher finite compositions:

```text
MoveThreeRingTower(source_peg, auxiliary_peg, target_peg) = [
  MoveTwoRingTower(source_peg, target_peg, auxiliary_peg),
  MoveSingleRing(source_peg, target_peg),
  MoveTwoRingTower(auxiliary_peg, source_peg, target_peg)
]
```

This is H3 because it calls an H2 function. The dynamic benchmark uses explicit finite mappings rather than executable recursion or loops.

## InnerBot and OuterBot

### InnerBot state verification

InnerBot receives the current SceneDescriptor, natural-language instruction, and proposed StateDescriptor. It checks whether the goal relations and persistent constraints match the task. It returns `RESULT: YES/NO` and a reason.

### InnerBot plan verification

Before execution, the benchmark first parses and expands the proposed hierarchy deterministically. It verifies known function names, hierarchy mappings, H0 expansion, move legality, and projected state transitions. When that symbolic validation passes, the LLM InnerBot checks the semantic plan and function definitions.

For the N-level condition, InnerBot also acts as a router. A rejected plan is attributed to `DecisionBot`, `HierarchyPlanner`, or `both`, determining which artifacts are regenerated.

### OuterBot execution verification

After a subtask executes, OuterBot receives:

- The state before execution.
- The observed state after execution.
- The expected subtask state.
- The final goal.
- Environment constraints.

It returns one of `TASK SUCCESS`, `SUBTASK SUCCESS`, `EXECUTE REMAINING ACTIONS`, `RECOVERABLE`, or `NON-RECOVERABLE`. Recoverable errors produce feedback and a replan from the actual current symbolic state.

LLM verifier verdicts do not replace deterministic scoring. A plan is successful only if deterministic execution is legal and reaches the exact goal.

## Comparison Conditions

### 1. Base model

```powershell
python benchmarking\hanoi_benchmark.py --task hanoi_5 --provider openai --model MODEL --reasoning low --no-framework
```

Pipeline:

```text
current peg stacks -> direct MoveHoop planner -> deterministic simulation -> score
```

There is one planner call, no StateDescriptor, no hierarchy, and no LLM verifier.

### 2. Base model plus Inner/Outer

```powershell
python benchmarking\hanoi_benchmark.py --task hanoi_5 --provider openai --model MODEL --reasoning low --no-framework --inner-outer
```

Pipeline:

```text
current peg stacks -> direct MoveHoop planner -> deterministic check
-> LLM InnerBot -> symbolic execution -> LLM OuterBot -> feedback replan
```

The first direct-planner prompt is the same as the base condition. This condition adds verification and repeated correction but no H1/H2 hierarchy.

### 3. Fixed H1/H2 plus Inner/Outer

```powershell
python benchmarking\hanoi_benchmark.py --task hanoi_5 --provider openai --model MODEL --reasoning low
```

Pipeline:

```text
SceneDescriptor -> StateDescriptor -> InnerBot state check
-> H1 generator -> H2 generator -> DecisionBot
-> deterministic hierarchy expansion -> InnerBot plan check
-> symbolic H0 execution -> OuterBot -> feedback replan
```

The maximum hierarchy depth is fixed at H2. DecisionBot plans with the generated H2/H1 actions.

### 4. N-level hierarchy plus Inner/Outer

```powershell
python benchmarking\dynamic_hierarchy_benchmark.py --task hanoi_5 --provider openai --model MODEL --reasoning low
```

Pipeline:

```text
SceneDescriptor -> StateDescriptor -> InnerBot state check
-> plan-only DecisionBot -> dynamic HierarchyPlanner
-> static graph and symbolic execution checks -> InnerBot router
-> symbolic H0 execution -> OuterBot -> selective replan
```

DecisionBot describes what each subtask must achieve. HierarchyPlanner separately chooses useful H2-through-Hn functions and their calls. The router can retain a valid DecisionBot plan when only the hierarchy is wrong.

## Results

Every run records structured metrics and steps under `benchmarking/results/<model>/<mode>/...`. The output includes legality, exact success, optimality, first error, move count, H0/H1/H2/Hn call counts, model calls, replans, token usage, runtime, and raw stage outputs.

## Implementation Files

- `tasks/hanoi_3.json` through `tasks/hanoi_12.json`: task fixtures.
- `task_loader.py`: task loading and validation.
- `prompts.py`: direct, StateDescriptor, H1/H2, DecisionBot, InnerBot, and OuterBot prompts.
- `dynamic_prompts.py`: N-level DecisionBot, HierarchyPlanner, and router prompts.
- `scoring.py`: parsing, hierarchy expansion, move simulation, and scoring.
- `hanoi_benchmark.py`: base, Inner/Outer, and fixed H1/H2 runners.
- `dynamic_hierarchy_benchmark.py`: N-level runner.
