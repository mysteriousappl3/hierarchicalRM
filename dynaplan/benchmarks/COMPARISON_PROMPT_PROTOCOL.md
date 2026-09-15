# Controlled comparison prompt protocol

Protocol identifier: `shared-public-semantics-v3`

Status: **frozen for the official GPT-5.6 Luna / Claude Haiku 4.5 sweep.** Any
textual change to this policy or its corresponding constants requires a new
protocol version and a new registered campaign manifest.

This protocol is the registered model-facing layer for comparisons among the
direct condition and the mechanism-preserving baseline ports. It is separate
from claims about reproducing an upstream method's exact unpublished prompt.

## Shared optimization objective

Every method receives this exact sentence once in its public task body:

> Optimization objective: Among all valid plans, minimize the number of primitive actions in the final submitted plan.

Method-specific prompts may explain their planning mechanism, but may not
replace, weaken, or contradict that objective. The optimal length and oracle
plan remain evaluator-only.

## Shared public semantics

Every model call in every method receives the same benchmark-level semantic
contract for its domain. It contains no instance solution, optimal length,
evaluator result, or private state.

- Logistics receives explicit load, unload, drive, and fly preconditions and
  effects, including containment and location persistence.
- Blocksworld receives complete add/delete effects for pickup, putdown, stack,
  and unstack, including the convention that a held block is not clear.
- Flat Hanoi receives one exact `MoveHoop` transition definition using
  bottom-to-top stacks and stable ring identities.
- Both LexiCon domains receive identical finite-trace definitions for `always`,
  `sometime`, `at-most-once`, `sometime-before`, and `sometime-after`.

The strings are defined in `comparison_protocol.py` and kept byte-identical in
the DynaPlan copied runtime and the literature-baseline runtime. Method-specific
prompts may still describe the method's control flow, schemas, decomposition,
audit roles, search, or retrieval. DynaPlan's checkpoint review is therefore a
method mechanism, while the action and temporal meanings are shared.

## Flat-Hanoi fairness policy

Every comparison method receives the same:

- public initial state, goal state, ring sizes, legal-move rules, and peg names;
- primitive syntax: `MoveHoop(source_peg, target_peg)`;
- benchmark-level solved three-ring example (full tower `peg_0` to `peg_1`),
  expressed only with `MoveHoop` and verified absent from every frozen task;
- minimum-action objective above.

The frozen paper-derived Flat-Hanoi package uses numeric triples
`[disk_id, source_peg, destination_peg]`. That prompt remains preserved as a
reference artifact, but it is not mixed into the controlled method sweep. For
scoring only, the harness deterministically identifies the current top ring
selected by each `MoveHoop` call and converts the call to the benchmark's
numeric triple. This adapter does not search, repair, or expose oracle data.

AoT+ trajectory augmentation and ReAcTree episodic retrieval retain additional
examples because those are part of their declared inference mechanisms. Their
content comes from fixed public pools. Before retrieval, the runner compares a
name-normalized public `(initial, goal)` signature and removes any task
semantically identical to the current target. Consequently the selection is
target-aware solely for disjointness; it does not read a target solution or
optimal length. The pool, exclusions, selected examples, and protocol identifier
are recorded as method-specific context. Any paper table must disclose this
fact.

## LexiCon policy

The released LexiCon task text and domain rules are retained. The shared public
semantic contract and minimum-action sentence are appended idempotently to the
public task body for Base, DynaPlan, and every literature port. Exact action
parsing and compiled-PDDL scoring remain unchanged.

## Public task capability boundary

Planning strategies receive a frozen, slot-only public task object. Oracle
plans, optimal lengths, source directories, plan-file mappings, and provenance
helpers are absent fields—not nullable fields. LexiCon strategies that need
online replay or LLM+P compilation receive the public PDDL and compiler source
as in-memory text. Flat-Hanoi strategies receive only rings, pegs, rules,
initial state, and goal state. The private task remains owned by the runner and
is used only for final authoritative scoring and provenance records.

Preflight constructs each public view and fails if a forbidden field or a
dynamic attribute dictionary is present. Every completed native run also
records the boundary type and forbidden-field list; the unified audit requires
that record to match before marking setup as verified.

## Baseline-specific fairness corrections

- ReAcTree uses the pinned upstream control-flow depth default of 20. Model
  calls, decisions, and primitive attempts remain separately hard-bounded and
  are recorded per run.
- ADaPT intermediate children now declare grounded public-state completion
  conditions. A child succeeds only after deterministic replay establishes all
  conditions and shows non-vacuous progress; model self-report alone cannot
  accept a checkpoint. The root still requires the official final evaluator.

## Audit requirements

Each run records the protocol identifier, prompt hashes, shared objective, and
shared contract hash and, for Flat-Hanoi, the common representation and
solved-example hash. Exact stage prompts remain in the raw native log.
