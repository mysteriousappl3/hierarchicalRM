# DynaPlan

Detailed architecture, bot contracts, design motivations, failure paths, and
the main system figure are in [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md).

Framework ID: `dynaplan_final_nlevel_hierarchy_v1_1`
Benchmark integration version: `59`

The frozen v1 setup report remains in
[`../../OFFICIAL_RUN_READINESS_REPORT.md`](../../OFFICIAL_RUN_READINESS_REPORT.md).
Its completed v1 results are not relabelled as v1.1 results; this revision
needs a fresh live smoke before any new paid sweep.

DynaPlan is a success-first, transactional N-level planning framework. It uses
one DecisionBot, one HierarchyPlanner role, one InnerBot semantic audit, and
one OuterBot review role. The online verifier is intentionally LLM-only: the
official deterministic task evaluator is withheld until the final candidate.

This directory is the official, self-contained architecture boundary. Its
runtime is copied into `runtime/`; execution does not import architecture code
from the development tree at `simmer-style-libero/benchmarking`.

## Execution flow

```text
public task (oracle fields removed)
  -> StateDescriptor + state-review InnerBot
  -> reusable H1 capability definitions
  -> DecisionBot subtasks and checkpoint contracts
  -> composed H1/H2/H3 hierarchy generation
  -> deterministic structural expansion to canonical H0 actions
  -> one InnerBot audit
       - forward action/state ledger
       - backward checkpoint/final-requirement support ledger
       - structured coverage certificate
       - earliest-failure coordinates drive a suffix-only repair transaction
  -> tentative shadow execution by subtask
  -> independent OuterBot review of exact actions, expanded H0, and
     public before/after shadow states
       - accepted candidate: commit transaction
       - rejected candidate: exact rollback and retry
  -> official deterministic final evaluator
```

## Components

| Component | Responsibility | Authority boundary |
|---|---|---|
| Public-task adapter | Converts Logistics, Blocksworld, or Flat-Hanoi into a frozen slot-only planning object | Oracle plans, optimal lengths, paths, and provenance helpers are absent fields |
| StateDescriptor | Converts the public initial state and requested goal into the framework state contract | Model-generated when `fixed_goal=False`; structurally validated before reuse |
| State-review InnerBot | Checks whether StateDescriptor captured the visible task | LLM judgment only |
| H1 source | Supplies reusable primitive capability definitions | Cached only after structural validation |
| DecisionBot | Decomposes the task into ordered subtasks and complete checkpoint goal states | Includes the success-first checkpoint and temporal review instructions |
| Checkpoint-tag normalizer | Repairs only an unambiguous `end_subtask_N` closer inside an already delimited `start_subtask_goalstate_N` block | Syntax-only; bodies, IDs, semantics, and downstream validators remain unchanged |
| Localized repair controller | Preserves numbered blocks before the earliest Decision-validator or InnerBot-audit failure and regenerates only the suffix | InnerBot localization is advisory, never deterministic authority; every merge is fully re-audited from the frozen candidate start and falls back to full regeneration after two repeats |
| HierarchyPlanner | Composes H1/H2/H3 calls for each DecisionBot subtask | Can regenerate a failed suffix while retaining eligible upstream artifacts |
| Structural compiler | Expands composed hierarchy calls into canonical H0 calls and semantic actions | Proves expansion and syntax only; it does not prove applicability or goals |
| InnerBot execution audit | Simulates the candidate forward and traces every checkpoint/final requirement backward to support | Strict JSON and evidence coverage are enforced, but witness truth is still an LLM judgment |
| Transaction controller | Executes a candidate against a private shadow-state copy | Rejection restores state, action list, revision, and digest; a false LLM acceptance can still commit an invalid candidate |
| OuterBot | Independently reviews each exact subtask trace and final-subtask marker without seeing InnerBot's verdict | Second LLM line of defense; correlated semantic errors remain possible |
| Final evaluator | Replays the submitted primitive plan with the benchmark's deterministic scorer | Invoked once inside DynaPlan after planning; the unified harness may independently rescore the persisted output for audit agreement |

## v1.1 behavior

- Parent architecture: `shared_nlevel_v5_llm_only_execution_audit_v3_3_success_first`.
- `max_replans=15`, `reuse_h1=True`, `fixed_goal=False`.
- One InnerBot execution-audit call per complete candidate; no second critic.
- Required structured evidence for all public final goals and temporal
  constraints.
- Continue replanning after a clean transactional rollback, including a
  candidate-level `NON-RECOVERABLE` judgment.
- Exact OuterBot trace handoff across all three domains.
- Unambiguous DecisionBot checkpoint-closing-tag normalization.
- Natural-language action verbs are permitted in Decision descriptions while
  actual `operator(...)` and `(operator ...)` calls remain prohibited.
