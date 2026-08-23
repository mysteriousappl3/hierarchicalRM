# Dynamic Hierarchy Planner — Pipeline Refactor

> Design proposal for restructuring the planning pipeline around a **dynamically scaling
> hierarchy planner** ("dynamic action scaler"). This document captures the intended
> architecture, the responsibility split between components, and the correction/control
> flow. It is written to be assessed — i.e. to be checked for whether the plan is coherent,
> whether it fixes the problems it claims to, and whether the code changes can be made simpler.

---

## Motivation

The current pipeline entangles two things that should be separate: **planning a task** and
**composing the action hierarchies** used to solve it. Today the dynamic-hierarchy work sits
in the *pre-planning* stage as the `H2` action. That is wrong for a structural reason:

- Building a hierarchy requires *already knowing how to solve the task*.
- So the hierarchy module ends up doing planning-like reasoning — it becomes a second
  decision bot under a different name.
- That wastes tokens and adds an error-prone reasoning step that later has to be corrected.

Guiding principle for the refactor: **give each module a narrow, well-defined
responsibility.** Narrow scope reduces errors and keeps each model reasoning only within the
constraints and domain it is configured for.

Corollary: **planning comes first; hierarchies are downstream of a plan.** You cannot
construct hierarchies for a task you have not yet thought through, so the plan must be
produced before — and independently of — the hierarchy composition.

---

## Pipeline stages (unchanged skeleton)

1. **Pre-planning**
2. **Planning & correction**
3. **Execution**
4. **Post-action verification / task-completion status check**

The refactor changes *what lives in each stage* and *what each component does* — not the
overall skeleton.

---

## Components (after refactor)

### 1. Decision Bot — *planning only*

**Change:** decoupled down to a pure planner. It no longer produces action sequences.

- **Removed input:** the `H2` actions.
- **Removed output:** any sequence of concrete actions per subtask.
- **New output:** *only the plan* — the subtasks / checkpoints to hit for each task,
  expressed as **goal states + natural-language descriptions** (higher-level abstractions).
  Because it no longer sees `H2`, it physically cannot emit an action sequence, which is the
  intended behavior.
- **Retained input:** the `H1` (primitive) actions — but *only as grounding*, not to build
  actions from.

**Why keep `H1` if it can't use them to build actions:** the `H1` set tells the Decision Bot
the environment's constraints — these are the only *valid* primitive actions the simulator
works with. The bot is instructed to treat them as a validity boundary so that any subtask /
checkpoint it invents is reachable by *some* composition of those primitives, rather than
inventing subtasks that don't physically exist in the pipeline.

> Prompt intent: *"These are the only valid actions. You don't need to produce any of them —
> create abstractions or subtasks that help solve the task, but keep them grounded so they
> can be reached by some sequencing of these primitives."*

---

### 2. Dynamic Hierarchy Planner — *hierarchy composition*

*(Also referred to across the recordings as the **Dynamic Action Scaler**, **Dynamic
Hierarchy Analyzer**, and **Hierarchy Action Planner** — all the same refactored component,
i.e. the old `H2` role, rebranded and **moved from pre-planning into the planning stage**.)*

**Responsibility:** take the Decision Bot's plan and actually construct the dynamic
hierarchies that solve it.

- **Inputs:** the `H1` actions + the Decision Bot's plan (its subtasks/checkpoints).
- **Task:** compose dynamic hierarchies — `H2`, `H3`, … up to `Hn` — where each level is an
  abstraction / composition of one or more hierarchies below it (bottoming out at `H1`
  primitives).
- **The plan may be wrong — and that's acceptable.** For any given plan, the job is still to
  build hierarchies from it. Correctness of the plan is handled downstream by the Inner Bot,
  not here.

**Why this is the core idea (the "dynamic scaler"):** the pipeline is no longer constrained
to a fixed two-level hierarchy. It can build **n levels** of nested hierarchical actions —
arbitrarily complex actions composed of layered sub-actions — which is expected to unlock
significantly harder tasks.

**Desired behavior to prompt/test:**
- Let it decide how many subtasks a single hierarchy can cover. A single multi-hierarchy
  composition may legitimately solve one *or more* subtasks — tell it this is allowed.
- Encourage it to **balance sufficient depth against sufficient breadth** (phrasing TBD;
  this is behavior to elicit and test rather than hard-code).

