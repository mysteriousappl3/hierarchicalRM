# Dynamic Hierarchy Revision Plan

---

## 1. Core framing change

- Headline contribution moves from "hierarchical H1/H2 pipeline" to
  "**dynamic n-level hierarchy discovery**" - depth is not fixed, not
  pre-configured, and inferred post-hoc from the model's own call graph.
- The old fixed two-level pipeline becomes an **ablation/baseline**, not the
  method - it is the sharpest evidence that dynamic beats fixed, since it's
  the same framework minus the one change that matters.
- Paper narrative: (1) dynamic hierarchy as the method, (2) flat Hanoi +
  LEXICON as evidence it's not a Hanoi-recursion trick, (3) open-source models
  as evidence it's not frontier-model-only, (4) LIBERO robotic sim as evidence
  it transfers beyond symbolic puzzles.

---

## 2. Puzzle track

**Tasks:**
- Flat Hanoi (non-canonical/scrambled variant - no clean recursive shortcut)
- One LEXICON domain, extended with a second harder variant:
  - [*LexiCon: a Benchmark for Planning under Temporal Constraints in Natural
    Language*](https://arxiv.org/abs/2510.05972) (NeurIPS 2025, D&B track),
    code: [github.com/Periklismant/lexicon_neurips](https://github.com/Periklismant/lexicon_neurips)
  - **Primary LEXICON domain: Logistics, not Blocksworld** (decided, see
    Sec. 2.1). Blocksworld secondary if budget allows.
  - `c` throughout = **number of PDDL3 temporal constraints** on the problem
    (LEXICON's difficulty knob; dirs `data/data_{c}/`, ~30 problems each,
    c in {1,2,3,5,7,10}). Each constraint is an `always` / `sometime` /
    `sometime-after` / `sometime-before` clause over the state trajectory.
    c=10 expands to ~16 text clauses, since the two conditional forms each
    carry a trigger plus a consequent.
  - CoPE's constraint-augmented Blocksworld variant, from
    [*Language Model as Planner and Formalizer under
    Constraints*](https://arxiv.org/abs/2510.05486), code:
    [github.com/CassieHuang22/LLM-as-Formalizer-constraints](https://github.com/CassieHuang22/LLM-as-Formalizer-constraints).
    **Dropped as a hierarchy baseline**: verified entirely flat (no
    decomposition), and no venue acceptance found (v2 Apr 2026, arXiv only).
    Still usable as a *task* source if we want extra constraint-heavy
    Blocksworld instances.

---

### 2.1 Does LEXICON actually get harder? (measured, not assumed)

Concern: horizons of 16-37 actions are short for frontier reasoning models, so
does this benchmark show complexity at all? Measured directly from
`lexicon_neurips` ground-truth optimal plans (`constrained_plan` vs
`unconstrained_plan`, n~30 per cell):

| domain | c=1 | c=3 | c=5 | c=7 | c=10 |
|---|---|---|---|---|---|
| **Logistics** - optimal len | 17.4 | 23.6 | 27.9 | 32.5 | **37.5** (max 57) |
| Logistics - unconstrained | 11.7 | 9.6 | 11.1 | 11.0 | 10.7 |
| Logistics - **ratio** | 1.48x | 2.45x | 2.52x | 2.95x | **3.50x** |
| **Blocksworld** - optimal len | 6.8 | 10.0 | 12.6 | 12.7 | 16.1 |
| Blocksworld - unconstrained | 3.2 | 3.3 | 3.1 | 3.2 | 3.3 |
| Blocksworld - **ratio** | 2.16x | 3.03x | 4.01x | 4.02x | **4.87x** |

**Answer: yes, and constraint count is a clean horizon knob.** The
unconstrained goal length is *flat* (~11 Logistics, ~3.2 Blocksworld) across
every cell - so the goal is not getting harder. All growth is constraint-induced:
constraints force non-greedy, self-undoing detours. Logistics reaches 37.5 mean
/ 57 max, which is a real horizon.

**But horizon is not the main difficulty - non-Markovian verification is.**
PDDL3 `sometime-after` / `sometime-before` are predicates over the *whole
trajectory*, not the current state. An autoregressive model choosing action *t*
must verify a property of everything it has emitted and will still emit. It
cannot check its work locally at any step. This is why frontier models
(GPT-5, o3, R1, Gemini-2.5) drop to near 0% at c=10 on plans of only ~16 actions.

**Implication for our claim:** frame the LEXICON result as
**constraint-induced horizon**, not "long horizon". The hierarchy argument is
that a composed action satisfies an interleaving constraint *once* at the right
level instead of re-verifying it at every primitive step. Sharper than a
horizon-length claim, and it is what the data supports.

### 2.1.1 Which second domain? (measured from shipped frontier-model plans)

Concern: if a domain is easy, the row is useless. Measured o3's shipped plans
against SymK optimal (`len == opt` = plausibly optimal, `len > opt` =
definitely suboptimal). Not a full validity check, but a sound hardness proxy:

| domain | c=1 | c=3 | c=5 | c=7 | c=10 | n at c=10 |
|---|---|---|---|---|---|---|
| Blocksworld `len==opt` | 0.73 | 0.40 | 0.37 | 0.24 | **0.14** | 28-32 |
| Sokoban `len==opt` | 0.60 | 0.50 | 0.40 | 0.14 | **0.00** | **12-15** |
| Logistics `len==opt` | 0.83 | 0.60 | 0.52 | 0.17 | **0.15** | 30 |
| BabyAI `len==opt` | 0.71 | 0.57 | 0.38 | 0.23 | 0.22 | 32 |

**Nothing here is easy at c>=7.** o3 is optimal on 14-24% of problems at c=7
and worse at c=10. Blocksworld's short plans (16.1 mean) do NOT make it easy -
that is the whole point of Sec. 2.1: difficulty is non-Markovian constraint
verification, not horizon length.

**Decision: keep Blocksworld as the second domain, not Sokoban.**

- **Sokoban is harder but unusable at the top end.** It hits 0.00 at c=10 -
  attractive - but only **15 problems** there (vs 30-32 for Blocksworld), and
  only ~10-12 have model plans. A floor effect measured on n=12 has enormous
  Wilson intervals; if every method scores ~0 we learn nothing and cannot
  separate them. Blocksworld keeps n=30+ at every level.
- **Blocksworld is the standard comparison surface.** PlanBench, LLM+P, AoT+
  and CoPE all ship Blocksworld, so our numbers are contextualizable against
  published work. Sokoban has far less external comparison.
- **Blocksworld has the steepest constraint ratio** (4.87x vs Sokoban 3.21x) -
  the cleanest demonstration that constraints, not goals, create the horizon.
- Sokoban is also grid/spatial, which conflates spatial reasoning with
  constraint reasoning. Blocksworld isolates the variable we care about.

**AlfWorld is ruled out**: not wired into `verify_plan.py` (only blocksworld /
babyai / logistics / sokoban are), so there is no verifier for it.

**On MysteryBlocksworld (CoPE):** inspected the repo. It obfuscates predicates
into `action1/object1/predicate3` so models cannot pattern-match memorized
Blocksworld. Genuinely harder, and the right tool against a
"they memorized Blocksworld" objection - but it changes *what is measured*:
it tests schema induction from an unfamiliar symbol table, not hierarchical
planning. Our hierarchy claim is about depth discovery, and obfuscation adds a
confound rather than stressing depth. **Use it only as a small robustness
appendix if a reviewer raises memorization** - not as a main row. Note CoPE
has no venue acceptance (arXiv only).

**Why Logistics is primary:** longest horizons (37.5 vs 16.1), the only domain
with a naturally-occurring two-level structure (trucks within city / planes
between cities), and free intra-plan reuse when k packages share a route.
Blocksworld at 5-7 blocks may have nothing for an n-level hierarchy to abstract.

---

### 2.2 Baselines - priority order

All rows go in the same results table as HierarchicalRM. Ordered by build
priority; stop wherever the page/time budget runs out.

**A `TaskDomain` *code interface* is a shared prerequisite for P0-P4.**
(Software abstraction, not a planning "domain" - named `TaskDomain` to avoid
the overload with PDDL domains.) Three methods:

```python
class TaskDomain:
    def step(self, state, action):   # -> (new_state, ok, reason)
    def primitives(self):            # the H0 action list
    def render_state(self, state):   # state -> text for the prompt
```

Our loop currently hardcodes Hanoi at ~3 places: state dicts
`{peg: list(stack)}` (~10 sites), `apply_hanoi_move` at
`dynamic_hierarchy_benchmark.py:538,797`, and the `MoveSingleRing` H0 contract
in `dynamic_scoring.py:40`. `dynamic_scoring.py` is otherwise already
domain-neutral, so level inference / cycle detection / `expand_calls` need no
edits. Implement `HanoiDomain` + `LogisticsDomain`; everything above the
interface - i.e. the contribution - is untouched.

The same `step()` is what TDP's `E.Step(a)`, ADaPT, and ReAcTree each need to
run on a non-interactive benchmark. **Build once, unblock our method and every
baseline.**

#### Baselines by category

**A. Classical planner / PDDL (solver-in-the-loop)**

| P | Baseline | Role | Venue | Code | Training |
|---|---|---|---|---|---|
| **P3** | **LLM+P** | LLM->PDDL->Fast Downward. Optimal by construction, so it *should* beat us on optimality - the "just use a real planner" foil. PDDL-native, drops into LEXICON cleanly. | arXiv 2023, 800+ cites | [Cranial-XIX/llm-pddl](https://github.com/Cranial-XIX/llm-pddl) | none |

**B. Hierarchical / decomposition (the core comparison set)**

| P | Baseline | Hierarchy mechanism | Venue | Code | Training |
|---|---|---|---|---|---|
| **P0** | **Fixed H1/H2** | fixed depth 2, built goal-blind before planning | this paper | built (Hanoi only) | none |
| **P1** | **AdaPlan-H (AHP)** | self-adaptive depth `m`, capped at 3; levels are *independent* flat step-lists (no level calls the level below) | arXiv Apr 2026 | [import-myself/AHP](https://github.com/import-myself/AHP) | **none needed** [YES] |
| **P2** | **TDP** | DAG of sub-goals w/ node-scoped context; breadth via shared deps, one level of subgoals | arXiv Jan 2026 | prompts only -> `baselines/TDP_SPEC.md` | none |
| **P4** | **ADaPT** | recursive, depth-adaptive via `max_depth` knob -> sweeping it gives an *external* depth ablation | NAACL Findings 2024 | [archiki/ADaPT](https://github.com/archiki/ADaPT) | none |
| P6 | ReAcTree | agent tree, nodes recursively expand the tree; sequence/fallback/parallel control flow | **AAMAS 2026** | [Choi-JaeWoo/ReAcTree](https://github.com/Choi-JaeWoo/ReAcTree) | none (Unity/ALFRED coupling to strip) |
| - | *(ours)* | n-level, depth inferred post-hoc from the call graph; Python expands | - | built | none |

**C. Flat / non-hierarchical long-horizon (search-based prompting)**

| P | Baseline | Role | Venue | Code | Training |
|---|---|---|---|---|---|
| P5 | AoT+ | 2025 SOTA search-based prompting (state memoization + random trajectory augmentation). The "you don't need hierarchy, you need better search" foil. Ships Blocksworld + Logistics. | **ICLR 2025** | [llmsresearch/aot-plus](https://github.com/llmsresearch/aot-plus) | none |

**Cut to four for the 8-page budget: P0, P1, P2, P3** - one per mechanism
(fixed-depth / adaptive-depth / DAG / solver). P4-P6 to supplementary.
Rationale: P4 ADaPT overlaps P1 on "adaptive depth"; P5 AoT+ is the weakest
fit to the hierarchy claim; P6 ReAcTree is the most expensive to port.

**Not used on the puzzle track - ReplanVLM.** It is a *vision*-language
replanning method: its whole mechanism is internal/external error correction
driven by visual scene feedback from a VLM. On a symbolic text benchmark
there is no image, so what remains after stripping the vision is a generic
replan loop - which our Fixed H1/H2 row (and TDP's node-local replanning)
already covers, with code. Keep ReplanVLM as a **cite-only row on the robotic
track**, where its visual closed loop is the actual comparison. Running a
de-visioned ReplanVLM on Hanoi would be a strawman and a reviewer would say so.

**Verified during the search (do not re-litigate):**
- **AdaPlan-H needs no training for our use.** Traced the repo: hierarchical
  plans enter the agent as a *prompt string* (`prompt/templates.py:27-28`).
  `--metaplan_type` only sets the output directory path
  (`main.py:93-95`); the real switch is `--metaplan_path` -> a plan JSON.
  Plans are generated by one prompted LLM call (`genplan/gen_plan.py`) with
  depth chosen by a 3-bucket English rubric (easy=1 / medium=2 / hard=3 levels).
  SFT+DPO is only how they get their *headline* numbers - label our row
  "untrained variant".
- **AdaPlan-H is not the same mechanism as ours.** Its N levels are independent
  flat step-lists at different granularities; a level never calls the level
  below. All N get concatenated into the prompt, so more depth = *more* tokens.
  Ours infers depth from the call graph and Python does the expansion. Good
  related-work paragraph; defuses it as a threat.
- **TDP has no public code but publishes all 6 prompts + Algorithm 1 verbatim.**
  Transcribed to `baselines/TDP_SPEC.md`, full text in
  `baselines/tdp_paper_fulltext.txt`. For a training-free method the prompts
  *are* the method.
- **Ruled out:** MAP (Nature Comms 2025 but arXiv v1 Oct 2023, pre-reasoning-era);
  HiPlan (no code, needs expert trajectories); HSRL (no code, needs M-GRPO
  fine-tuning); Multi2 / HiMAC / HIPIF (all require SFT/RL); HyperTree Planning
  (ICML 2025 but no code, TravelPlanner only); T3 Planner (STL not PDDL3,
  needs distillation); PDDLego+ (recursion triggers on *partial observability*;
  LEXICON is fully observable).

**Baseline-integrity rules (all rows):**
- Never copy a published number into our tables - re-run everything on our
  backbones. All three of HiPlan / AdaPlan-H / TDP re-ran their own baselines
  on matched backbones; match that standard.
- Mark each row `official code` / `authors' prompts, our implementation` /
  `our reimplementation`.
- Report **call budget per method** alongside SR. A hierarchical method makes
  several calls per step; ReAct makes one. Without matched budget, a win partly
  measures spend. This is what the cost-performance frontier figure is for.
- Inspect each baseline's failure traces by hand before trusting its number.
  An under-tuned baseline is the most common way a comparison paper dies in review.

**Robotic track:** ReplanVLM stays as a *cite-only* row (no public code) - 
see Sec. 3.

### 2.3 Build order (with a de-risking gate)

1. **`TaskDomain` interface + `HanoiDomain` adapter** - refactor the ~3
   hardcoded Hanoi bindings behind the interface (see Sec. 2.2), against the
   existing 71 offline tests.
2. **LEXICON Logistics adapter** - `step()` + NL problem parser + wire
   `verify_plan.py`.
3. **GATE: run our method only, ~10 Logistics problems.**
  - `max_hierarchy_level` >= 3 -> plan validated, proceed to P0-P4.
  - `max_hierarchy_level` = 1 -> the hierarchy has nothing to abstract on
     LEXICON. Reframe before spending a week on baselines.
4. P0 Fixed H1/H2 on Logistics -> P1 AdaPlan-H -> P2 TDP -> P3 LLM+P -> P4 ADaPT.

Steps 1-3 decide whether steps 4+ are worth doing. **Do not start any baseline
before step 3 reports.**

**Model scale:**
- 1-2 open-source models, e.g. one GPT-OSS (20B) + one of Qwen/Mistral -- Get thoughts from Hamza on what models for open sources with smaller parameters are best
- Run on the same puzzle tasks/baselines above - no separate benchmark surface
- Purpose: does dynamic hierarchy discovery hold up on weaker reasoners, or
  does it need a reasoning floor the fixed 2-level scheme didn't need

---

## 3. Robotic simulator track

**Benchmark:** LIBERO-LH (long-horizon subset) - part of the
[LIBERO benchmark](https://arxiv.org/abs/2306.03310) (NeurIPS 2023) |
code: [github.com/Lifelong-Robot-Learning/LIBERO](https://github.com/Lifelong-Robot-Learning/LIBERO)

**VLA backbone:** pi0.5 - 
[*pi0.5: a Vision-Language-Action Model with Open-World Generalization*](https://arxiv.org/abs/2504.16054)
(Physical Intelligence, 2025) | code:
[github.com/Physical-Intelligence/openpi](https://github.com/Physical-Intelligence/openpi)

**Baselines:**
| Baseline | Role | Paper | Code |
|---|---|---|---|
| pi0.5 flat (no planner) | floor/ablation | (same pi0.5 citation above) | your own backbone |
| Reflective Planning (ReflectVLM) | look-ahead/self-correction SOTA | [*Reflective Planning: Vision-Language Models for Multi-Stage Long-Horizon Robotic Manipulation*](https://arxiv.org/abs/2502.16707) | [github.com/yunhaif/reflect-vlm](https://github.com/yunhaif/reflect-vlm) |
| ReplanVLM (on pi0.5) | generic replanning, no hierarchy | (same ReplanVLM citation above) | verify existing implementation status - no public code found elsewhere |

**Existing dVRK real-robot results:** keep as-is from the original submission,
untouched - already validated evidence of real-hardware transfer.

---

## 4. Metrics (ICRA, 8-page budget)

Extend the original paper's metric vocabulary rather than replace it, so the
revision reads as continuous with the original results.

**ICRA framing note:** a robotics reviewer weights *success and cost on real
tasks* far above reasoning elegance. Lead every table with SR and a cost
column; keep depth/compression as the mechanism evidence that explains them.

### 4.1 Tier 1 - report on every table, both tracks

| Metric | Field | Status | Why ICRA cares |
|---|---|---|---|
| Success Rate + Wilson CI | `result` / `score` | have | the number some reviewers read first |
| Step Count (executed primitives) | `executed_moves` | have | efficiency of the *executed* plan |
| Replan Count | `replan_count` | have | robustness proxy |
| Model call count | `model_call_count` | have | latency/cost proxy |
| **Planning wall-clock** | - | **MISSING, ADD** | deployability - see below |

**Wall-clock is the one ICRA-specific metric we do not yet log, and it is not
optional for a robotics venue.** "Plans in 8s vs 45s" is a deployability
argument a robotics reviewer accepts immediately. Log per stage, report
**median and p90, not mean** (LLM latency is heavy-tailed). This must be added
*before* any runs - it cannot be retrofitted afterwards.

Everything else in Tier 1-3 is already logged: `models.py` captures normalized
per-call `usage` across OpenAI / Anthropic / Gemini, and the benchmark records
`stage_counts`, `level_counts`, `max_hierarchy_level`, `expanded_h0_calls`.

### 4.2 Tier 2 - depth and compression (the mechanism evidence)

| Metric | Field | Note |
|---|---|---|
| `max_hierarchy_level` | have | depth discovered, not configured |
| `level_counts` (actions per level) | have | **our breadth evidence** - see the breadth risk below |
| **Compression ratio** = `len(expanded_h0_calls) / high_level_calls` | derivable | **the single strongest metric** |
| Output tokens, total + per stage | via `usage` | the 7.1x result vs fixed H1/H2 |

**Prefer compression ratio over raw token count as the headline.** Token counts
depend on model, prompt, and tokenizer; compression ratio is a property of the
*hierarchy itself*. At hanoi_12 it is 4095 / ~6 = ~680x. That number is
unambiguous and model-independent.

### 4.3 Tier 3 - LEXICON only, separate the failure modes

A plan can reach the goal and still violate a trajectory constraint, and
`verify_plan.py` returns invalid / suboptimal / optimal. Report three distinct
columns: **goal-reach rate**, **constraint-violation rate**, **optimality rate**.

Expect DAG/subgoal baselines (TDP especially) to drop `sometime-after` /
`sometime-before` constraints outright - a DAG node cannot encode a trajectory
predicate. Keeping the columns separate is what lets that be reported as a
finding rather than a muddle.

### 4.4 Robotic track

Reuse the existing real-robot vocabulary (SR, Outer Bot trigger frequency,
Step Count, as in original Table 4), **plus planning wall-clock**.

**ACTION ITEM - coordinate with whoever owns LIBERO-LH / ReflectVLM / Franka:**
ask them to log `max_hierarchy_level` and `level_counts` on the robot runs.
Cheap to add now, impossible to retrofit. Without it, Figures 3 and 4 are
puzzle-track-only, and the paper's central claim then has no evidence on the
platforms ICRA reviewers weight most heavily.

---

## 5. Figures (priority order)

**Fig 1 (must) - Success vs. horizon.** x = Hanoi N (3..12) / LEXICON c
(1,3,5,7,10); y = SR with Wilson CIs. One line per method. The money plot; if
only one figure survives the page budget, it is this one.

**Fig 2 (must) - Cost-performance frontier.** x = model calls (and/or
wall-clock), y = SR. One point per method. This is where hierarchy wins even
when SR ties, and it is the direct answer to "you just spent more compute."
It also pre-empts the matched-budget objection, since the reviewer can see the
budget on the axis.

**Fig 3 (must) - Compression ratio vs. horizon.** `expanded_h0_calls /
high_level_calls` as N grows, with mean discovered depth overlaid on a second
axis. Should *increase* with N. **This is the figure that makes the title
true** - it operationalizes "hierarchy" as a measured quantity.

**Fig 4 (strong) - Discovered depth distribution per domain.** Stacked bars or
violin: Hanoi N=3..12, LEXICON c=1..10, LIBERO-LH, Franka. Shows depth *adapts
to task structure* rather than being tuned.
> Honest contingency: if the robot tasks come back at depth 2 while Hanoi
> reaches 7+, the claim becomes "depth matches task structure" rather than
> "deeper is better". That is still a good claim - but write the framing that
> way from the start instead of being forced into it at rebuttal.

**Fig 5 (if space) - Failure-mode stacked bars.** Fields already logged:
`illegal_reason`, `failed_move`, `termination_reason`, `owner`. Shows *why* we
win, not just that we do. First to cut if pages are tight.

---