- Earliest-failing Decision and hierarchy suffix repair, including an
  InnerBot recheck after an OuterBot rejection, with exact numbered-block
  preservation, full frozen-start re-audit, and full-regeneration fallback
  after two repeated localized failures.
- No exact PDDL, Hanoi simulator, typed state machine, or other deterministic
  semantic feedback during planning.

## Source layout

- `benchmark.py` — official subprocess-isolated entry point and task/provider
  bridge.
- `framework.json` — machine-readable framework registration.
- `runtime/dynaplan_nlevel_checkpoint_normalization.py` — conservative tag
  normalization.
- `runtime/dynaplan_nlevel_localized_repair.py` — Decision suffix transaction
  and unverified audit-localization contract.
- `runtime/dynaplan_nlevel_adapter.py` — the three versioned DynaPlan adapters.
- `runtime/dynaplan_nlevel_pipeline.py` — architecture enforcement and
  DynaPlan telemetry.
- `runtime/shared_nlevel_execution_audit_v3_3_adapter.py` — success-first
  checkpoint, public-rule, and temporal prompts.
- `runtime/shared_nlevel_execution_audit_v3_3_evidence.py` — strict evidence
  schema and deterministic coverage checks.
- `runtime/shared_nlevel_execution_audit_v3_1_adapter.py` — exact OuterBot
  trace handoff.
- `runtime/shared_nlevel_verified_repair_pipeline.py` — shared N-level cache,
  retry, transaction, rollback, and final-score controller.
- `runtime/shared_nlevel_pipeline.py` — common hierarchy types, parsing, and
  structural expansion.
- `runtime/shared_nlevel_{lexicon,blocksworld,flat_hanoi}.py` — domain
  adapters and public state/action conventions.
- `runtime/models.py` — hosted model clients and exact prompt/call/usage
  ledger.
- `runtime/n_hirearchy_v5_5/rules.py` and `rules.schema.json` — copied rule
  types required by an inherited adapter module; DynaPlan's LLM-only path does
  not activate the prompt-induced deterministic interpreter.

The copied runtime contains supporting inherited modules because the Python
dependency graph is transitive. Presence in the copy does not mean every
ablation is activated; `dynaplan_nlevel_adapter.py` and
`dynaplan_nlevel_pipeline.py` select the registered path.

## Controlled-comparison contract

Under frozen protocol `shared-public-semantics-v3`, every Base, DynaPlan, and
literature-port model call receives the exact same domain action semantics,
LexiCon temporal definitions, and minimum-action objective. Every Flat-Hanoi
call also receives the same target-disjoint solved three-ring example and
`MoveHoop(source_peg, target_peg)` representation. The wrappers verify that the
shared contract appears exactly once and record its digest.

DynaPlan retains method-specific control and audit prompts, checkpoint
contracts, hierarchy composition, and deterministic structural H0 expansion.
Those are the architecture being evaluated, not a private task hint. No task
ID, target plan, oracle action sequence, or optimal length is hardcoded into
the planner.

The method is not compute-matched to one-call baselines: it can use many more
calls and tokens. Official reporting must therefore include validity,
optimality, calls, tokens, and cost—not validity alone.

## Commands

Unified offline preflight for every registered method:

```bash
python benchmarks/benchmark.py \
  --baseline all --benchmark all \
  --constraints 1 --lexicon-id 1 \
  --hanoi-task paper-baseline-v1-n3-0017
```

DynaPlan/OpenAI smoke trio:

```bash
python benchmarks/benchmark.py \
  --baseline dynaplan --benchmark all \
  --constraints 1 --lexicon-id 1 \
  --hanoi-task paper-baseline-v1-n3-0017 \
  --provider openai --model gpt-5.6-luna --reasoning medium \
  --max-output-tokens 8192 --execute --run-id <unique-id>
```

DynaPlan/Claude Haiku 4.5 smoke trio:

```bash
python benchmarks/benchmark.py \
  --baseline dynaplan --benchmark all \
  --constraints 1 --lexicon-id 1 \
  --hanoi-task paper-baseline-v1-n3-0017 \
  --provider anthropic --model claude-haiku-4-5-20251001 \
  --reasoning medium --anthropic-thinking-budget 4096 \
  --max-output-tokens 8192 --execute --run-id <unique-id>
```

Omitting `--execute` never contacts a model provider. The official sweep uses
three preregistered Flat-Hanoi instances per ring count and three matched
LexiCon worlds per constraint level; see the readiness report and
`../../benchmarks/official_sweep_v1.json` before paid execution.