**Optional input (last resort):** older `H2` actions from past experiments can be supplied as
examples. Hold these back by default — introduce them only if needed.

---

### 3. Inner Bot — *promoted to orchestrator / router*

Now that planning and hierarchy composition are two separate steps, the Inner Bot receives
**both** and acts as the orchestrator that decides *whether* there's a mistake, *where* it
lies, and *who* should fix it.

**Output — three fields** (analogous to the Outer Bot's verdict/reason, extended):

| Field | Values | Notes |
|---|---|---|
| **Mistake?** | yes / no (valid / invalid) | Is there a mistake at all? |
| **Who corrects it** | `Decision Bot` \| `Hierarchy Planner` \| `both` | Only set if a mistake exists |
| **Reason** | what actually went wrong | `NA` if no mistake |

If there is no mistake: `Mistake? = no`, `Who = NA`, `Reason = NA`.

The relevant component then receives the full Outer-Bot / Inner-Bot output and corrects only
the specific thing it's responsible for.

---

### 4. Outer Bot — *post-execution verification*

Unchanged in spirit: after execution it checks the result and catches mistakes. The
difference is **routing** — its findings are **not** handed straight to the Decision Bot.
They go to the **Inner Bot**, which re-diagnoses:

> *"The Outer Bot identified this. Based on that feedback — is the plan correct but the
> hierarchies wrong (something the previous Inner Bot pass missed)? Is the plan itself wrong?
> Or both?"*

This is the **same code flow** as the initial planning loop, so it can be implemented once
and reused.

---

## Correction / control flow

Routing is driven entirely by the Inner Bot's "who corrects it" field:

- **Decision Bot wrong**
  1. Give the plan back to the Decision Bot → re-plan.
  2. Run the Hierarchy Planner on the new plan.
  3. Run the Inner Bot again.

- **Hierarchy Planner only wrong**
  1. Keep the old plan.
  2. Give it to the Hierarchy Planner and instruct it to output *the same plan + the
     hierarchies*.
  3. Run the Inner Bot.

- **Both wrong** → **same path as "Decision Bot wrong."**
  Rationale: if the plan changes, the hierarchies are downstream and must change anyway, so
  no separate branch is needed. The code flow is identical, so it can be written that way.

**Happy path:** Inner Bot reports no mistake → **execute** → Outer Bot verifies → any
mistakes loop back through the Inner Bot via the same flow.

Each iteration **scales up / builds up** the hierarchies rather than discarding them.

---

## Running skills module (hierarchy reuse)

As the loop re-plans and rebuilds, keep a **running store of previously constructed,
validated hierarchies** — a "skills module" of useful hierarchical actions the model has
already built.

- On a subsequent run, only one or two of the previously used hierarchical actions may have
  been wrong. Tell the model: *"These previously generated hierarchies were valid — reuse
  some/all, or modify existing ones."*
- Feed the model **its own prior output** back and let it update it in real time — models are
  generally good at correcting and spotting mistakes when shown their previous response.

**Risk — tunnel vision:** don't let it lock onto a wrong solution set. Mitigate by prompting
it to explicitly choose among options:
- *"These work as-is — great."*
- *"Only a few actions need changing."*
- *"These mistakes recur across multiple hierarchical actions — recreate them from scratch."*

The point is to **force the model to make that decision** rather than defaulting to patching.

---

## Design goals

- **Narrow responsibilities per module** → fewer errors; each model reasons only within its
  configured constraints and domain.
- **Decouple planning from hierarchy composition** → plan first, compose hierarchies
  downstream.
- **n-level dynamic hierarchies** instead of a fixed two-level scheme → solve more complex,
  deeply nested actions.
- **Reusable correction loop** → initial planning and post-execution correction share one
  code path.
- **Generalizable framework** → a skills module the pipeline (or other pipelines) can use for
  other tasks requiring dynamic hierarchy composition or multi-step planning of complex
  tasks. The broader aim is to push the model's limits by giving it better structure to
  reason through and self-correct.

---

## Open questions & caveats (from the author)

- This is a **large refactor** with substantial functionality changes; feasibility of the
  effort itself is a consideration.
- Whether it works is genuinely **unknown** — the intent is to build it and run experiments
  over a few days.
- The **depth-vs-breadth** balancing behavior of the Hierarchy Planner is a hypothesis to
  test/prompt, not a solved design.
- The **tunnel-vision** mitigation for the skills-reuse step needs prompt design and
  validation.
