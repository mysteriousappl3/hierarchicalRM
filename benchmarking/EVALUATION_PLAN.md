# Evaluation Plan — Benchmarks, Baselines, and Reporting

> Plan for the paper's experimental section: which external benchmarks to adopt, which
> published methods to compare against, and what figures/tables/statistics to report.
> Written in response to two reviewer complaints (Table I lacks a reuse baseline;
> Table III lacks reproducibility detail).

---

## Terminology

Terms used loosely in the draft, pinned down here so the paper uses them consistently.

- **Horizon** — the number of *primitive* (H0) actions in an optimal solution. "Long
  horizon" means that number is large (tens to hundreds), so the planner must stay
  coherent over many steps. Hanoi at N=10 has a horizon of 1023; a LIBERO-Long task has a
  horizon of roughly 5-10 subtasks. Horizon is about *solution length*, not task difficulty
  in the search-space sense.
- **Horizon scaling** — how a method's success rate degrades as horizon grows. The central
  claim of the paper: flat planners fall off sharply, hierarchical ones should not.
- **Hierarchy depth** — number of abstraction levels actually used (H0 primitives → H1 →
  H2 → ... → Hn). Depth 1 means no abstraction beyond primitives.
- **Compression ratio** — `expanded_h0_calls / high_level_calls`. How many primitive actions
  one high-level dispatch stands for. This is the quantity that makes "hierarchy" measurable
  rather than declared; if it stays near 1, the hierarchy is a renaming, not an abstraction.
- **Reuse** — how many times a *single* generated function is dispatched. Two distinct kinds,
  and the paper must not conflate them:
  - **Intra-plan reuse** — calling the same function several times within one plan. This is
    what the harness currently measures.
  - **Cross-task reuse** — carrying a function generated for one task over to a later task.
    The pipeline does **not** do this today. This is the gap Reviewer 1 identified.
- **Optimality** — plan length equals the known optimal cost. Distinct from **validity**
  (legal moves, goal reached, but possibly longer than necessary). Report both; they come
  apart badly at high horizon.
