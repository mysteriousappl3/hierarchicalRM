# Symbolic Planning Benchmark Harness

This folder is a standalone text-only benchmark for the planning part of the Unity project. It does not run Unity, render images, or move the robot. It includes Tower of Hanoi, Blocks World, and Checker Jumping domains for testing direct planning, LLM verification, and hierarchical action generation from symbolic state.

## Files

- `hanoi_benchmark.py` - CLI runner.
- `dynamic_hierarchy_benchmark.py` - dynamic H1-through-Hn Tower of Hanoi runner.
- [`details_hanoi.md`](details_hanoi.md) - complete Hanoi setup, prompts, JSON state, verifiers, actions, and comparison conditions.
- `models.py` - model adapters for OpenAI, Anthropic, Gemini, OpenAI-compatible local servers, and a local mock model.
- `prompts.py` - Unity-derived prompt templates plus explicitly marked JSON-equivalent benchmark notes.
- `scoring.py` - deterministic parser, H2/H1 expansion, H0 move extraction, and Hanoi scorer.
- `task_loader.py` - loads `tasks/hanoi_3.json` through `tasks/hanoi_12.json`.
- `tasks/` - JSON benchmark cases.
- `blocks_world_benchmark.py` - four-condition Blocks World CLI runner.
- `blocks_world_task.py` - paper-style Blocks World task generator and small-instance shortest-path oracle.
- `blocks_world_prompts.py` - direct, InnerBot/OuterBot, H1/H2, and dynamic hierarchy prompts.
- `blocks_world_scoring.py` - deterministic Blocks World simulator and hierarchy expansion.
- `blocks_world_structured.py` - JSON contracts and the static compiler for DecisionBot and dynamic H1-through-Hn output.
- [`details_blocksworld.md`](details_blocksworld.md) - complete Blocks World setup, prompts, JSON state, verifiers, actions, and comparison conditions.
- `checker_jumping_benchmark.py` - four-condition Checker Jumping CLI runner.
- `checker_jumping_task.py` - paper-style Checker Jumping task generator.
- `checker_jumping_prompts.py` - direct and framework prompts without a supplied solution algorithm.
- `checker_jumping_scoring.py` - deterministic move simulator, parser, hierarchy expansion, and scorer.
- `checker_jumping_structured.py` - structured DecisionBot contracts and dynamic hierarchy compiler.
- `checker_jumping_sweep.py` - resumable multi-trial sweeps, aggregate CSV output, and plots.
- `.env.example` - copy to `.env` for API keys. Do not commit `.env`.
- `opensource_models/` - registry and VM scripts for serving the Qwen3.5 and
  Ministral 3 Reasoning benchmark checkpoints through vLLM.

## Quick Smoke Test

Run the built-in mock model:

```powershell
python benchmarking\hanoi_benchmark.py --task hanoi_3 --provider mock
```

Run all fixture tasks:

```powershell
python benchmarking\hanoi_benchmark.py --task all --provider mock
```

The mock provider is deterministic and should solve every fixture optimally. Use it to verify the harness before using real APIs.

## Task Setup

### Tower of Hanoi

Tower of Hanoi tasks are stored as `tasks/hanoi_3.json` through `tasks/hanoi_12.json`. Complexity is the number of rings and the optimal solution length is `2^N - 1`. Peg arrays are bottom-to-top:

```json
{
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

The direct conditions plan with `MoveHoop(source_peg, target_peg)`. Hierarchy conditions use `MoveSingleRing(source_peg, target_peg)` as H1, expanded into `MoveCoroutine`, `GrabCoroutine`, `MoveCoroutine`, and `DropCoroutine` H0 calls.

| Condition | Command |
|---|---|
| Base model | `python benchmarking\hanoi_benchmark.py --task hanoi_5 --provider openai --model MODEL --reasoning low --no-framework` |
| Base + Inner/Outer | `python benchmarking\hanoi_benchmark.py --task hanoi_5 --provider openai --model MODEL --reasoning low --no-framework --inner-outer` |
| H1/H2 + Inner/Outer | `python benchmarking\hanoi_benchmark.py --task hanoi_5 --provider openai --model MODEL --reasoning low` |
| N-level + Inner/Outer | `python benchmarking\dynamic_hierarchy_benchmark.py --task hanoi_5 --provider openai --model MODEL --reasoning low` |

See **[Tower of Hanoi benchmark details](details_hanoi.md)** for the prompt contracts, complete JSON representations, InnerBot/OuterBot behavior, H0/H1/H2 examples, N-level composition, scoring, and result layout.

### Blocks World

See **[Blocks World benchmark details](details_blocksworld.md)** for the prompt contracts, JSON state, InnerBot/OuterBot behavior, H0/H1/H2 examples, dynamic N-level compiler, all four conditions, and result metrics.

The Blocks World runner follows the configurations described in *The Illusion of Thinking*. Complexity is the number of blocks. The initial state divides alphabetically ordered blocks across two stacks and leaves the third empty. The goal interleaves the two groups onto stack 0. Arrays are always bottom-to-top, so the last item is movable.

For example, `blocks_world_4` is:

```json
{
  "initial": {"0": ["A", "B"], "1": ["C", "D"], "2": []},
  "goal": {"0": ["D", "B", "C", "A"], "1": [], "2": []}
}
```

All conditions use the same symbolic H0 primitive:

```text
MoveBlock(block, source_stack, target_stack)
```

The deterministic simulator requires the named block to be the current top block, applies every move, and defines success only as a legal sequence whose final state exactly equals the goal. Optimality is reported separately and is not required for success. An exact BFS optimum is computed for N <= 8; larger tasks report `optimal_move_count: null`.

Run all four conditions on a single task:

```powershell
python benchmarking\blocks_world_benchmark.py --task blocks_world_4 --mode all --provider openai --model gpt-5.6-luna --reasoning medium
```

The explicit conditions are:

| Mode | Model-facing pipeline |
|---|---|
| `no-framework` | Paper-style direct `moves = [[block, from, to], ...]` plan; no model verifier or hierarchy |
| `inner-outer` | Same direct planner plus LLM InnerBot validation, LLM OuterBot state checking, and feedback replans |
| `h1-h2` | StateDescriptor, LLM state check, model-generated H1 and H2, DecisionBot, LLM plan check, symbolic expansion/execution, and OuterBot |
| `complete-framework` | StateDescriptor, structured plan-only DecisionBot, structured model-selected H1-through-Hn hierarchy, static compilation, selective InnerBot routing, symbolic expansion/execution, and OuterBot |

The fixed H1 contract is:

```text
MoveTopBlock(block, source_stack, target_stack) = [
  MoveBlock(block, source_stack, target_stack)
]
```

Available paper-style sizes are N = 2, 4, 6, 8, 10, 12, 16, 20, 24, 30, 36, and 40. Every run writes `metrics.json`, `steps.json`, and `raw_log.jsonl` under `results/<model>/<mode>/...`. The selected model is used for the planner, hierarchy generators, InnerBot, router, and OuterBot; verifier models are not silently fixed to another model.

### Complete-framework validation and replanning

DecisionBot returns JSON subtasks with consecutive IDs, natural-language objectives, and complete expected states. HierarchyPlanner returns JSON function definitions with declared levels plus one dispatch call per subtask. OpenAI, supported Claude models, and Gemini enforce these shapes with native JSON Schema output. OpenAI-compatible local servers use the same JSON instructions and deterministic parser by default, and can opt into native schemas with `LOCAL_STRUCTURED_OUTPUTS=true` when the endpoint supports that feature.

Before any move executes, the static compiler checks exact H1, inferred versus declared levels, cycles, unknown functions, arity, parameter binding, concrete dispatch arguments, subtask coverage, hierarchy expansion, and whether higher levels provide reuse or compression. The simulator then independently checks primitive move legality and exact intermediate/final states.

Retries preserve valid upstream artifacts:

- StateDescriptor failure regenerates the state description and all downstream artifacts.
- Decision format or semantic failure regenerates DecisionBot and HierarchyPlanner.
- Hierarchy graph, binding, dispatch, usefulness, expansion, or primitive-plan failure regenerates only HierarchyPlanner and reuses DecisionBot.
- An ambiguous LLM router rejection follows its `DecisionBot`, `HierarchyPlanner`, or `both` ownership field.

`metrics.json` separates `format_valid`, `decision_semantic_valid`, `hierarchy_graph_valid`, `parameter_binding_valid`, `dispatch_valid`, `hierarchy_useful`, `primitive_plan_legal`, and `goal_reached`. It also records per-stage replan counts, router attribution counts, artifact reuse, failure-category counts, function reuse, mappings by level, and the primitive-to-dispatch compression ratio. This avoids counting a formatting or compiler failure as a model execution failure.

## Checker Jumping

The Checker Jumping runner implements Appendix A.2.2 of *The Illusion of Thinking*. For complexity `N`, the board contains `N` red checkers, one empty position, and `N` blue checkers:

```text
initial: R ... R _ B ... B
goal:    B ... B _ R ... R
```

`N` always means **checkers per color**. The board length is `2N + 1`, the total number of checkers is `2N`, and the optimal solution length is `(N + 1)^2 - 1`.

All four conditions use the same H0 primitive:

```text
MoveChecker(color, source_position, target_position)
```

The deterministic simulator enforces all of the following:

- `R` moves only right and `B` moves only left.
- A slide moves forward one position into the empty position.
- A jump moves forward two positions into the empty position and crosses exactly one opposite-colored checker.
- The source must contain the named color, the target must be empty, and both positions must be in range.
- Success requires a completely legal sequence whose final board exactly equals the goal.

Optimality is recorded separately and is not required for success, matching the paper. The first illegal move and its reason are preserved.

The fixed H1 contract is:

```text
MoveCheckerForward(color, source_position, target_position) = [
  MoveChecker(color, source_position, target_position)
]
```

Run all four conditions on one size:

```powershell
python benchmarking\checker_jumping_benchmark.py --task checker_jumping_4 --mode all --provider openai --model gpt-5.6-luna --reasoning medium
```

The conditions are:

| Mode | Model-facing pipeline |
|---|---|
| `no-framework` | Paper-style direct `moves = [[color, from, to], ...]` response and deterministic scoring |
| `inner-outer` | The identical first direct prompt plus LLM InnerBot/OuterBot checks and feedback replanning |
| `h1-h2` | StateDescriptor, LLM state check, exact H1, model-generated H2, DecisionBot, expansion, InnerBot, and OuterBot |
| `complete-framework` | StateDescriptor, structured plan-only DecisionBot, model-generated useful H1-through-Hn hierarchy, static compiler, selective router replanning, symbolic execution, and OuterBot |

The direct prompt describes only the state, goal, legal movement rules, and output format. It does not provide the Checker Jumping solution algorithm. All modes are scored by the same deterministic simulator; an LLM verifier cannot turn an illegal or incomplete plan into a success.

Run a paper-scale 25-trial sweep from `N=1` through `N=15`:

```powershell
python benchmarking\checker_jumping_sweep.py --min-checkers 1 --max-checkers 15 --trials 25 --provider openai --model gpt-5.6-luna --reasoning medium
```

Each individual run writes `metrics.json`, `steps.json`, and `raw_log.jsonl`. The sweep also writes resumable `summary.json`, raw `summary.csv`, aggregated `aggregate.csv`, and a six-panel PNG. Aggregate success uses the proportion of independent trials that are legal and reach the exact goal, with a 95% Wilson confidence interval. The remaining panels report legal-plan rate, mean first-failure move, calls, tokens, and maximum hierarchy depth.

## Framework vs Direct Agent Mode

The runner supports three comparison modes.

### 1. Direct agent only

This is the plain no-framework baseline: one model call, no InnerBot, no OuterBot, no H1/H2.

```powershell
python benchmarking\hanoi_benchmark.py --task hanoi_4 --provider openai --model gpt-5.5 --no-framework
```

Direct mode asks for raw moves:

```text
MoveHoop(source_peg, target_peg)
```

The deterministic scorer still checks legality, completion, and optimality.

### 2. Direct agent + Inner/Outer

This is the middle condition: the model still plans with raw `MoveHoop` calls, but the benchmark wraps it with InnerBot plan checks, OuterBot verdicts, and replanning feedback. It does not generate StateDescriptor, H1, H2, or DecisionBot outputs.

```powershell
python benchmarking\hanoi_benchmark.py --task hanoi_4 --provider openai --model gpt-5.5 --no-framework --inner-outer
```

InnerBot and OuterBot are LLM calls using Unity-style verifier prompts.

### 3. Complete hierarchy framework

By default, the benchmark uses the HierarchicalRM-style flow:

```text
JSON SceneDescriptor
-> StateDescriptor
-> LLM InnerBot state check
-> H1 generation
-> H2 generation
-> DecisionBot plan
-> LLM InnerBot plan check
-> H2/H1 expansion to H0
-> symbolic H0 execution per subtask
-> JSON SceneDescriptor refresh
-> LLM OuterBot verdict
-> replan from current symbolic state when needed
```

This mirrors the Unity `PipelineExecutor` control flow, but swaps camera images and robot motion for deterministic JSON state updates.

```powershell
python benchmarking\hanoi_benchmark.py --task hanoi_4 --provider openai --model gpt-5.5
```

Hierarchy mode uses LLM-based InnerBot and OuterBot verifier calls, matching the Unity setup more closely.

The selected `--model` is used for every model-call stage in the JSON benchmark: StateDescriptor, H1, H2, DecisionBot, InnerBot, and OuterBot. Unity currently hardcodes those components separately in the C# scripts.

## Reasoning Effort

For supported providers, expose reasoning effort with:

```powershell
python benchmarking\hanoi_benchmark.py --task hanoi_7 --provider openai --model gpt-5.5 --reasoning low
python benchmarking\hanoi_benchmark.py --task hanoi_7 --provider openai --model gpt-5.5 --reasoning medium
python benchmarking\hanoi_benchmark.py --task hanoi_7 --provider openai --model gpt-5.5 --reasoning high
```

For OpenAI, this is sent as `reasoning_effort`. The selected value is also recorded in `metrics.json`, `steps.json`, and each raw model-call record. For local/OpenAI-compatible, Anthropic, and Gemini providers, the value is currently recorded for bookkeeping but not sent as a provider-specific thinking parameter.

## Result Layout

Every run writes a structured result folder. The raw JSONL row is stored inside that folder as `raw_log.jsonl`.

Structured results are written under:

```text
benchmarking/results/<model-name>/<not-hierarchy|inner-outer|hierarchy>/<task-id>_<timestamp>/
```

Each structured run folder contains:

```text
metrics.json
steps.json
raw_log.jsonl
```

If you pass `--output`, the runner also writes an optional aggregate JSONL file at that explicit path. By default, no root-level `run_*.jsonl` file is written.

`metrics.json` contains aggregate benchmark fields:

```text
solved
verifier_mode
reasoning_effort
legal
optimal
move_count
optimal_move_count
model_steps / model_call_count
input_tokens
output_tokens
total_tokens
reasoning_tokens
cached_input_tokens
token_usage_available
token_usage
h1_count
h2_count
h0_count
top_level_call_count
replan_count
attempt_count
termination_reason
stage_counts
scene_descriptor_count
state_descriptor_count
h1_generation_count
h2_generation_count
decision_count
innerbot_state_check_count
innerbot_plan_check_count
outerbot_check_count
innerbot_state_llm_call_count
innerbot_plan_llm_call_count
outerbot_llm_call_count
executed_subtask_count
parse_error_count
illegal_reason
```

`token_usage` contains totals, a `by_stage` breakdown, and per-call records. For real API providers, usage is read from the provider response when available. For the mock provider, token counts are rough estimates and `token_usage_available` is `false`. If a local/OpenAI-compatible server does not return a usage object, token fields are recorded as `0` with `missing_usage_call_count` incremented.

`steps.json` contains the actual action decisions:

```text
high_level_plan
expanded_h0_plan
hanoi_moves
final_state
```

In hierarchy mode, `steps.json` also includes the state, H1, H2, DecisionBot outputs, InnerBot checks, OuterBot verdicts, and per-attempt events.
In inner-outer mode, it includes the direct model outputs plus per-attempt InnerBot/OuterBot checks and feedback.
In not-hierarchy mode, it includes the direct model output instead.

In hierarchy mode, `replan_count` is the number of actual retry transitions triggered by state verifier failures, plan verifier failures, expansion failures, illegal symbolic moves, or OuterBot-style recoverable outcomes. The benchmark replans from the current symbolic Hanoi state and feeds failure feedback back into the next DecisionBot prompt.
In inner-outer mode, `replan_count` is the number of retry transitions triggered by malformed direct plans, illegal symbolic direct plans, or OuterBot-style recoverable outcomes. The benchmark replans from the current symbolic Hanoi state and feeds verifier feedback back into the next direct-agent prompt.

This is still not Unity execution: camera capture, physical robot motion, collision failures, and image-based OuterBot checks are not run. InnerBot and OuterBot are extra model calls over JSON state using Unity-style verifier prompts.

## Real Model Examples

OpenAI:

```powershell
Copy-Item benchmarking\.env.example benchmarking\.env
# edit benchmarking\.env and set OPENAI_API_KEY
python benchmarking\hanoi_benchmark.py --task hanoi_4 --provider openai --model gpt-5.1
```

Anthropic:

```powershell
python benchmarking\hanoi_benchmark.py --task hanoi_4 --provider anthropic --model claude-sonnet-4-5
```

Gemini:

```powershell
python benchmarking\hanoi_benchmark.py --task hanoi_4 --provider gemini --model gemini-2.5-pro
```

OpenAI-compatible local server:

```powershell
python benchmarking\hanoi_benchmark.py --task hanoi_4 --provider local --model Qwen/Qwen2.5-7B-Instruct
```

The configured open-source benchmark models and Linux GPU VM workflow are
documented in [`opensource_models/README.md`](opensource_models/README.md).

## Benchmark Contract

The benchmark freezes:

- H0 primitives: `MoveCoroutine`, `GrabCoroutine`, `DropCoroutine`.
- Task state and goal JSON.
- StateDescriptor JSON schema and required Hanoi constraints:
  `Move one ring at a time`, `Only move the top ring of a peg`, and
  `Never place a larger ring on top of a smaller ring`.
- Prompt stages and output fence format.
- Deterministic scoring rules.

The model generates:

- State/goal representation unless `--fixed-goal` is used. The prompt provides the exact required Hanoi StateDescriptor contract so the model should emit the same schema as the fixed goal.
- H1 mapping from H0 primitives.
- H2 mapping from H1 functions.
- Final symbolic plan.

The scorer expands generated H2/H1 calls down to H0 and checks legal Hanoi execution, final success, and optimality.

## Prompt Provenance

Hierarchy-mode prompts are now kept as close as practical to the Unity pipeline prompts. The shared verifier wording for InnerBot and OuterBot should stay Unity-style; JSON benchmark differences should be appended in clearly marked `BENCHMARK JSON EQUIVALENT` sections rather than mixed into the shared text.

- `StateDescriptor.cs` -> `build_state_prompt`
- `H1ActionGenerator.cs` -> `build_h1_prompt`
- `H2ActionGenerator.cs` -> `build_h2_prompt`
- `DecisionBot.cs` -> `build_decision_prompt`
- `InnerBot.cs` -> `build_innerbot_state_prompt`, `build_innerbot_plan_prompt`
- `OuterBot.cs` -> `build_outerbot_prompt`

The benchmark adds clearly marked `BENCHMARK JSON EQUIVALENT` text where Unity would normally provide camera-derived scene state, robot execution context, or parser-specific metadata. These additions are not part of the original Unity prompt text, but they make the Python JSON benchmark runnable and auditable.

For Tower of Hanoi, the JSON benchmark also adds an explicit required StateDescriptor contract. This avoids failures caused by Unity's generic spatial-relation prompt under-specifying procedural Hanoi rules such as moving one top ring at a time.

The direct/no-framework prompt is not from Unity. It is a baseline prompt for comparing a raw Hanoi planner against the hierarchy pipeline.

## Example Scene And Actions

For `hanoi_3`, the benchmark uses a SceneDescriptor-style JSON state instead of a Unity screenshot:

```json
{
  "objects": [
    "<peg_a>",
    "<peg_b>",
    "<peg_c>",
    "<ring_1>",
    "<ring_2>",
    "<ring_3>"
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
  },
  "your_explanation": "Benchmark-provided symbolic Hanoi state; no image extraction was used."
}
```

The fixed H0 primitives are:

```text
MoveCoroutine(reachable_object)
GrabCoroutine()
DropCoroutine()
```

A typical generated H1 action is:

````text
```start_mapping
MoveSingleRing(source_peg, target_peg) = [
  MoveCoroutine(source_peg),
  GrabCoroutine(),
  MoveCoroutine(target_peg),
  DropCoroutine()
]
```end_mapping
````

This means: move to the source peg, grab the top ring, move to the target peg, and drop it.

For the Hanoi benchmark, the allowed H1 functions are exactly:

```text
MoveSingleRing(source_peg, target_peg)
```

A typical generated H2 action for a two-ring subproblem is:

````text
```start_mapping
MoveTwoRingTower(source_peg, auxiliary_peg, target_peg) = [
  MoveSingleRing(source_peg, auxiliary_peg),
  MoveSingleRing(source_peg, target_peg),
  MoveSingleRing(auxiliary_peg, target_peg)
]
```end_mapping
````

This means: move the smaller ring aside, move the larger ring to the target peg, then move the smaller ring onto it.

The model may generate different valid names, but the mappings must expand to known lower-level calls.
