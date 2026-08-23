# Dynamic (n-level) Hierarchy — Architecture

How the `dynamic-hierarchy` mode works, and how it differs from the existing
two-level `hierarchy` mode.

See also: [results](DYNAMIC_HIERARCHY_RESULTS.md) ·
[worked example](HANOI_8_WALKTHROUGH.md) ·
[original proposal](HIERARCHY_SCALER_DESIGN.md)

---

## 1. The core change

The two-level pipeline says **an H2 function may not call another H2**. So every
composed action has to list its H1 calls one by one, which means the model must
literally write out all 2^n - 1 moves. At hanoi_12 that is 4,095 calls, about
30k tokens, against an 8,192-token limit. It cannot fit.

The n-level pipeline lets a level call the level below it:

```
H7_MoveTower7(src, tgt, aux) = [H6_MoveTower6(src, aux, tgt),
                                MoveSingleRing(src, tgt),
                                H6_MoveTower6(aux, tgt, src)]
```

Six lines like this cover 255 moves. Python does the expansion, not the model.
The model writes a few lines regardless of task size.

Everything below follows from that.

---

## 2. The pipeline

**Two-level:**

```
StateDescriptor → InnerBot check → H1 → H2 → DecisionBot → execute → OuterBot
                                        ↑          ↑
                                  goal-blind   writes the full call sequence
```

H2 is built before anyone has thought about the task, so it is guessing which
macros will be useful. On hanoi_3 it produced 6 macros and the planner used 2.

**n-level:**

```
StateDescriptor → InnerBot check → H1 → DecisionBot → DynamicHierarchyAgent
                                            ↑                  ↑
                                    plan only, no calls   builds actions for that plan
                                                                    ↓
                          execute ← InnerBot router ← symbolic validation
                             ↓
                          OuterBot ──→ back to the router
```

Same first three stages, unchanged. Same execution and OuterBot, unchanged.

---

## 3. The three new pieces

### DecisionBot — plans only

It gets the scene, the goal state, and H1. It does **not** get any composed
actions, and the prompt never asks for a call format. So it physically cannot
write a solution — it produces subtasks and goal states in plain English.

H1 is shown only as a boundary: "these are the only things this environment can
do, so keep your subtasks reachable." It is not there to build with.

### DynamicHierarchyAgent — builds the actions

Takes the plan plus H1 and composes actions at whatever depth it judges useful.
It may define H2 from H1, H3 from H2, and so on with no limit.

Two prompt choices worth knowing:

- The worked example in the prompt is **deliberately not Hanoi**. It shows
  abstract `BaseAction` / `Level2Action` / `Level3Action` mechanics. Showing a
  tower would hand over the answer and the benchmark would measure nothing.
- **Self-recursion is forbidden**, with the reason given: the notation has no
  arithmetic and no base case, so `MoveTower(k) = [MoveTower(k-1), ...]` could
  never terminate. The workaround is numbered levels.

### InnerBot router — decides who fixes a mistake

The old InnerBot answered "is this right, yes or no." The router adds an owner:

```
RESULT: NO
OWNER:  HierarchyPlanner
REASON: subtask 3 places the larger ring on the smaller one
```

The prompt also tells it what the harness has **already checked mechanically**,
so it does not waste effort re-verifying the expansion. Without that section it
produced false positives — in the first live run it rejected two perfectly good
hierarchies, costing 2 wasted rounds and 3.5x the tokens on hanoi_5.

---

## 4. How levels are decided

Nothing configures a level count. There is no `--levels` flag, and the model
never labels anything "H4" — it just writes definitions. The harness works out
the depth afterwards by reading the call graph:

```
level(primitive) = 0
level(f)         = 1 + max(level of everything f calls)
```

So on hanoi_8:

| action | calls | level | rings it moves |
|---|---|---|---|
| `MoveSingleRing` | H0 primitives | 1 | 1 |
| `H2_MoveTower2` | MoveSingleRing | 2 | 2 |
| `H3_MoveTower3` | H2 + a single move | 3 | 3 |
| … | | | |
| `H7_MoveTower7` | H6 + a single move | 7 | 7 |

**Level equals the number of rings the action moves.** Each level adds exactly
one ring, because the notation has no loops — which is why depth grows roughly
in step with task size.

A hierarchy is rejected if any callee is undefined, if the graph has a cycle, or
if a body is empty. Cycle detection is what catches a model that ignores the
no-recursion instruction — it fails immediately with a clear message instead of
running away inside expansion.

