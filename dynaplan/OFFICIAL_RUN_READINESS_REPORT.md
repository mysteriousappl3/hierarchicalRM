# DynaPlan official-sweep readiness report

Date: 2026-09-15  
Framework: `dynaplan_final_nlevel_hierarchy_v1`  
Comparison protocol: `shared-public-semantics-v3`

## Decision

**The official campaign is registered and ready, but the final paid sweep has
not started.** The source tree, task matrix, model configurations, comparison
prompt policy, resumable launcher, and aggregate reporter are frozen together
under the `official-sweep-v1` Git tag. The registered manifest records their
exact commit, tag, hashes, interpreter, and all 720 conditions before any paid
call.

This report intentionally separates setup validity from model performance. A
smoke can finish correctly and return an invalid plan; that is a valid
benchmark outcome, not an integration failure.

## Frozen sweep

| Dimension | Registered choice |
|---|---|
| Methods | Base, DynaPlan, AdaPlan-H, TDP, ADaPT, ReAcTree, AoT+, LLM+P |
| Models | `gpt-5.6-luna` at medium reasoning; `claude-haiku-4-5-20251001` with 4,096 thinking tokens |
| Output cap | 8,192 tokens per call for both models |
| Flat Hanoi | 3 frozen instances at each `n={3,4,5,6,7}` = 15 |
| Logistics | 3 matched worlds at each `c={1,3,5,7,10}` = 15 |
| Blocksworld | 3 matched seeds at each `c={1,3,5,7,10}` = 15 |
| Per method/model | 45 conditions |
| Overall | 8 methods × 2 models × 45 tasks = **720 conditions** |

“Three runs” means three distinct preregistered task instances per difficulty
stratum, each with one fresh hosted-model rollout. It does not mean three
stochastic reruns of the same task. Hosted generations are unseeded.

The exact coordinates and outcome-blind selection rules are in
`../paper-tables/runs.md` and the machine-readable registry is
`benchmarks/official_sweep_v1.json`.

### Flat-Hanoi coordinates

| Rings | Registered tasks (oracle length, evaluator-only) |
|---:|---|
| 3 | `n3-0032` (1), `n3-0004` (5), `n3-0013` (6) |
| 4 | `n4-0018` (3), `n4-0015` (7), `n4-0013` (13) |
| 5 | `n5-0008` (5), `n5-0003` (18), `n5-0012` (28) |
| 6 | `n6-0026` (11), `n6-0019` (35), `n6-0017` (54) |
| 7 | `n7-0000` (22), `n7-0029` (60), `n7-0010` (102) |

### LexiCon coordinates

Logistics uses the three lexicographically earliest complete underlying-world
SHA-256 chains. Blocksworld uses the three smallest embedded generation seeds
that occur at every registered constraint level. This selection was performed
without model outcomes.

| Domain / chain | `c=1` | `c=3` | `c=5` | `c=7` | `c=10` |
|---|---:|---:|---:|---:|---:|
| Logistics chain 1 | 14 | 18 | 7 | 2 | 2 |
| Logistics chain 2 | 16 | 20 | 9 | 4 | 3 |
| Logistics chain 3 | 19 | 23 | 12 | 6 | 4 |
| Blocksworld seed 2002 | 14 | 4 | 12 | 2 | 12 |
| Blocksworld seed 2005 | 17 | 6 | 14 | 3 | 13 |
| Blocksworld seed 2006 | 18 | 7 | 15 | 4 | 14 |

## Prompt-fairness freeze

The earlier asymmetry has been removed at the benchmark task layer. Every
model call for Base, DynaPlan, and all six literature ports now receives the
same domain contract and optimization objective:

- Logistics: exact public load, unload, drive, and fly preconditions/effects.
- Blocksworld: exact public pickup, putdown, stack, and unstack
  preconditions/effects, including the held-block convention.
- Flat Hanoi: bottom-to-top stack convention and exact `MoveHoop` transition.
- Both LexiCon domains: the same finite-trace definitions of `always`,
  `sometime`, `at-most-once`, `sometime-before`, and `sometime-after`.
- All domains: the same instruction to minimize primitive actions after
  satisfying validity.

Those strings are byte-identical in the DynaPlan and comparison runtimes, are
added idempotently, and are identified by a recorded SHA-256 digest. Changing
them requires a new protocol version and a new campaign registration.

Method-specific control remains method-specific: decomposition prompts,
schemas, memory, retrieval, verifier/auditor roles, repair policy, and search
policy are part of the method being compared.

## Provider readiness

Claude is enabled for Base and all six literature ports, not only DynaPlan.
Anthropic rejects several JSON-Schema validation keywords accepted by the
OpenAI endpoint. The provider adapter now:

1. converts unsupported validation annotations into model-visible schema
   descriptions;
