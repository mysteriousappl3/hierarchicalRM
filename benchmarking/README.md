# Hanoi Benchmark Harness

This folder is a standalone text-only benchmark for the planning part of the Unity project. It does not run Unity, render images, or move the robot. It tests whether a model can generate H1/H2 action abstractions and a valid Tower of Hanoi plan from JSON state.

## Files

- `hanoi_benchmark.py` - CLI runner.
- `models.py` - model adapters for OpenAI, Anthropic, Gemini, OpenAI-compatible local servers, and a local mock model.
- `prompts.py` - Unity-derived prompt templates plus explicitly marked JSON-equivalent benchmark notes.
- `scoring.py` - deterministic parser, H2/H1 expansion, H0 move extraction, and Hanoi scorer.
- `task_loader.py` - loads `tasks/hanoi_3.json` through `tasks/hanoi_12.json`.
- `tasks/` - JSON benchmark cases.
- `.env.example` - copy to `.env` for API keys. Do not commit `.env`.

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