One useful side effect: `expand_calls` in `scoring.py` was **already** recursive
and had no notion of levels, so it needed no changes at all. Only its depth
ceiling was raised (20 → 64).

---

## 5. What happens when something is wrong

```
parse or level error   →  blame the hierarchy   (no model call needed)
symbolic check fails   →  blame the hierarchy   (no model call needed)
router says NO         →  blame whoever OWNER names
OuterBot reports a problem → send it to the router, which re-diagnoses
```

| OWNER | What re-runs |
|---|---|
| `hierarchy` | just the DynamicHierarchyAgent — the plan is kept |
| `decision` | re-plan, then rebuild the hierarchy |
| `both` | same as `decision` — a new plan invalidates the hierarchy anyway |

If the router's answer is unreadable, it defaults to `both`, which is the safe
choice: worst case it behaves like the old pipeline.

**Why the first two lines need no model call:** the plan contains no function
calls, so it cannot possibly be the cause of a symbolic failure. Attribution is
free in the most common failure case.

**Why this matters for cost:** in the two-level pipeline every correction round
regenerates the whole pipeline — StateDescriptor, InnerBot check, H1, H2, and
the plan. That is 5 calls per round. At hanoi_11 it did 16 rounds (80 calls) and
still executed zero moves. So zero replans does not save 15 calls, it saves
about 80.

---

## 6. Side by side

| | two-level | n-level |
|---|---|---|
| Hierarchy built | before planning, goal-blind | after planning, from the plan |
| Depth | fixed at 2 | model's choice |
| A composed action may call | H1 only | any lower level |
| Planner outputs | subtasks **and the call sequence** | subtasks and goal states only |
| Planner sees | H1 and H2 | H1 only, as a boundary |
| Plan verdict | yes / no | yes / no **+ who owns it** |
| OuterBot finding goes to | the planner | the router |
| A correction re-runs | everything | only what OWNER names |
| Model must write | every one of 2^n − 1 moves | one line per level |

On gpt-5.5 at reasoning `low`, hanoi_3 to hanoi_12:
**10/10 solved vs 8/10 · 50,582 vs 360,929 output tokens · 0 vs 55 replans.**

---

## 7. Files

New (nothing in `scoring.py` or `prompts.py` was touched):

| File | What it does |
|---|---|
| `dynamic_scoring.py` | level inference, validity, per-level counts, the two new parsers |
| `dynamic_prompts.py` | the three new prompts |
| `dynamic_hierarchy_benchmark.py` | the CLI and the loop |
| `test_unrolled_tower.py`, `test_dynamic_scoring.py`, `test_dynamic_prompts.py`, `test_dynamic_loop.py` | 71 offline tests, no API calls |

Modified: four additive edits to `hanoi_benchmark.py`, mock branches in
`models.py`, and a new `--mode dynamic-hierarchy` in `run_open_source.py`.

Results land in `results/<model>/dynamic-hierarchy/`, so the existing baselines
are untouched. The old `h1_valid` / `h2_valid` / `h1_count` / `h2_count` fields
are still populated so existing figure scripts keep working, with
`level_call_counts` and `max_hierarchy_level` added alongside.

> One caveat when reading charts: `h2_count` now folds in every composed level,
> so hanoi_12 reports 4,095. That is not comparable to the two-level meaning —
> use `level_call_counts` for the new mode.

---

## 8. Not built yet

- **Other domains.** The pipeline is domain-neutral but the Hanoi specifics
  (legal-move check, the `MoveSingleRing` contract, scene/goal JSON) are
  hardwired in about six places. A `Domain` interface would cover it. Needed
  before Blocks World or Sokoban.
- **Skills module.** The prompt already accepts `previous_hierarchies`, but the
  loop never passes it — with 0 replans across 20 task-runs there has been
  nothing to reuse.

## 9. Two behaviours to be aware of

- **Plan granularity drives cost, not depth.** Each subtask costs one OuterBot
  call. hanoi_8 with an 8-subtask plan used 14 model calls; hanoi_12 with a
  3-subtask plan used 9. This is the main reason per-task token counts vary
  between runs.
- **On Hanoi it builds pure depth, no breadth** — exactly one action per level,
  in all 10 tasks. That is correct here, since there is only one useful
  abstraction. Whether it ever builds several distinct skills at one level is
  untested.
