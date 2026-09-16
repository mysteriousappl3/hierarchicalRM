# DynaPlan

**Dynamic Hierarchy Discovery for Robotic Planning in Long-Horizon Puzzle Tasks**

Anonymous code release for double-blind review. Project page: `index.html`
(served from this branch).

DynaPlan plans long-horizon tasks by composing actions out of other composed
actions, so the depth of the hierarchy follows the task instead of being set
in advance. The expanded plan is checked before anything runs, and a failed
check rewrites only the artifact it names. Structure is handled
deterministically; every semantic judgment made online is a language-model
call, and the benchmark's own validator is withheld until the final plan.

Framework ID: `dynaplan_v1_3_compact_fallback` · Benchmark integration
version: `61`

---

## Pipeline

```text
task (goal, constraints, initial state; benchmark-internal fields removed)
  -> Decision Bot: subtasks and checkpoints, no actions named
  -> base actions H1: written once per task, validated, cached
  -> Hierarchy Planner: JSON definitions and per-subtask calls
  -> compiler: callees exist, arities match, no self-calls;
               levels computed; calls expanded into one H0 trace
  -> Inner Bot: one call, forward over actions and backward over
                goals and constraints
       rejected -> rewrite the named artifact, check the whole plan again
  -> execution, one subtask at a time against a saved state
       Outer Bot reviews the exact actions and states, without seeing
       the Inner Bot verdict; a rejection rolls the plan back
  -> benchmark validator, once, on the submitted plan
```

## What is in this repo

```text
dynaplan/
  ARCHITECTURE.md                 design reference for the shipped pipeline
  DYNAPLAN_ARCHITECTURE.svg       pipeline diagram
  baselines/dynaplan/
    README.md                     framework notes and commands
    benchmark.py                  entry point for a single condition
    framework.json                registered framework metadata
    runtime/                      the framework itself
      dynaplan_nlevel_pipeline.py         controller and repair loop
      dynaplan_nlevel_compact_contracts.py JSON generation contracts
      dynaplan_nlevel_localized_repair.py  owner-scoped rewrite
      dynaplan_nlevel_exhaustion_fallback.py  uncertified submission
      shared_nlevel_*                     compile, expand, check, execute
      prompts.py, flat_prompts.py, ...    prompts per domain
      hanoi_solver.py, scoring.py         oracle and scoring helpers
  baselines/TDP/README.md         note on how TDP was reimplemented
  benchmarks/
    official_sweep.py             frozen task registry and runner
    official_sweep_v1.json        the 45 tasks used in the paper
    dynaplan_v13_sweep.py         the two-model campaign launcher
    dynaplan_v13_smoke.py         small offline check
    benchmark.py                  shared harness
    COMPARISON_PROMPT_PROTOCOL.md what every method is given
    Flat-Hanoi/                   flat Tower of Hanoi generator and evaluator
assets/                           figures used by the project page
index.html, style.css             project page
```

## Components

| Component | Responsibility | Boundary |
|---|---|---|
| Decision Bot | Subtasks and checkpoints for the task | Writes no actions |
| H1 source | Base actions, one state change each | Cached after structural validation |
| Hierarchy Planner | Definitions and calls that reach each checkpoint | JSON against a fixed schema |
| Compiler | Callees, arities, self-calls, levels, expansion to primitives | Structure only, no semantics |
| Inner Bot | One check of the expanded plan, forward and backward | Model judgment, coverage enforced deterministically |
| Outer Bot | Review of each executed subtask against its checkpoint | Does not see the Inner Bot verdict |
| Transaction controller | Saves state, executes, rolls back on rejection | Deterministic |
| Validator | Scores the submitted plan | Runs once, cannot trigger repair |

## Third-party baselines and benchmarks

Not vendored here. Clone them next to `dynaplan/baselines/` if you want to
reproduce the comparison:

| Method | Repository |
|---|---|
| AdaPlan-H | https://github.com/import-myself/AHP |
| ADaPT | https://github.com/archiki/ADaPT |
| AoT+ | https://github.com/llmsresearch/aot-plus |
| LLM+P | https://github.com/Cranial-XIX/llm-pddl |
| ReAcTree | https://github.com/Choi-JaeWoo/ReAcTree |
| LexiCon benchmark | https://github.com/Periklismant/lexicon_neurips |

TDP has no public implementation; it was reimplemented from the prompts and
algorithm in its paper, and `dynaplan/baselines/TDP/README.md` records what
that involved.

## How to run

1. Python 3.10 or newer. Install the harness requirements, then install the
   Flat-Hanoi package in editable mode:
   ```bash
   pip install -e dynaplan/benchmarks/Flat-Hanoi
   ```
2. Put provider keys in the environment, for example `OPENAI_API_KEY` and
   `ANTHROPIC_API_KEY`. Nothing is read from a checked-in file.
3. Offline check, which makes no paid calls:
   ```bash
   python dynaplan/benchmarks/dynaplan_v13_smoke.py
   ```
4. Run the campaign. Registration and verification are offline, and inference
   happens only with `--execute`:
   ```bash
   python dynaplan/benchmarks/dynaplan_v13_sweep.py --execute
   ```
   Results are written to a local results directory that this repo ignores.

The 45 tasks are fixed in `official_sweep_v1.json`: three flat Tower of Hanoi
instances for each of N = 3 to 7, and three LexiCon problems at each of 1, 3,
5, 7 and 10 constraints in Logistics and in Blocksworld.

## Not included

- Model outputs, run logs and scored results. The scripts regenerate them.
- The Unity simulator and the recorded videos from the earlier project.
- Third-party baseline checkouts and the LexiCon data, linked above.