- **Latent failure** (SIMMER's term) — a step that violates no precondition and raises no
  error, but silently ruins the outcome later. Not our failure mode; our domains have no
  hidden state. Mentioned only to explain why SIMMER was not adopted.
- **GSR (Goal Success Rate)** — fraction of goal conditions satisfied. Gives partial credit,
  unlike binary task success. ReAcTree reports this.

---

## Benchmarks

| Benchmark | Role | Status |
|---|---|---|
| Hanoi (tower-to-tower, flat-to-flat) | Existing; cleanest horizon knob (2^N − 1) | Have |
| Blocks World, Checker Jumping | Existing; second and third domains | Have |
| **LEXICON** — Logistics (primary), AlfWorld (secondary) | External, published, symbolic verifier | To add |
| **LIBERO-Long** | External, embodied, long-horizon | To add |
| SIMMER | *Not adopted* — no horizon axis, scores safety not composition | Rejected |

### Why LEXICON over SIMMER

LEXICON (NeurIPS 2025 D&B) generates constrained planning problems over five PDDL domains,
translates them to natural language, and verifies both validity and **optimality** with a
symbolic engine. Constraint count {1,3,5,7,10} maps to rising optimal cost — a principled
horizon knob that matches how we already scale Hanoi and Checker Jumping. 150 problems per
domain, 30 per constraint level.

SIMMER (COLM 2026) has 100 fixed cooking scripts with no complexity axis, and scores
failures-per-plan by safety category. A hierarchy that compresses 40 primitives into 6
dispatches scores identically to a flat plan there — it cannot see our contribution.

### Why Logistics is the primary LEXICON domain

It is the only LEXICON domain with a *naturally occurring* two-level hierarchy: trucks move
packages within a city, airplanes between cities. So the correct abstraction is discoverable
rather than imposed:

```
H0: load, unload, drive, fly
H1: DeliverWithinCity(pkg, from, to)       = load → drive → unload
H2: DeliverAcrossCities(pkg, cityA, cityB) = DeliverWithinCity → fly → DeliverWithinCity
```

This matters because our existing H1s (`MoveSingleRing`, `MoveTopBlock`) expand to a single
primitive — the H1 level is close to a rename. Logistics gives a genuinely multi-primitive
H1. It also gives free **intra-plan reuse**: k packages on the same route means defining
`DeliverAcrossCities` once and dispatching it k times.

Secondary: **AlfWorld** — longest horizons available (optimal cost 7→37) and its constraints
impose partial orderings over subtasks. Rejected: Sokoban (irreversible deadlocks, irregular
geometry so no repeating macro), BabyAI (navigation-only, lowest costs, needs conditional
effects).

---

## Baselines

Split by which experiments they serve. Code availability was the binding constraint.

### Symbolic / text benchmarks (LEXICON, Hanoi, flat-Hanoi)

| Method | Venue | Code | Why |
|---|---|---|---|
| **LLM+P** | arXiv:2304.11477 | [Cranial-XIX/llm-pddl](https://github.com/Cranial-XIX/llm-pddl) | Ships blocksworld; implements **4 methods in one repo** (direct, +in-context, →PDDL, +context→PDDL). The "just use a real planner" foil — Fast Downward is optimal, so it should beat us on optimality. PDDL-native, so it drops into LEXICON cleanly. |
| **ProgPrompt** | [progprompt.github.io](https://progprompt.github.io/) | Public | Closest published method to our claim — generates programmatic plans with function definitions, but **no persistent library and no explicit level assignment**. That delta *is* our contribution. |
| **Tree-Planner** | ICLR 2024 | [Aaron617/tree-planner](https://github.com/Aaron617/tree-planner) | Efficiency foil. Attacks the same cost problem via sampling+aggregation rather than abstraction. We already log `model_call_count`, so the comparison is nearly free. |

### LIBERO-Long

| Method | Venue | Code | Why |
|---|---|---|---|
| **ReplanVLM** | IEEE RA-L | ✗ none found | Internal + external error correction = our InnerBot/OuterBot split under other names. **Cite, do not run.** Must position against it explicitly. |
| **Action-Sketcher** | CVPR 2026 | [FlagOpen/Action-Sketcher](https://github.com/FlagOpen/Action-Sketcher), Apache-2.0 | **Recommended runnable baseline.** Native LIBERO support, `run_libero_example.py`, released PI0-LIBERO checkpoint. Days of work, not weeks. Weaker scientific match (its novelty is visual sketches, orthogonal to ours) but it runs. |
| **ReAcTree** | AAMAS 2026 | [Choi-JaeWoo/ReAcTree](https://github.com/Choi-JaeWoo/ReAcTree) | Strongest *conceptual* comparison — recursive goal decomposition into an agent tree, plus episodic + working memory. Same thesis as our dynamic hierarchy. **But see port cost below.** |
| **ViReSkill** | arXiv:2509.24219 | ✗ not confirmed | Growing skill library, replays stored skills without extra LLM calls. Reports **0.66 with reuse vs 0.50 without on LIBERO-10** — an existing published measurement of exactly our reuse question. Cite as motivation; email authors for code. |

### ReAcTree port cost — realistic estimate

**1.5–3 weeks**, and the blockers are structural, not incidental:

- VirtualHome is a **hard dependency** (Unity binary `linux_exec.x86_64` as a separate
  process); ALFRED bundled the same way.
- **No environment abstraction** — no gym-style wrapper. Parallel config branches
  (`wah_reactree`, `alfred_reactree`) with per-env prompts in `resource/{wah,alfred}/`.
  LIBERO means hand-adding a third branch.
- **Episodic memory is env-coupled** (`resource/*/em_llm/`, built by `embed_em.py` from
  trajectories). Running it on LIBERO without rebuilding EM benchmarks a crippled version —
  reviewers will catch that.
- **Backend mismatch** — built on HuggingFace Llama-3.1 8B/70B, not our API `create_client`.
  Swapping the model forfeits the right to cite their published 53% GSR.

The recursive tree logic is the easy part. The LIBERO action-space mapping and EM rebuild
are not, and cannot be shortcut.

**Decision rule:** if LIBERO is a *secondary* experiment → use Action-Sketcher, cite ReAcTree
in related work. If hierarchical-vs-hierarchical on LIBERO *is* the central claim → pay the
port cost. **Third option worth costing first:** run ReAcTree unmodified on VirtualHome and
port *our* method there instead — our planning layer is already environment-agnostic, so this
may be strictly less work, and it compares against their published numbers directly.

### The baseline we must build ourselves

None of the above is the **predefined fixed action library** condition Reviewer 1 asked for.
ViReSkill is closest but its library is learned online, not human-authored. Add a condition
where a hand-written H1/H2 library is frozen and the model may only dispatch into it — no
generation. Cheap to build: the compiler already validates dispatch against a hierarchy, so
we supply one instead of generating it. This isolates *generation* from *having a library*.

---

## Reporting

### Figures

1. **Success vs. horizon** — the money plot. Success rate (y) vs. problem size (x: Hanoi
   N=3..10, Checker Jumping N, LEXICON constraint count). One line per condition
   (`no-framework`, `inner-outer`, `h1-h2`, `complete-framework`) plus each baseline.
   Wilson intervals on every point.
2. **Cost–performance frontier** — success rate vs. total LLM calls (and tokens / USD).
   One point per method. Where hierarchy should win even when success ties; direct answer
   to Tree-Planner's efficiency claim.
3. **Compression ratio vs. horizon** — `expanded_h0_calls / high_level_calls` as N grows.
   Operationalizes "hierarchy". Should *increase* with N. Overlay mean hierarchy depth.
4. **Reuse vs. horizon** — dispatches per unique generated function. Overlay the
   predefined-library ablation. This is the figure that answers Reviewer 1.
5. **Failure-mode stacked bars** — illegal move / goal not reached / malformed output /
   hierarchy invalid / replans exhausted. Already have `illegal_reason`, `h1_valid`,
   `h2_valid`, `failed_move`. Shows *why* we win, not just that we do.

### Tables

- **A — Main results.** Methods × benchmarks. Per cell: success %, optimality %, mean moves
  vs. optimal. Bold best, ± CI half-width.
- **B — Ablation.** `no-framework` → `+inner-outer` → `+h1-h2` → `+dynamic hierarchy` →
  `+predefined library`. One row per component.
- **C — Cost.** Mean LLM calls, input/output/**cached** tokens, wall-clock, USD per task,
  broken out by stage. Few papers report cache-adjusted cost; `by_stage` and
  `cached_input_tokens` are already logged.
- **D — Reproducibility appendix.** Exact model snapshot IDs, temperature, reasoning effort,
  max tokens, seeds, trials per cell, retry/replan policy, prompt hashes. Numbered appendix
  table, not prose. This is the Reviewer 2 fix.

### Statistics

- **Wilson score intervals** on all success rates — better than normal approximation near
  0 and 1, which is where high-N cells live.
- **Paired design**: run every method on an identical instance set, then **McNemar's test**
  for paired binary outcomes. Much more power than unpaired, and free if the instance list
  is fixed.
- **Bootstrap CIs** for ratio metrics (compression, reuse) — not binomial.
- **Report n per cell in every caption.** Match LEXICON's convention (30 problems per
  constraint level, 150 per domain).
- **Holm–Bonferroni** when claiming significance across many method × size cells.

### Prerequisite work

`blocks_world_sweep.py` currently has `trials_per_cell: 1` and there is no
confidence-interval code anywhere in the harness. Single-trial points cannot support any of
the scaling claims above. **Add a `--trials` flag and Wilson intervals before running
anything else.** Also port the `--jobs` thread pool from `flat_hanoi_benchmark.py` to the
other runners — LEXICON at 150 problems × 4 conditions × several baselines is not viable
serially.

---

## Sources

- [LEXICON](https://proceedings.neurips.cc/paper_files/paper/2025/file/8ef63909f4bc1cedffb993c0e285a4e7-Paper-Datasets_and_Benchmarks_Track.pdf) (NeurIPS 2025 D&B)
- [SIMMER](https://arxiv.org/pdf/2606.14574) (COLM 2026) — rejected, see above
- [LLM+P](https://arxiv.org/pdf/2304.11477) · [code](https://github.com/Cranial-XIX/llm-pddl)
- [ProgPrompt](https://progprompt.github.io/) · [Tree-Planner](https://github.com/Aaron617/tree-planner)
- [ReAcTree](https://arxiv.org/abs/2511.02424) · [code](https://github.com/Choi-JaeWoo/ReAcTree)
- [Action-Sketcher](https://github.com/FlagOpen/Action-Sketcher) (CVPR 2026)
- [ViReSkill](https://arxiv.org/html/2509.24219) · [RePLan](https://arxiv.org/pdf/2401.04157) · [ReplanVLM](https://arxiv.org/abs/2407.21762)
- [LIBERO](https://arxiv.org/abs/2306.03310) (NeurIPS 2023 D&B)
