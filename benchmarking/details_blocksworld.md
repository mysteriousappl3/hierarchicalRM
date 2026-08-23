# Blocks World Benchmark Details

This document describes the text-only Blocks World benchmark, including task generation, prompts, JSON state, verification, and the four comparison conditions. The Python simulator is the authoritative environment; Unity and visual input are not involved.

## Task Setup

Blocks World contains three stacks and `N` uniquely named blocks. Complexity is primarily the number of blocks.

The paper-style task generator:

1. Creates blocks `A`, `B`, `C`, and so on.
2. Divides the blocks in alphabetical order across stacks `0` and `1`.
3. Leaves stack `2` empty as workspace.
4. Builds an interleaved target stack on stack `0`.

For `blocks_world_4`:

```json
{
  "task_id": "blocks_world_4",
  "initial": {
    "0": ["A", "B"],
    "1": ["C", "D"],
    "2": []
  },
  "goal": {
    "0": ["D", "B", "C", "A"],
    "1": [],
    "2": []
  }
}
```

Arrays are ordered **bottom to top**, so the last block in a stack is movable. Available paper-style sizes are `N = 2, 4, 6, 8, 10, 12, 16, 20, 24, 30, 36, 40`.

## Rules and Success

The only primitive operation is:

```text
MoveBlock(block, source_stack, target_stack)
```

A move is legal only when:

1. Source and target are known, different stacks.
2. The source stack is not empty.
3. The named block is the current top block of the source stack.

Any top block may be placed on an empty stack or another block. Unlike Hanoi, Blocks World has no block-size placement restriction.

Success requires a completely legal sequence whose final state exactly equals the goal. Optimality is reported separately. An exact breadth-first-search optimum is computed for `N <= 8`; larger tasks report no exact optimum.

## JSON State

The authoritative state is stored as a dictionary from stack ID to a bottom-to-top block array:

```json
{
  "0": ["A", "B"],
  "1": ["C", "D"],
  "2": []
}
```

Hierarchy conditions ask StateDescriptor to return:

```json
{
  "stack_order": "bottom_to_top",
  "current": {
    "0": ["A", "B"],
    "1": ["C", "D"],
    "2": []
  },
  "goal": {
    "0": ["D", "B", "C", "A"],
    "1": [],
    "2": []
  },
  "constraints": [
    "Only the top block of a stack may move",
    "Every move must name its block, source stack, and target stack"
  ]
}
```

The benchmark deterministically checks that `current` and `goal` exactly match the authoritative task and that every block occurs exactly once.

## Prompt Contracts

### Direct prompt

The base model receives the initial stacks, goal stacks, bottom-to-top convention, top-block rule, and request for a minimum move sequence. Its output is parsed as either paper-style moves or primitive calls:

```text
moves = [
  ["B", 0, 1],
  ["A", 0, 2],
  ...
]
```

Equivalent function-call output is:

```text
MoveBlock(B, 0, 1)
MoveBlock(A, 0, 2)
```

The prompt supplies the state, goal, rule, and output requirement but does not supply a solution algorithm.

### Framework prompts

| Stage | Inputs | Required output |
|---|---|---|
| StateDescriptor | Authoritative current and goal states, rules, feedback | Exact current/goal JSON and constraints |
| InnerBot state check | Authoritative state and proposed descriptor | `RESULT: YES/NO` with reason |
| H1 generator | StateDescriptor and action contract | Exact `MoveTopBlock` mapping |
| H2 generator | Current state, goal, descriptor, H1, feedback | H2 mappings composed only from H1 |
| Fixed DecisionBot | State, descriptor, H1/H2 mappings, feedback | Numbered concrete H2 calls |
| N-level DecisionBot | Current state, goal, descriptor, feedback | JSON subtasks with complete expected states |
| HierarchyPlanner | DecisionBot plan and task state | Structured H1-through-Hn functions and dispatch |
| InnerBot router | Plan, hierarchy, state, deterministic summary | Verdict and responsible component |
| OuterBot | Previous, observed, expected, and final states | Execution status |

## H0, H1, and H2 Actions

### H0 primitive

H0 is already a semantic environment operation:

```text
MoveBlock(block, source_stack, target_stack)
```

There is no robot-arm motion layer in this JSON benchmark.

### Fixed H1 action

H1 wraps exactly one legal semantic block move:

```text
MoveTopBlock(block, source_stack, target_stack) = [
  MoveBlock(block, source_stack, target_stack)
]
```

### Example fixed H2 actions

For `blocks_world_4`, the model could define:

```text
ClearInitialStack() = [
  MoveTopBlock(B, 0, 1),
  MoveTopBlock(A, 0, 2),
  MoveTopBlock(B, 1, 2)
]

AssembleGoalStack() = [
  MoveTopBlock(D, 1, 0),
  MoveTopBlock(B, 2, 0),
  MoveTopBlock(C, 1, 0),
  MoveTopBlock(A, 2, 0)
]
```

Each H2 function contains only H1 calls. DecisionBot could solve the task by calling `ClearInitialStack()` and then `AssembleGoalStack()`.

### Example N-level action

The dynamic hierarchy could add:

```text
SolveFourBlockRearrangement() = [
  ClearInitialStack(),
  AssembleGoalStack()
]
```

This function is H3 because it calls H2 functions. Higher functions must call only known lower-level functions. The compiler rejects cycles, unknown calls, incorrect levels, bad arity, unbound parameters, non-concrete dispatch arguments, direct H0 calls above H1, and one-call wrappers that add depth without reuse or compression.

## InnerBot and OuterBot

### InnerBot state verification

The state verifier compares the model-generated StateDescriptor with the authoritative current state and goal. Both the deterministic checker and the LLM verifier must accept it before hierarchy generation continues.

### InnerBot plan verification

For `inner-outer` and fixed H1/H2 conditions, the benchmark:

1. Parses the proposed plan.
2. Deterministically simulates every primitive move.
3. Builds a validation summary.
4. Sends the proposal and summary to the LLM InnerBot.

A deterministic failure cannot be overridden by an LLM `YES` verdict.

### N-level router

The complete framework separates DecisionBot's subtask plan from HierarchyPlanner's implementation. The static compiler first checks structure and expansion. InnerBot then judges semantic agreement and can assign a mistake to:

- `DecisionBot`: the subtask plan or expected states are wrong.
- `HierarchyPlanner`: the plan is valid but the hierarchy implements it incorrectly.
- `both`: both artifacts need correction.

Retries preserve valid upstream artifacts. A hierarchy-only failure regenerates the hierarchy while reusing the StateDescriptor and DecisionBot plan.

### OuterBot execution verification

OuterBot compares:

- The state before execution.
- The observed post-execution state.
- The expected subtask state.
- The final task goal.
- The natural-language subtask requirement.

It returns `TASK SUCCESS`, `SUBTASK SUCCESS`, `EXECUTE REMAINING ACTIONS`, `RECOVERABLE`, or `NON-RECOVERABLE`. Its verdict is recorded and can trigger feedback replanning, but exact benchmark success remains deterministic legality plus exact goal completion.

## Comparison Conditions

All four conditions use the same task generator, primitive simulator, success definition, selected model, reasoning effort, token limit, and result schema.

### 1. Base model

```powershell
python benchmarking\blocks_world_benchmark.py --task blocks_world_4 --mode no-framework --provider openai --model MODEL --reasoning low
```

Pipeline:

```text
current and goal stacks -> direct primitive plan -> deterministic simulation -> score
```

There is one model call and no LLM verifier or hierarchy.

### 2. Base model plus Inner/Outer

```powershell
python benchmarking\blocks_world_benchmark.py --task blocks_world_4 --mode inner-outer --provider openai --model MODEL --reasoning low
```

Pipeline:

```text
direct primitive planner -> deterministic check -> LLM InnerBot
-> symbolic execution -> LLM OuterBot -> feedback replan
```

The direct planner remains responsible for every `MoveBlock` action. InnerBot and OuterBot add checking and correction but no hierarchy.

### 3. Fixed H1/H2 plus Inner/Outer

```powershell
python benchmarking\blocks_world_benchmark.py --task blocks_world_4 --mode h1-h2 --provider openai --model MODEL --reasoning low
```

Pipeline:

```text
StateDescriptor -> InnerBot state check -> H1 generator -> H2 generator
-> fixed-hierarchy DecisionBot -> deterministic expansion -> InnerBot plan check
-> symbolic execution -> OuterBot -> feedback replan
```

The hierarchy is limited to H1 and H2. H1 is exact and H2 is generated for the concrete task.

### 4. N-level hierarchy plus Inner/Outer

```powershell
python benchmarking\blocks_world_benchmark.py --task blocks_world_4 --mode complete-framework --provider openai --model MODEL --reasoning low
```

Pipeline:

```text
StateDescriptor -> InnerBot state check -> plan-only DecisionBot
-> structured H1-through-Hn HierarchyPlanner -> static compiler
-> InnerBot router -> symbolic execution -> OuterBot -> selective replan
```

DecisionBot declares subtasks and complete expected states. HierarchyPlanner independently chooses the useful hierarchy depth and dispatches one H2-or-higher call per subtask.

Run all conditions together with:

```powershell
python benchmarking\blocks_world_benchmark.py --task blocks_world_4 --mode all --provider openai --model MODEL --reasoning low
```

## Result Artifacts and Metrics

Every run writes:

```text
metrics.json
steps.json
raw_log.jsonl
```

Metrics include exact success, legality, optimality when available, move count, first failure move, H0/H1/H2/Hn counts, maximum hierarchy depth, model calls by stage, replans, verifier checks and disagreements, compiler failure categories, function reuse, compression ratio, tokens, and runtime.

## Implementation Files

- `blocks_world_task.py`: deterministic task generation and small-task BFS optimum.
- `blocks_world_prompts.py`: direct and framework prompt contracts.
- `blocks_world_scoring.py`: parsing, expansion, simulation, and scoring.
- `blocks_world_structured.py`: DecisionBot schemas and N-level static compiler.
- `blocks_world_benchmark.py`: four-condition runner and result writer.
- `blocks_world_sweep.py`: resumable complexity sweeps and plotting.
- `test_blocks_world_benchmark.py`: scripted end-to-end and compiler tests.