2. normalizes mixed nullable enums to provider-compatible `anyOf` branches;
3. retains the original deterministic local parser as the acceptance
   authority; and
4. records the adapter version in every Claude artifact.

This is a provider-compatibility translation of the same output contract, not
a method-specific prompt change. It fixed the two genuine smoke-infrastructure
failures: TDP's `node_...` identifier constraint and ReAcTree's nullable
control enum. ReAcTree then completed Flat Hanoi with a valid 5-move plan, and
TDP completed Blocksworld with an optimal 3-action plan. AoT+ Logistics also
completed under the fixed 8,192-token cap; its resulting invalid plan is a
model outcome.

Earlier qualifying DynaPlan hosted smokes covered all three domains on both
models:

| Model | Setup | Valid | Optimal | Calls | Tokens |
|---|---:|---:|---:|---:|---:|
| GPT-5.6 Luna | 3/3 | 3/3 | 2/3 | 34 | 142,385 |
| Claude Haiku 4.5 thinking | 3/3 | 2/3 | 2/3 | 53 | 327,167 |

The GPT literature-port smokes cover all 18 method/domain cells. The Claude
literature campaign plus targeted compatibility reruns cover the same matrix;
these diagnostics use excluded tasks (`c=1,id=1` and `n3-0017`) and are not
part of the official 720-condition denominator.

## Verification completed

- 126 focused comparison, provider, baseline, task-boundary, schema, scoring,
  and launcher tests pass.
- The unified offline self-test passes.
- All eight methods preflight successfully on all three task boundaries.
- Matrix validation confirms 720 unique conditions: 360 per provider, 90 per
  method, and 240 per benchmark.
- All registered LexiCon chain hashes and Flat-Hanoi task IDs resolve.
- The launcher is register-before-execute, source/hash-drift detecting,
  resumable, non-overwriting, filterable, and parallel-capable.
- The reporter excludes incomplete conditions from denominators and reports
  setup, validity, optimality, calls, tokens, lengths, and artifacts.

## Remaining methodological advantages and limitations

The comparison is much fairer, but not advantage-free:

1. **DynaPlan is domain-adapted.** Its adapters contain domain-level hierarchy
   mappings, state conventions, checkpoint/audit schemas, and deterministic H0
   expansion. They contain no task IDs, target plans, or oracle lengths. The
   public action/temporal semantics are now shared; DynaPlan's decomposition and
   audit machinery remains its intended architectural advantage.

2. **DynaPlan has a compute advantage over Base.** It may make many calls and
   repairs while Base makes one. Calls, exact token categories, latency, and
   cost must be reported beside success; this is not a compute-matched study.

3. **LLM+P is tool-assisted and uses exact PDDL search.** It should be shown as
   a separate upper-bound-style condition, not described as LLM-only or
   directly comparable verification.

4. **AoT+ and ReAcTree retain method-intrinsic examples/retrieval.** Their
   pools are fixed and target-disjoint, but this extra context is still an
   advantage that must be disclosed.

5. **The literature methods are mechanism-preserving cross-domain ports.** The
   pinned upstream repositories are provenance references; the adapters are
   not upstream programs run unchanged. TDP has no public implementation and
   follows its published prompts/algorithm.

6. **Reasoning settings are provider-specific, not compute-equivalent.** GPT
   medium reasoning and Claude's 4,096-token extended-thinking budget are the
   registered settings, but they are not claimed to represent equal internal
   compute.

7. **The checkpoint-tag normalizer is benchmark-informed engineering.** It
   only repairs a single unambiguous syntactic closing-tag mismatch and then
   reruns every original structural/semantic check. It is domain-independent
   and cannot make an invalid checkpoint valid, but its provenance should be
   disclosed.

No evaluated task plan, goal-specific branch, oracle action sequence, or
optimal length is present in model-visible planning code. Private oracle data
is structurally absent from public task objects and is used only by the final
evaluator and offline rescore.

## Operational procedure

The final sweep must not be launched from an edited checkout. Registration is
complete; review `benchmarks/results/official_two_model_sweep_registered_v1/
registered_manifest.json`, then resume in bounded provider/method/benchmark
batches:

```bash
cd /home/medcvr/hamza-hirearchy-tests/dynaplan

# Paid execution only after reviewing registered_manifest.json.
../simmer-style-libero/.venv/bin/python benchmarks/official_sweep.py \
  --execute --jobs 3 --provider openai
../simmer-style-libero/.venv/bin/python benchmarks/official_sweep.py \
  --execute --jobs 3 --provider anthropic

# Offline progress/final report.
../simmer-style-libero/.venv/bin/python benchmarks/official_sweep.py --report
```

The launcher skips completed conditions, assigns a new attempt directory to
an interrupted condition, and never overwrites a prior artifact. Diagnostic
and setup runs remain outside the registered campaign directory.
