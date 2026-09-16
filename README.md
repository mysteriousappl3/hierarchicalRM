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

## Abstract

Language model planners for long-horizon robot tasks become less reliable as
plans grow, since every action must be correct and earlier mistakes make later
ones more likely. Hierarchical decomposition groups primitive steps into
higher-level actions, but existing methods fix the number of levels in
advance, and when composed actions may call only primitives the planner still
writes out every step. We introduce DynaPlan, a planning framework in which
composed actions may call other composed actions, so the number of levels is
not fixed in advance. A language model checks the fully expanded plan before
execution, in a forward pass over its actions and a backward pass over its
goals and constraints, and a failed plan is repaired by rewriting only the
part at fault from the first failing subtask. We evaluate DynaPlan on flat
Tower of Hanoi and on the Logistics and Blocksworld domains of the LexiCon
benchmark, which adds temporal constraints to classical planning problems. We
further validate DynaPlan on two real robots executing primitive skills, a
dVRK solving flat Tower of Hanoi and a Franka arm solving Blocksworld
problems.

![DynaPlan on a Blocksworld task](assets/teaser.png)

*A composed action may call other composed actions, so one definition can
cover many primitive steps. Nothing sets a depth: the level of an action
follows from what it calls, and the depth is the largest level among the
definitions. Action names are illustrative.*

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

![DynaPlan pipeline](assets/architecture.png)

The Decision Bot writes checkpoints without naming actions, the Hierarchy
Planner composes the actions that reach them, a compiler expands everything
into one list of primitive actions, and the Inner Bot checks that list before
anything runs. During execution the Outer Bot reviews each subtask against its
checkpoint without seeing the Inner Bot verdict, so the two judgments stay
independent.

---

## Results

Each method plans 15 tasks per benchmark with two models, under the same task
description, the same action and constraint definitions and the same
instruction to use as few actions as possible. No method sees the validator
during planning.

![Valid and optimal plans per benchmark](assets/table_main.png)

DynaPlan solves the most flat Tower of Hanoi tasks with both models, and it is
the only planner to solve a Hanoi instance whose optimal solution is 35 moves
long, where no baseline solves one longer than 11 moves.

![Actions in the plan against actions composed](assets/compression.png)

A planner that writes its plan directly must produce every action the robot
executes. DynaPlan composes one call per subtask and the definitions those
calls use, and the compiler expands them. On plans of ten actions or fewer
that saves nothing; on plans longer than 25 actions the model composes 16.2
actions for a 33.6-action plan.

### Real robot setups

![dVRK and Franka setups](assets/robots.png)

Both robots execute fixed primitive skills with no learned policy, and the
state after each subtask is read by colour thresholding against a fixed
palette. On the dVRK a ring move expands to four primitives, and on the Franka
a block move expands to two.

---

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
