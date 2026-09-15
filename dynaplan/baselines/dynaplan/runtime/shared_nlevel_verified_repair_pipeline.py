"""Domain-generic verified prefix/suffix repair for the shared N-level architecture.

V5 preserves v3's validated-artifact cache and dependency-aware invalidation,
then makes v4's useful controller behavior explicit and domain neutral:

* a typed adapter protocol constructs public failure certificates and renders
  domain-specific suffix patches;
* the pipeline, rather than an adapter-local monkeypatch, freezes and verifies
  checkpoint-valid prefix blocks;
* deterministic projection is authoritative over advisory Router/OuterBot
  verdicts; and
* the shortest complete deterministically valid candidate is retained as an
  incumbent and can be restored after a later model-side failure.

The registered v2/v3/v4 modules are intentionally not imported for control
flow and remain byte-for-byte untouched.  The implementation below began from
the v3 loop so its cache and invalidation semantics stay directly comparable.

Cache scope is one benchmark rollout.  State-scoped artifacts are keyed by a
monotonic revision that advances after every committed primitive action, so a
public-state self-loop cannot hide temporal-history changes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple, runtime_checkable

import shared_nlevel_pipeline as v2
from shared_nlevel_pipeline import (
    ArtifactCheck,
    FinalScoreContext,
    LocalArtifact,
    OWNER_BOTH,
    OWNER_DECISION,
    OWNER_HIERARCHY,
    SharedLoopResult,
    StageRequest,
)


PIPELINE_VERSION = "shared_nlevel_v5_verified_prefix_repair"


@dataclass(frozen=True)
class RepairCandidate:
    """A structurally compiled hierarchy eligible for transactional repair."""

    serial: int
    state_revision: int
    h1_output: str
    decision_output: str
    decision: object
    output: str
    hierarchy: object


@dataclass(frozen=True)
class RepairContext:
    """Domain-neutral description of one verified-prefix suffix repair."""

    candidate: RepairCandidate
    projection: object
    certificate: Mapping[str, object]
    preserved_subtask_indices: Tuple[int, ...]
    repair_subtask_indices: Tuple[int, ...]
    failure_count: int
    backtracked: bool = False


@dataclass(frozen=True)
class ValidIncumbent:
    """Shortest complete candidate accepted by deterministic projection."""

    candidate_serial: int
    action_count: int
    state_revision: int
    final_state: object
    executed_actions: Tuple[object, ...]
    high_level_plan: Tuple[str, ...]
    expanded_h0_plan: Tuple[str, ...]
    score_context: FinalScoreContext
    outputs: Mapping[str, object]


@runtime_checkable
class VerifiedRepairAdapter(Protocol):
    """Extra hooks a domain supplies to the generic v5 controller.

    The engine owns retry policy, prefix selection, semantic prefix equality,
    incumbent selection, and deterministic authority.  An adapter owns
    public diagnostic sanitization, its hierarchy text grammar, full-state
    equivalence, and domain-specific Decision-certificate augmentation.
    """

    pipeline_version: str
    checkpoint_local_repair_limit: int

    def states_equivalent(
        self,
        task: object,
        left: object,
        right: object,
    ) -> bool: ...

    def build_repair_certificate(
        self,
        task: object,
        current_state: object,
        decision: object,
        hierarchy: object,
        projection: object,
        preserved_subtask_indices: Sequence[int],
        repair_subtask_indices: Sequence[int],
    ) -> Mapping[str, object]: ...

    def hierarchy_repair_request(
        self,
        task: object,
        current_state: object,
        scene: object,
        state_output: object,
        h1_output: str,
        decision_output: str,
        candidate_output: str,
        certificate: Mapping[str, object],
        preserved_subtask_indices: Sequence[int],
        repair_subtask_indices: Sequence[int],
        feedback: str,
        include_code_block: bool,
    ) -> StageRequest: ...

    def merge_hierarchy_repair(
        self,
        task: object,
        candidate_output: str,
        patch_output: str,
        preserved_subtask_indices: Sequence[int],
        repair_subtask_indices: Sequence[int],
    ) -> ArtifactCheck: ...

    def augment_decision_repair_request(
        self,
        task: object,
        current_state: object,
        base_request: StageRequest,
        certificate: Mapping[str, object],
    ) -> StageRequest: ...


def _validate_repair_adapter(adapter: object) -> None:
    if getattr(adapter, "pipeline_version", None) != PIPELINE_VERSION:
        raise ValueError(
            f"{PIPELINE_VERSION} requires a versioned verified-repair adapter"
        )
    required = (
        "build_repair_certificate",
        "hierarchy_repair_request",
        "merge_hierarchy_repair",
        "augment_decision_repair_request",
        "states_equivalent",
    )
    missing = [name for name in required if not callable(getattr(adapter, name, None))]
    if missing:
        raise TypeError("verified-repair adapter is missing hooks: " + ", ".join(missing))


def _same_subtask(left: object, right: object) -> bool:
    """Compare the executable semantics of a frozen compiled subtask."""

    return bool(
        getattr(left, "index", None) == getattr(right, "index", None)
        and getattr(left, "top_level_calls", None)
        == getattr(right, "top_level_calls", None)
        and getattr(left, "h0_calls", None) == getattr(right, "h0_calls", None)
        and getattr(left, "actions", None) == getattr(right, "actions", None)
    )


def _score_success(score: object) -> bool:
    if isinstance(score, Mapping):
        if "valid" in score:
            return bool(score["valid"])
        if "solved" in score:
            return bool(score["solved"])
    for name in ("valid", "solved", "success"):
        if hasattr(score, name):
            return bool(getattr(score, name))
    return False


def _h1_check(adapter: object, task: object, output: object) -> Optional[ArtifactCheck]:
    """Return a standalone H1 check when the adapter exposes that contract."""

    validator = getattr(adapter, "validate_h1", None)
    if not callable(validator):
        return None
    return v2._coerce_artifact_check(validator(task, output))


def _canonical_h1(
    adapter: object,
    task: object,
    output: object,
    check: ArtifactCheck,
) -> object:
    """Return a state-independent H1 representation when the adapter can."""

    canonicalizer = getattr(adapter, "canonicalize_h1", None)
    if not callable(canonicalizer):
        return output
    canonical = canonicalizer(task, output, check)
    if not isinstance(canonical, str) or not canonical.strip():
        raise ValueError("adapter.canonicalize_h1() must return non-empty text")
    return canonical


def _canonical_decision(
    adapter: object,
    task: object,
    output: object,
    check: ArtifactCheck,
) -> object:
    """Return a validated Decision representation when the adapter can.

    The hook is deliberately optional so existing variants retain byte-for-byte
    Decision handling.  A versioned adapter may use it for a conservative,
    syntax-only canonicalization after its ordinary parser has accepted the
    result.
    """

    canonicalizer = getattr(adapter, "canonicalize_decision", None)
    if not callable(canonicalizer):
        return output
    canonical = canonicalizer(task, output, check)
    if not isinstance(canonical, str) or not canonical.strip():
        raise ValueError("adapter.canonicalize_decision() must return non-empty text")
    return canonical


def _append_stage_feedback(request: StageRequest, feedback: str) -> StageRequest:
    """Ensure adapters that ignore their feedback parameter still receive it."""

    if not feedback:
        return request
    marker = "STAGE-LOCAL VALIDATION FEEDBACK:"
    return replace(
        request,
        prompt=f"{request.prompt.rstrip()}\n\n{marker}\n{feedback}\n",
    )


def run_shared_nlevel_loop(
    task: object,
    client: object,
    adapter: object,
    *,
    fixed_goal: bool,
    max_tokens: int,
    max_replans: int,
    reuse_h1: bool,
    include_code_block: bool,
    reasoning_effort: Optional[str] = None,
    final_score_task: Optional[object] = None,
) -> SharedLoopResult:
    """Run N-level planning with validated artifact caches and local repairs.

    ``max_replans`` retains its v2 meaning: it is the number of correction
    rounds after the first pass.  A rejected stage consumes one round, but it
    does not trigger calls to downstream stages and does not discard unrelated
    validated artifacts.  ``reuse_h1`` must be true because validated H1 reuse
    is an identifying part of this architecture version.
    """

    if max_replans < 0:
        raise ValueError("max_replans must be non-negative")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if not reuse_h1:
        raise ValueError(
            f"{PIPELINE_VERSION} requires reuse_h1=True; only a "
            "validated H1 artifact is cached"
        )
    _validate_repair_adapter(adapter)
    # V5 is deterministic-authoritative by default.  The explicit
    # ``online_verification_authoritative=False`` hook exists only for the
    # registered v5-LLM-only ablation: it preserves the controller and model
    # stages while withholding semantic verifier feedback until final score.
    online_verification_authoritative = bool(
        getattr(adapter, "online_verification_authoritative", True)
    )
    # LLM-only execution auditors inspect a complete candidate before the
    # controller executes it.  They cannot establish a verified prefix, so a
    # rejected candidate must be treated as one transaction rather than
    # leaking its unchecked shadow effects into the next repair round.
    transactional_candidate_execution = bool(
        getattr(adapter, "transactional_candidate_execution", False)
    )
    # An offline LLM-only candidate cannot irreversibly damage the task after
    # its complete shadow execution has been rolled back.  New ablations may
    # opt into treating NON-RECOVERABLE as a candidate-level rejection.  Keep
    # the historical stopping policy for all other adapters and for any mode
    # without transactional isolation.
    continue_after_rollback = bool(
        getattr(adapter, "continue_after_rollback", False)
        and transactional_candidate_execution
        and not online_verification_authoritative
    )

    current_state = adapter.initial_state(task)
    state_revision = 0
    executed_actions: List[object] = []
    high_level_plan: List[str] = []
    expanded_h0_plan: List[str] = []
    parse_errors: List[str] = []
    attempts: List[Dict[str, object]] = []
    router_attributions: List[str] = []

    model_call_count = 0
    model_calls_by_stage: Dict[str, int] = {}
    stage_counts = v2.new_stage_counts()

    total_top_level_count = 0
    total_h0_count = 0
    level_totals: Dict[int, int] = {}
    max_level_seen = 0
    base_valid_any = False
    hierarchy_valid_any = False
    last_mapping_count_by_level: Dict[int, int] = {}
    hierarchy_errors_seen: List[str] = []
    last_illegal_reason: Optional[str] = None
    termination_reason = "max_replans_exhausted"
    last_outputs: Dict[str, object] = {}

    # All cache entries are rollout-local.  H1 is task-scoped; every other
    # model artifact is tied to the monotonic state revision.
    cache: Dict[str, object] = {
        "scene_revision": None,
        "scene": None,
        "descriptor_revision": None,
        "state_output": None,
        "descriptor_check": None,
        "descriptor_model_backed": False,
        "state_verified_revision": None,
        "innerbot_state_output": None,
        "h1_output": None,
        "h1_check": None,
        "h1_model_backed": False,
        "decision_revision": None,
        "decision_output": None,
        "decision": None,
        "hierarchy_revision": None,
        "hierarchy_output": None,
        "hierarchy": None,
        "projection": None,
    }
    feedback_by_stage: Dict[str, str] = {
        "state_descriptor": "",
        "innerbot_state": "",
        "h1": "",
        "decision": "",
        "hierarchy_planner": "",
        "innerbot_router": "",
        "outerbot": "",
    }
    # Rejected candidates are diagnostic context only.  They are never read as
    # valid artifacts or used to bypass validation.
    rejected_outputs: Dict[str, object] = {"state_descriptor": None}
    cache_hits: Dict[str, int] = {
        "scene": 0,
        "state_descriptor": 0,
        "innerbot_state": 0,
        "h1": 0,
        "decision": 0,
        "hierarchy": 0,
        "projection": 0,
    }
    model_call_cache_hits: Dict[str, int] = {
        "state_descriptor": 0,
        "innerbot_state": 0,
        "h1": 0,
        "decision": 0,
        "hierarchy": 0,
    }
    invalidation_counts: Dict[str, int] = {
        "state": 0,
        "state_descriptor": 0,
        "innerbot_state": 0,
        "h1": 0,
        "decision": 0,
        "hierarchy": 0,
    }
    invalidation_log: List[Dict[str, object]] = []

    candidate: Optional[RepairCandidate] = None
    pending_repair: Optional[RepairContext] = None
    valid_incumbent: Optional[ValidIncumbent] = None
    incumbent_candidate_serials: set[int] = set()
    candidate_serial = 0
    last_failure_signature: Optional[Tuple[object, ...]] = None
    same_failure_count = 0
    decision_repair_certificate: Optional[Mapping[str, object]] = None
    repair_telemetry: Dict[str, object] = {
        "localized_patch_request_count": 0,
        "localized_patch_accept_count": 0,
        "localized_patch_reject_count": 0,
        "full_regeneration_fallback_count": 0,
        "preserved_subtask_count_total": 0,
        "backtrack_count": 0,
        "checkpoint_local_repair_count": 0,
        "checkpoint_decision_escalation_count": 0,
        "failure_certificates": [],
        "router_validity_override_count": 0,
        "outerbot_validity_override_count": 0,
        "valid_incumbent_count": 0,
        "valid_incumbent_update_count": 0,
        "valid_incumbent_restored": False,
        "transactional_candidate_execution": transactional_candidate_execution,
        "candidate_transaction_commit_count": 0,
        "candidate_transaction_rollback_count": 0,
        "continue_after_rollback": continue_after_rollback,
        "candidate_rollback_continuation_count": 0,
    }

    def call(request: StageRequest) -> str:
        nonlocal model_call_count
        model_call_count += 1
        model_calls_by_stage[request.stage] = (
            model_calls_by_stage.get(request.stage, 0) + 1
        )
        effort_resolver = getattr(adapter, "reasoning_effort_for", None)
        effort = (
            effort_resolver(request.stage, reasoning_effort)
            if callable(effort_resolver)
            else reasoning_effort
        )
        return v2._call_client(client, request, max_tokens, effort)

    def route(owner: object) -> str:
        canonical = v2._canonical_owner(owner)
        router_attributions.append(canonical)
        return canonical

    def log_invalidation(scope: str, reason: str, had_value: bool) -> None:
        if not had_value:
            return
        invalidation_counts[scope] += 1
        invalidation_log.append(
            {
                "state_revision": state_revision,
                "scope": scope,
                "reason": reason,
            }
        )

    def invalidate_hierarchy(reason: str) -> None:
        had_value = any(
            cache[key] is not None
            for key in ("hierarchy_output", "hierarchy", "projection")
        )
        cache["hierarchy_revision"] = None
        cache["hierarchy_output"] = None
        cache["hierarchy"] = None
        cache["projection"] = None
        feedback_by_stage["hierarchy_planner"] = ""
        log_invalidation("hierarchy", reason, had_value)

    def invalidate_decision(reason: str) -> None:
        nonlocal candidate, pending_repair
        had_value = cache["decision_output"] is not None or cache["decision"] is not None
        cache["decision_revision"] = None
        cache["decision_output"] = None
        cache["decision"] = None
        feedback_by_stage["decision"] = ""
        log_invalidation("decision", reason, had_value)
        candidate = None
        pending_repair = None
        invalidate_hierarchy(reason)

    def invalidate_h1(reason: str) -> None:
        had_value = cache["h1_output"] is not None or cache["h1_check"] is not None
        cache["h1_output"] = None
        cache["h1_check"] = None
        cache["h1_model_backed"] = False
        feedback_by_stage["h1"] = ""
        log_invalidation("h1", reason, had_value)
        invalidate_decision(reason)

    def invalidate_inner(reason: str) -> None:
        had_value = (
            cache["state_verified_revision"] is not None
            or cache["innerbot_state_output"] is not None
        )
        cache["state_verified_revision"] = None
        cache["innerbot_state_output"] = None
        feedback_by_stage["innerbot_state"] = ""
        log_invalidation("innerbot_state", reason, had_value)
        invalidate_decision(reason)

    def invalidate_descriptor(reason: str) -> None:
        had_value = any(
            cache[key] is not None
            for key in ("state_output", "descriptor_check")
        )
        cache["descriptor_revision"] = None
        cache["state_output"] = None
        cache["descriptor_check"] = None
        cache["descriptor_model_backed"] = False
        feedback_by_stage["state_descriptor"] = ""
        log_invalidation("state_descriptor", reason, had_value)
        invalidate_inner(reason)

    def invalidate_state(reason: str) -> None:
        had_value = cache["scene"] is not None or cache["descriptor_revision"] is not None
        cache["scene_revision"] = None
        cache["scene"] = None
        rejected_outputs["state_descriptor"] = None
        log_invalidation("state", reason, had_value)
        invalidate_descriptor(reason)

    def set_owner_feedback(owner: str, reason: str) -> None:
        target = (
            "hierarchy_planner" if owner == OWNER_HIERARCHY else "decision"
        )
        feedback_by_stage[target] = reason

    def invalidate_owner(owner: object, reason: str) -> str:
        canonical = route(owner)
        if canonical == OWNER_HIERARCHY:
            invalidate_hierarchy(reason)
        else:
            # BOTH starts at the earliest implicated planning stage.  H1 and
            # the validated state bundle are not discarded without evidence.
            invalidate_decision(reason)
        set_owner_feedback(canonical, reason)
        return canonical

    def start_stage() -> str:
        if cache["descriptor_revision"] != state_revision:
            return "state_descriptor"
        if cache["state_verified_revision"] != state_revision:
            return "innerbot_state"
        if cache["h1_output"] is None:
            return "h1"
        if cache["decision_revision"] != state_revision:
            return "decision"
        if cache["hierarchy_revision"] != state_revision:
            return "hierarchy_planner"
        return "innerbot_router"

    def failure_attempt(
        attempt: Dict[str, object],
        *,
        stage: str,
        message: str,
        owner: Optional[str] = None,
    ) -> None:
        attempt["failed_stage"] = stage
        attempt["owner"] = owner or stage
        attempt["verdict"] = "REPLAN"
        attempt["feedback_out"] = message
        attempt["output_state"] = adapter.snapshot_state(task, current_state)
        stage_outputs = attempt.get("stage_outputs")
        if isinstance(stage_outputs, Mapping):
            last_outputs.update(stage_outputs)
        attempts.append(attempt)

    def capture_execution_transaction() -> Dict[str, object]:
        """Snapshot every final-score-relevant value before candidate execution."""

        return {
            "state": adapter.copy_state(task, current_state),
            "state_revision": state_revision,
            "executed_actions": tuple(executed_actions),
            "high_level_plan": tuple(high_level_plan),
            "expanded_h0_plan": tuple(expanded_h0_plan),
            "total_top_level_count": total_top_level_count,
            "total_h0_count": total_h0_count,
            "level_totals": dict(level_totals),
            "max_level_seen": max_level_seen,
            "last_illegal_reason": last_illegal_reason,
        }

    def rollback_execution_transaction(
        snapshot: Mapping[str, object],
        attempt: Dict[str, object],
        reason: str,
    ) -> None:
        """Restore the pre-candidate state while retaining diagnostic evidence."""

        nonlocal current_state
        nonlocal state_revision
        nonlocal total_top_level_count
        nonlocal total_h0_count
        nonlocal max_level_seen
        nonlocal last_illegal_reason

        attempted_output_state = adapter.snapshot_state(task, current_state)
        attempted_state_revision = state_revision
        prior_actions = tuple(snapshot["executed_actions"])
        attempted_action_count = len(executed_actions) - len(prior_actions)

        current_state = adapter.copy_state(task, snapshot["state"])
        state_revision = int(snapshot["state_revision"])
        executed_actions[:] = list(prior_actions)
        high_level_plan[:] = list(snapshot["high_level_plan"])
        expanded_h0_plan[:] = list(snapshot["expanded_h0_plan"])
        total_top_level_count = int(snapshot["total_top_level_count"])
        total_h0_count = int(snapshot["total_h0_count"])
        level_totals.clear()
        level_totals.update(dict(snapshot["level_totals"]))
        max_level_seen = int(snapshot["max_level_seen"])
        saved_illegal_reason = snapshot["last_illegal_reason"]
        last_illegal_reason = (
            str(saved_illegal_reason)
            if isinstance(saved_illegal_reason, str)
            else None
        )

        transaction = attempt.get("execution_transaction")
        transaction = dict(transaction) if isinstance(transaction, Mapping) else {}
        transaction.update(
            {
                "committed": False,
                "rolled_back": True,
                "rollback_reason": reason,
                "attempted_action_count": attempted_action_count,
                "attempted_output_state": attempted_output_state,
                "attempted_state_revision": attempted_state_revision,
                "restored_state_revision": state_revision,
            }
        )
        attempt["execution_transaction"] = transaction
        attempt["ending_state_revision"] = state_revision
        repair_telemetry["candidate_transaction_rollback_count"] = int(
            repair_telemetry["candidate_transaction_rollback_count"]
        ) + 1

    def commit_execution_transaction(attempt: Dict[str, object]) -> None:
        transaction = attempt.get("execution_transaction")
        if not isinstance(transaction, Mapping):
            return
        committed = dict(transaction)
        committed.update(
            {
                "committed": True,
                "rolled_back": False,
                "committed_action_count": int(
                    len(executed_actions)
                    - int(committed.get("starting_action_count", 0))
                ),
                "committed_state_revision": state_revision,
            }
        )
        attempt["execution_transaction"] = committed
        repair_telemetry["candidate_transaction_commit_count"] = int(
            repair_telemetry["candidate_transaction_commit_count"]
        ) + 1

    solved = False
    for repair_index in range(max_replans + 1):
        cycle_revision = state_revision
        execution_transaction: Optional[Dict[str, object]] = None
        active_stage = start_stage()
        # ``outputs`` describes one coherent attempt.  Full per-attempt history
        # remains available in ``attempts``; never mix a repaired Decision with
        # a Hierarchy or Router output invalidated on an earlier attempt.
        last_outputs = {}
        attempt: Dict[str, object] = {
            "attempt_index": repair_index,
            "repair_index": repair_index,
            "start_stage": active_stage,
            "state_revision": state_revision,
            "input_state": adapter.snapshot_state(task, current_state),
            "feedback_in_by_stage": dict(feedback_by_stage),
            "cache_hits": [],
            "events": [],
            "stage_outputs": {},
        }

        try:
            # Scene is deterministic and state-scoped.
            if cache["scene_revision"] == state_revision:
                scene = cache["scene"]
                cache_hits["scene"] += 1
                attempt["cache_hits"].append("scene")
            else:
                scene = adapter.render_state(task, current_state)
                cache["scene"] = scene
                cache["scene_revision"] = state_revision
                stage_counts["scene_descriptor_count"] += 1
            attempt["stage_outputs"]["scene_json"] = scene

            # Deterministic descriptor validation happens before the InnerBot
            # call, so malformed JSON cannot consume a verifier call.
            if cache["descriptor_revision"] == state_revision:
                state_output = cache["state_output"]
                descriptor_check = cache["descriptor_check"]
                cache_hits["state_descriptor"] += 1
                attempt["cache_hits"].append("state_descriptor")
                if cache["descriptor_model_backed"]:
                    model_call_cache_hits["state_descriptor"] += 1
            else:
                active_stage = "state_descriptor"
                stage_counts["state_descriptor_count"] += 1
                if fixed_goal:
                    fixed_descriptor = adapter.fixed_state_descriptor(
                        task, current_state, scene
                    )
                    state_output = (
                        fixed_descriptor.value
                        if isinstance(fixed_descriptor, LocalArtifact)
                        else fixed_descriptor
                    )
                    descriptor_model_backed = False
                else:
                    request = adapter.state_descriptor_request(
                        task,
                        current_state,
                        scene,
                        rejected_outputs["state_descriptor"]
                        or cache.get("state_output")
                        or "N/A",
                        feedback_by_stage["state_descriptor"] or "N/A",
                    )
                    state_output = call(request)
                    descriptor_model_backed = True
                descriptor_check = v2._coerce_artifact_check(
                    adapter.validate_state_descriptor(
                        task, current_state, scene, state_output
                    )
                )
                attempt["stage_outputs"]["state_output"] = state_output
                attempt["descriptor_validation"] = v2._check_payload(
                    descriptor_check
                )
                if not descriptor_check.valid:
                    message = (
                        "StateDescriptor validation failed: "
                        f"{descriptor_check.reason}"
                    )
                    parse_errors.append(f"StateDescriptor: {descriptor_check.reason}")
                    rejected_outputs["state_descriptor"] = state_output
                    invalidate_descriptor(message)
                    feedback_by_stage["state_descriptor"] = message
                    failure_attempt(attempt, stage=active_stage, message=message)
                    continue
                cache["descriptor_revision"] = state_revision
                cache["state_output"] = state_output
                cache["descriptor_check"] = descriptor_check
                cache["descriptor_model_backed"] = descriptor_model_backed
                rejected_outputs["state_descriptor"] = None
                feedback_by_stage["state_descriptor"] = ""

            attempt["stage_outputs"]["state_output"] = state_output
            if cache["state_verified_revision"] == state_revision:
                innerbot_state_output = cache["innerbot_state_output"]
                cache_hits["innerbot_state"] += 1
                attempt["cache_hits"].append("innerbot_state")
                model_call_cache_hits["innerbot_state"] += 1
            else:
                active_stage = "innerbot_state"
                stage_counts["innerbot_state_check_count"] += 1
                stage_counts["innerbot_state_llm_call_count"] += 1
                innerbot_state_output = call(
                    _append_stage_feedback(
                        adapter.inner_state_request(
                            task, current_state, scene, state_output
                        ),
                        feedback_by_stage["innerbot_state"],
                    )
                )
                inner_valid, inner_reason = adapter.parse_inner_state(
                    innerbot_state_output
                )
                attempt["stage_outputs"][
                    "innerbot_state_output"
                ] = innerbot_state_output
                attempt["innerbot_state_check"] = {
                    "result": "YES" if inner_valid else "NO",
                    "reason": str(inner_reason),
                    "deterministic_descriptor_valid": descriptor_check.valid,
                }
                if not inner_valid:
                    message = (
                        "InnerBot state verifier rejected the validated "
                        f"descriptor: {inner_reason}"
                    )
                    parse_errors.append(f"InnerBotState: {inner_reason}")
                    if fixed_goal or bool(
                        getattr(
                            adapter,
                            "state_descriptor_validation_authoritative",
                            True,
                        )
                    ):
                        invalidate_inner(message)
                        feedback_by_stage["innerbot_state"] = message
                    else:
                        rejected_outputs["state_descriptor"] = state_output
                        invalidate_descriptor(message)
                        feedback_by_stage["state_descriptor"] = message
                    failure_attempt(attempt, stage=active_stage, message=message)
                    continue
                cache["state_verified_revision"] = state_revision
                cache["innerbot_state_output"] = innerbot_state_output
                feedback_by_stage["innerbot_state"] = ""

            attempt["stage_outputs"][
                "innerbot_state_output"
            ] = innerbot_state_output

            # H1 is promoted only after standalone adapter validation.  An
            # adapter without that optional hook may promote H1 later, but only
            # after the complete hierarchy compiler accepts it.
            h1_was_cached = cache["h1_output"] is not None
            if h1_was_cached:
                h1_output = cache["h1_output"]
                cache_hits["h1"] += 1
                attempt["cache_hits"].append("h1")
                if cache["h1_model_backed"]:
                    model_call_cache_hits["h1"] += 1
            else:
                active_stage = "h1"
                h1_source = adapter.h1_source(
                    task,
                    current_state,
                    scene,
                    feedback_by_stage["h1"],
                )
                if isinstance(h1_source, StageRequest):
                    h1_model_backed = True
                    stage_counts["h1_generation_count"] += 1
                    h1_output = call(
                        _append_stage_feedback(
                            h1_source, feedback_by_stage["h1"]
                        )
                    )
                elif isinstance(h1_source, LocalArtifact):
                    h1_model_backed = False
                    h1_output = h1_source.value
                else:
                    raise TypeError(
                        "adapter.h1_source() must return StageRequest or LocalArtifact"
                    )
                standalone_h1_check = _h1_check(adapter, task, h1_output)
                attempt["stage_outputs"]["h1_output"] = h1_output
                if standalone_h1_check is not None:
                    attempt["h1_validation"] = v2._check_payload(
                        standalone_h1_check
                    )
                    if not standalone_h1_check.valid:
                        message = f"H1 validation failed: {standalone_h1_check.reason}"
                        parse_errors.append(f"H1: {standalone_h1_check.reason}")
                        invalidate_h1(message)
                        feedback_by_stage["h1"] = message
                        failure_attempt(attempt, stage=active_stage, message=message)
                        continue
                    # Standalone acceptance is already deterministic evidence
                    # that a valid H1 level exists, even when a later Decision
                    # failure short-circuits Hierarchy compilation.
                    base_valid_any = True
                    max_level_seen = max(max_level_seen, 1)
                    raw_h1_counts = standalone_h1_check.metadata.get(
                        "mapping_count_by_level"
                    )
                    if isinstance(raw_h1_counts, Mapping):
                        last_mapping_count_by_level = {
                            int(level): int(count)
                            for level, count in raw_h1_counts.items()
                        }
                    else:
                        raw_mapping_count = standalone_h1_check.metadata.get(
                            "mapping_count"
                        )
                        if isinstance(raw_mapping_count, int):
                            last_mapping_count_by_level = {1: raw_mapping_count}
                    canonical_h1_output = _canonical_h1(
                        adapter, task, h1_output, standalone_h1_check
                    )
                    if canonical_h1_output != h1_output:
                        attempt["stage_outputs"]["h1_raw_output"] = h1_output
                    h1_output = canonical_h1_output
                    attempt["stage_outputs"]["h1_output"] = h1_output
                    cache["h1_output"] = h1_output
                    cache["h1_check"] = standalone_h1_check
                    cache["h1_model_backed"] = h1_model_backed
                    feedback_by_stage["h1"] = ""
                    invalidate_decision("Validated H1 artifact changed")

            attempt["stage_outputs"]["h1_output"] = h1_output

            if cache["decision_revision"] == state_revision:
                decision_output = cache["decision_output"]
                decision = cache["decision"]
                decision_check = ArtifactCheck.accepted(decision)
                cache_hits["decision"] += 1
                attempt["cache_hits"].append("decision")
                model_call_cache_hits["decision"] += 1
            else:
                active_stage = "decision"
                stage_counts["plan_generation_count"] += 1
                decision_request = adapter.decision_request(
                    task,
                    current_state,
                    scene,
                    state_output,
                    h1_output,
                    feedback_by_stage["decision"],
                )
                if decision_repair_certificate is not None:
                    decision_request = adapter.augment_decision_repair_request(
                        task,
                        current_state,
                        decision_request,
                        decision_repair_certificate,
                    )
                decision_output = call(decision_request)
                decision_check = v2._coerce_artifact_check(
                    adapter.parse_decision(task, decision_output)
                )
                decision = decision_check.value
                attempt["stage_outputs"]["plan_output"] = decision_output
                attempt["stage_outputs"]["decision_output"] = decision_output
                attempt["decision_validation"] = v2._check_payload(decision_check)
                if not decision_check.valid or decision is None:
                    message = (
                        "Decision validation failed: "
                        f"{decision_check.reason}"
                    )
                    parse_errors.extend(
                        f"Plan: {error}" for error in decision_check.errors
                    )
                    invalidate_decision(message)
                    feedback_by_stage["decision"] = message
                    failure_attempt(
                        attempt,
                        stage=active_stage,
                        message=message,
                        owner=OWNER_DECISION,
                    )
                    continue
                canonical_decision_output = _canonical_decision(
                    adapter,
                    task,
                    decision_output,
                    decision_check,
                )
                if canonical_decision_output != decision_output:
                    attempt["stage_outputs"]["decision_raw_output"] = decision_output
                decision_output = canonical_decision_output
                cache["decision_revision"] = state_revision
                cache["decision_output"] = decision_output
                cache["decision"] = decision
                feedback_by_stage["decision"] = ""
                decision_repair_certificate = None

            attempt["stage_outputs"]["plan_output"] = decision_output
            attempt["stage_outputs"]["decision_output"] = decision_output

            if cache["hierarchy_revision"] == state_revision:
                hierarchy_output = cache["hierarchy_output"]
                hierarchy = cache["hierarchy"]
                projection = cache["projection"]
                cache_hits["hierarchy"] += 1
                cache_hits["projection"] += 1
                attempt["cache_hits"].extend(["hierarchy", "projection"])
                model_call_cache_hits["hierarchy"] += 1
            else:
                active_stage = "hierarchy_planner"
                stage_counts["hierarchy_generation_count"] += 1
                repair_context = pending_repair
                if repair_context is not None and (
                    repair_context.candidate.state_revision != state_revision
                    or repair_context.candidate.h1_output != h1_output
                    or repair_context.candidate.decision_output != decision_output
                ):
                    repair_context = None
                    pending_repair = None

                if repair_context is None:
                    raw_hierarchy_output = call(
                        adapter.hierarchy_request(
                            task,
                            current_state,
                            scene,
                            state_output,
                            h1_output,
                            decision_output,
                            feedback_by_stage["hierarchy_planner"],
                            include_code_block,
                        )
                    )
                    hierarchy_output = raw_hierarchy_output
                else:
                    repair_telemetry["localized_patch_request_count"] = int(
                        repair_telemetry["localized_patch_request_count"]
                    ) + 1
                    patch_request = adapter.hierarchy_repair_request(
                        task,
                        current_state,
                        scene,
                        state_output,
                        h1_output,
                        decision_output,
                        repair_context.candidate.output,
                        repair_context.certificate,
                        repair_context.preserved_subtask_indices,
                        repair_context.repair_subtask_indices,
                        feedback_by_stage["hierarchy_planner"],
                        include_code_block,
                    )
                    raw_hierarchy_output = call(patch_request)
                    attempt["stage_outputs"][
                        "hierarchy_patch_output"
                    ] = raw_hierarchy_output
                    attempt["repair_mode"] = "verified_prefix_suffix_patch"
                    attempt["preserved_subtasks"] = list(
                        repair_context.preserved_subtask_indices
                    )
                    merged_check = v2._coerce_artifact_check(
                        adapter.merge_hierarchy_repair(
                            task,
                            repair_context.candidate.output,
                            raw_hierarchy_output,
                            repair_context.preserved_subtask_indices,
                            repair_context.repair_subtask_indices,
                        )
                    )
                    if not merged_check.valid or not isinstance(
                        merged_check.value, str
                    ):
                        repair_telemetry["localized_patch_reject_count"] = int(
                            repair_telemetry["localized_patch_reject_count"]
                        ) + 1
                        errors = list(merged_check.errors) or [merged_check.reason]
                        message = "Hierarchy patch merge failed: " + "; ".join(errors)
                        parse_errors.extend(f"HierarchyPatch: {item}" for item in errors)
                        attempt["stage_outputs"][
                            "hierarchy_output"
                        ] = raw_hierarchy_output
                        attempt["hierarchy_validation"] = v2._check_payload(
                            merged_check
                        )
                        # A compiler-accepted candidate is not necessarily
                        # merge-compatible for a third-party adapter.  Never
                        # retry an impossible transaction forever: discard the
                        # repair target and regenerate one full hierarchy next.
                        pending_repair = None
                        candidate = None
                        repair_telemetry[
                            "full_regeneration_fallback_count"
                        ] = int(
                            repair_telemetry[
                                "full_regeneration_fallback_count"
                            ]
                        ) + 1
                        invalidate_hierarchy(message)
                        feedback_by_stage["hierarchy_planner"] = message
                        failure_attempt(
                            attempt,
                            stage=active_stage,
                            message=message,
                            owner=OWNER_HIERARCHY,
                        )
                        continue
                    hierarchy_output = merged_check.value

                hierarchy_check = v2._coerce_artifact_check(
                    adapter.compile_hierarchy(
                        task,
                        current_state,
                        h1_output,
                        decision_output,
                        decision,
                        hierarchy_output,
                    )
                )
                if (
                    repair_context is not None
                    and hierarchy_check.valid
                    and hierarchy_check.value is not None
                ):
                    previous = {
                        item.index: item
                        for item in repair_context.candidate.hierarchy.subtasks
                    }
                    repaired = {
                        item.index: item for item in hierarchy_check.value.subtasks
                    }
                    prefix_errors = [
                        f"Certified prefix subtask {index} changed during repair"
                        for index in repair_context.preserved_subtask_indices
                        if index not in previous
                        or index not in repaired
                        or not _same_subtask(previous[index], repaired[index])
                    ]
                    if prefix_errors:
                        hierarchy_check = ArtifactCheck.rejected(*prefix_errors)
                    else:
                        repair_telemetry["localized_patch_accept_count"] = int(
                            repair_telemetry["localized_patch_accept_count"]
                        ) + 1
                attempt["stage_outputs"]["hierarchy_output"] = hierarchy_output
                attempt["hierarchy_validation"] = v2._check_payload(
                    hierarchy_check
                )
                hierarchy = hierarchy_check.value

                errors = list(hierarchy_check.errors)
                parse_errors.extend(errors)
                if hierarchy is not None:
                    stats = hierarchy.stats
                    base_valid_any = base_valid_any or stats.base_pattern_valid
                    hierarchy_valid_any = hierarchy_valid_any or stats.hierarchy_valid
                    max_level_seen = max(max_level_seen, stats.max_level)
                    last_mapping_count_by_level = dict(stats.mapping_count_by_level)
                    for error in stats.errors:
                        if error not in hierarchy_errors_seen:
                            hierarchy_errors_seen.append(error)

                if (
                    not hierarchy_check.valid
                    or hierarchy is None
                    or not hierarchy.subtasks
                ):
                    if repair_context is not None:
                        repair_telemetry["localized_patch_reject_count"] = int(
                            repair_telemetry["localized_patch_reject_count"]
                        ) + 1
                    if hierarchy is None or not getattr(hierarchy, "subtasks", ()):
                        if not errors:
                            errors.append("Hierarchy: no executable subtasks were produced")
                    message = "Hierarchy validation failed: " + "; ".join(errors)
                    invalidate_hierarchy(message)
                    feedback_by_stage["hierarchy_planner"] = message
                    failure_attempt(
                        attempt,
                        stage=active_stage,
                        message=message,
                        owner=OWNER_HIERARCHY,
                    )
                    continue

                candidate_serial += 1
                candidate = RepairCandidate(
                    serial=candidate_serial,
                    state_revision=state_revision,
                    h1_output=h1_output,
                    decision_output=decision_output,
                    decision=decision,
                    output=hierarchy_output,
                    hierarchy=hierarchy,
                )
                pending_repair = None

                projection = v2.project_compiled_hierarchy(
                    task, adapter, current_state, decision, hierarchy
                )
                attempt["projection"] = v2._projection_payload(
                    adapter, task, projection
                )
                if not projection.valid:
                    message = (
                        "Symbolic projection validation rejected the candidate: "
                        f"{projection.reason}"
                    )
                    parse_errors.append(f"Symbolic: {projection.reason}")
                    failed_index = getattr(projection, "failed_subtask_index", None)
                    ordered_indices = tuple(item.index for item in hierarchy.subtasks)
                    failed_action = getattr(projection, "failed_action", None)
                    signature = (
                        state_revision,
                        h1_output,
                        decision_output,
                        failed_index,
                        getattr(projection, "failed_action_index", None),
                        adapter.format_action(failed_action)
                        if failed_action is not None
                        else None,
                        bool(getattr(projection, "checkpoint_failure", False)),
                        str(projection.reason),
                    )
                    if signature == last_failure_signature:
                        same_failure_count += 1
                    else:
                        last_failure_signature = signature
                        same_failure_count = 1

                    can_localize = failed_index in ordered_indices and candidate is not None
                    checkpoint_limit = max(
                        0,
                        int(
                            getattr(
                                adapter, "checkpoint_local_repair_limit", 2
                            )
                        ),
                    )
                    escalate_checkpoint = bool(
                        getattr(projection, "checkpoint_failure", False)
                        and same_failure_count > checkpoint_limit
                    )
                    projection_owner = (
                        OWNER_BOTH
                        if not can_localize or escalate_checkpoint
                        else OWNER_HIERARCHY
                    )

                    if can_localize:
                        failed_position = ordered_indices.index(failed_index)
                        backtrack_after = max(
                            1, int(getattr(adapter, "repair_backtrack_after", 2))
                        )
                        backtracked = bool(
                            not escalate_checkpoint
                            and same_failure_count > backtrack_after
                            and failed_position > 0
                        )
                        repair_position = (
                            failed_position - 1 if backtracked else failed_position
                        )
                        if backtracked:
                            repair_telemetry["backtrack_count"] = int(
                                repair_telemetry["backtrack_count"]
                            ) + 1
                        preserved_indices = ordered_indices[:repair_position]
                        repair_indices = ordered_indices[repair_position:]
                        certificate = dict(
                            adapter.build_repair_certificate(
                                task,
                                current_state,
                                decision,
                                hierarchy,
                                projection,
                                preserved_indices,
                                repair_indices,
                            )
                        )
                        certificate.update(
                            {
                                "candidate_serial": candidate.serial,
                                "failure_count": same_failure_count,
                                "preserved_checkpoint_valid_subtasks": list(
                                    preserved_indices
                                ),
                                "repair_subtasks": list(repair_indices),
                                "backtracked_one_subtask": backtracked,
                            }
                        )
                        attempt["failure_certificate"] = dict(certificate)
                        certificates = repair_telemetry["failure_certificates"]
                        assert isinstance(certificates, list)
                        certificates.append(certificate)
                        repair_telemetry[
                            "preserved_subtask_count_total"
                        ] = int(
                            repair_telemetry["preserved_subtask_count_total"]
                        ) + len(preserved_indices)
                        if bool(getattr(projection, "checkpoint_failure", False)):
                            counter = (
                                "checkpoint_decision_escalation_count"
                                if escalate_checkpoint
                                else "checkpoint_local_repair_count"
                            )
                            repair_telemetry[counter] = int(
                                repair_telemetry[counter]
                            ) + 1
                        if not escalate_checkpoint:
                            pending_repair = RepairContext(
                                candidate=candidate,
                                projection=projection,
                                certificate=certificate,
                                preserved_subtask_indices=tuple(preserved_indices),
                                repair_subtask_indices=tuple(repair_indices),
                                failure_count=same_failure_count,
                                backtracked=backtracked,
                            )
                        else:
                            decision_repair_certificate = certificate

                    if projection_owner == OWNER_BOTH:
                        invalidate_decision(message)
                    else:
                        invalidate_hierarchy(message)
                    set_owner_feedback(projection_owner, message)
                    failure_attempt(
                        attempt,
                        stage="projection",
                        message=message,
                        owner=projection_owner,
                    )
                    continue

                # Fallback promotion for adapters lacking a standalone H1
                # validator happens only after the combined compiler *and*
                # symbolic projection accept the artifact.  This prevents a
                # semantically misbound H1 from surviving every later repair.
                if cache["h1_output"] is None:
                    cache["h1_output"] = h1_output
                    cache["h1_check"] = ArtifactCheck.accepted(h1_output)
                    cache["h1_model_backed"] = h1_model_backed

                cache["hierarchy_revision"] = state_revision
                cache["hierarchy_output"] = hierarchy_output
                cache["hierarchy"] = hierarchy
                cache["projection"] = projection
                feedback_by_stage["hierarchy_planner"] = ""

            deterministic_complete = bool(
                online_verification_authoritative
                and projection.valid
                and v2._goal_reached(adapter, task, projection.final_state)
            )
            if deterministic_complete:
                last_failure_signature = None
                same_failure_count = 0
                if candidate is None:
                    raise RuntimeError(
                        "A cached valid projection has no compiled candidate"
                    )
                incumbent_actions = (
                    *tuple(executed_actions),
                    *tuple(
                        action
                        for item in hierarchy.subtasks
                        for action in item.actions
                    ),
                )
                incumbent_high_level = (
                    *tuple(high_level_plan),
                    *tuple(
                        adapter.format_call(call_item)
                        for item in hierarchy.subtasks
                        for call_item in item.top_level_calls
                    ),
                )
                incumbent_h0 = (
                    *tuple(expanded_h0_plan),
                    *tuple(
                        adapter.format_call(call_item)
                        for item in hierarchy.subtasks
                        for call_item in item.h0_calls
                    ),
                )
                incumbent_levels = dict(level_totals)
                for item in hierarchy.subtasks:
                    for level, count in item.level_counts.items():
                        incumbent_levels[int(level)] = (
                            incumbent_levels.get(int(level), 0) + int(count)
                        )
                incumbent_context = FinalScoreContext(
                    # Keep the candidate snapshot oracle-free while planning;
                    # the private evaluator task is attached only if this
                    # incumbent is actually scored after the loop.
                    task=task,
                    final_state=adapter.copy_state(task, projection.final_state),
                    executed_actions=tuple(incumbent_actions),
                    high_level_plan=tuple(incumbent_high_level),
                    expanded_h0_plan=tuple(incumbent_h0),
                    parse_errors=tuple(parse_errors),
                    last_illegal_reason=None,
                    total_top_level_count=len(incumbent_high_level),
                    total_h0_count=len(incumbent_h0),
                    level_totals=dict(incumbent_levels),
                    max_level_seen=max(
                        [hierarchy.stats.max_level, *incumbent_levels.keys()],
                        default=hierarchy.stats.max_level,
                    ),
                    base_valid_any=hierarchy.stats.base_pattern_valid,
                    hierarchy_valid_any=hierarchy.stats.hierarchy_valid,
                    last_mapping_count_by_level=dict(
                        hierarchy.stats.mapping_count_by_level
                    ),
                    hierarchy_errors_seen=tuple(hierarchy.stats.errors),
                )
                if candidate.serial not in incumbent_candidate_serials:
                    incumbent_candidate_serials.add(candidate.serial)
                    repair_telemetry["valid_incumbent_count"] = int(
                        repair_telemetry["valid_incumbent_count"]
                    ) + 1
                if (
                    candidate.serial in incumbent_candidate_serials
                    and (
                        valid_incumbent is None
                        or len(incumbent_actions) < valid_incumbent.action_count
                    )
                ):
                    valid_incumbent = ValidIncumbent(
                        candidate_serial=candidate.serial,
                        action_count=len(incumbent_actions),
                        state_revision=(
                            state_revision
                            + sum(
                                len(item.actions)
                                for item in hierarchy.subtasks
                            )
                        ),
                        final_state=adapter.copy_state(
                            task, projection.final_state
                        ),
                        executed_actions=tuple(incumbent_actions),
                        high_level_plan=tuple(incumbent_high_level),
                        expanded_h0_plan=tuple(incumbent_h0),
                        score_context=incumbent_context,
                        outputs=dict(attempt["stage_outputs"]),
                    )
                    repair_telemetry["valid_incumbent_update_count"] = int(
                        repair_telemetry["valid_incumbent_update_count"]
                    ) + 1

            attempt["stage_outputs"]["hierarchy_output"] = hierarchy_output
            last_outputs = dict(attempt["stage_outputs"])

            active_stage = "innerbot_router"
            stage_counts["router_check_count"] += 1
            stage_counts["router_llm_call_count"] += 1
            router_output = call(
                _append_stage_feedback(
                    adapter.router_request(
                        task,
                        current_state,
                        scene,
                        state_output,
                        decision_output,
                        hierarchy_output,
                        projection,
                    ),
                    feedback_by_stage["innerbot_router"],
                )
            )
            feedback_by_stage["innerbot_router"] = ""
            last_outputs["router_output"] = router_output
            attempt["stage_outputs"]["router_output"] = router_output
            router_verdict = adapter.parse_router(router_output)
            if not router_verdict.no_mistake:
                message = (
                    "InnerBot router rejected the compiled hierarchy: "
                    f"{router_verdict.reason}"
                )
                parse_errors.append(f"Router: {router_verdict.reason}")
                if deterministic_complete:
                    repair_telemetry["router_validity_override_count"] = int(
                        repair_telemetry["router_validity_override_count"]
                    ) + 1
                    attempt["router_check"] = {
                        "result": "YES",
                        "owner": "NA",
                        "reason": (
                            "Deterministic complete-plan projection overrides "
                            f"advisory rejection: {router_verdict.reason}"
                        ),
                        "source": "deterministic_override",
                        "advisory_result": "NO",
                        "advisory_owner": v2._canonical_owner(
                            router_verdict.owner
                        ),
                    }
                else:
                    owner = invalidate_owner(router_verdict.owner, message)
                    attempt["router_check"] = {
                        "result": "NO",
                        "owner": owner,
                        "reason": router_verdict.reason,
                        "source": "llm",
                    }
                    failure_attempt(
                        attempt,
                        stage=active_stage,
                        message=message,
                        owner=owner,
                    )
                    continue

            if "router_check" not in attempt:
                attempt["router_check"] = {
                    "result": "YES",
                    "owner": "NA",
                    "reason": router_verdict.reason,
                    "source": "llm",
                }

            if transactional_candidate_execution:
                execution_transaction = capture_execution_transaction()
                attempt["execution_transaction"] = {
                    "enabled": True,
                    "starting_action_count": len(executed_actions),
                    "starting_state_revision": state_revision,
                    "committed": False,
                    "rolled_back": False,
                }

            replan_required = False
            failure_stage = "hierarchy_planner"
            failure_message = ""
            failure_owner = OWNER_HIERARCHY

            for position, projected_subtask in enumerate(projection.subtasks):
                subtask = projected_subtask.plan
                previous_state = adapter.copy_state(task, current_state)

                total_top_level_count += len(subtask.top_level_calls)
                total_h0_count += len(subtask.h0_calls)
                for level, count in subtask.level_counts.items():
                    level_totals[int(level)] = (
                        level_totals.get(int(level), 0) + int(count)
                    )
                high_level_plan.extend(
                    adapter.format_call(item) for item in subtask.top_level_calls
                )
                expanded_h0_plan.extend(
                    adapter.format_call(item) for item in subtask.h0_calls
                )

                executed_this_subtask: List[str] = []
                for action in subtask.actions:
                    action_number = len(executed_actions) + 1
                    transition = adapter.apply_action(
                        task, current_state, action, action_number
                    )
                    if not transition.ok:
                        last_illegal_reason = transition.reason
                        failure_message = (
                            f"Recoverable execution error at action {action_number}: "
                            f"{transition.reason}"
                        )
                        attempt["events"].append(
                            {
                                "subtask_index": subtask.index,
                                "verdict": "RECOVERABLE",
                                "reason": transition.reason,
                                "failed_action": adapter.format_action(action),
                                "state": adapter.snapshot_state(task, current_state),
                                "transition_metadata": dict(transition.metadata),
                            }
                        )
                        replan_required = True
                        break
                    current_state = transition.state
                    executed_actions.append(action)
                    executed_this_subtask.append(adapter.format_action(action))
                    state_revision += 1

                if replan_required:
                    break

                stage_counts["executed_subtask_count"] += 1
                stage_counts["scene_descriptor_count"] += 1
                stage_counts["outerbot_check_count"] += 1
                stage_counts["outerbot_llm_call_count"] += 1
                active_stage = "outerbot"
                outerbot_output = call(
                    _append_stage_feedback(
                        adapter.outer_request(
                            task,
                            decision,
                            hierarchy,
                            projected_subtask,
                            previous_state,
                            current_state,
                            position == len(projection.subtasks) - 1,
                        ),
                        feedback_by_stage["outerbot"],
                    )
                )
                feedback_by_stage["outerbot"] = ""
                last_outputs["outerbot_output"] = outerbot_output
                attempt["stage_outputs"]["outerbot_output"] = outerbot_output
                outer_verdict = adapter.parse_outer(outerbot_output)
                outer_status = v2._canonical_outer_status(outer_verdict.status)
                # Presentation snapshots may intentionally redact semantic
                # state (for example LexiCon's temporal monitor fluents).
                # Only the adapter's full-state equivalence contract can
                # authorize an override of the advisory OuterBot.
                deterministic_subtask_valid = bool(
                    adapter.states_equivalent(
                        task,
                        current_state,
                        projected_subtask.projected_state,
                    )
                )
                expected_outer_status: Optional[str] = None
                if online_verification_authoritative and deterministic_subtask_valid:
                    if position < len(projection.subtasks) - 1:
                        expected_outer_status = "SUBTASK SUCCESS"
                    elif v2._goal_reached(adapter, task, current_state):
                        expected_outer_status = "TASK SUCCESS"
                advisory_outer_status = outer_status
                if (
                    expected_outer_status is not None
                    and outer_status != expected_outer_status
                ):
                    repair_telemetry["outerbot_validity_override_count"] = int(
                        repair_telemetry["outerbot_validity_override_count"]
                    ) + 1
                    outer_status = expected_outer_status
                event: Dict[str, object] = {
                    "subtask_index": subtask.index,
                    "verdict": outer_status,
                    "outerbot_reason": outer_verdict.reason,
                    "outerbot_output": outerbot_output,
                    "high_level_calls": [
                        adapter.format_call(item) for item in subtask.top_level_calls
                    ],
                    "expanded_h0_calls": [
                        adapter.format_call(item) for item in subtask.h0_calls
                    ],
                    "executed_actions": executed_this_subtask,
                    "executed_moves": executed_this_subtask,
                    "state": adapter.snapshot_state(task, current_state),
                    "state_revision": state_revision,
                    "deterministic_projection_match": deterministic_subtask_valid,
                }
                if outer_status != advisory_outer_status:
                    event["advisory_outer_status"] = advisory_outer_status
                    event["outerbot_override_source"] = "deterministic_projection"
                attempt["events"].append(event)

                if outer_status == "TASK SUCCESS":
                    if (
                        not online_verification_authoritative
                        or v2._goal_reached(adapter, task, current_state)
                    ):
                        solved = True
                        break
                    guard_reason = (
                        "OuterBot claimed TASK SUCCESS, but deterministic goal "
                        "and constraint validation is false"
                    )
                    event["deterministic_goal_guard"] = {
                        "accepted": False,
                        "reason": guard_reason,
                    }
                    parse_errors.append(f"OuterBot: {guard_reason}")
                    failure_stage = "outerbot"
                    failure_owner = OWNER_BOTH
                    failure_message = (
                        f"{guard_reason}. Current state is "
                        f"{adapter.snapshot_state(task, current_state)}."
                    )
                    replan_required = True
                    break

                if outer_status in {"SUBTASK SUCCESS", "EXECUTE REMAINING ACTIONS"}:
                    continue

                normalized_failure = (
                    outer_status
                    if outer_status in {"RECOVERABLE", "NON-RECOVERABLE"}
                    else "RECOVERABLE"
                )
                execution_feedback = (
                    f"OuterBot reported {outer_status} after subtask "
                    f"{subtask.index}: {outer_verdict.reason}. Current state is "
                    f"{adapter.snapshot_state(task, current_state)}."
                )
                stage_counts["router_check_count"] += 1
                stage_counts["router_llm_call_count"] += 1
                current_scene = adapter.render_state(task, current_state)
                active_stage = "innerbot_router"
                recheck_output = call(
                    _append_stage_feedback(
                        adapter.router_request(
                            task,
                            current_state,
                            current_scene,
                            state_output,
                            decision_output,
                            hierarchy_output,
                            projection,
                            execution_feedback=execution_feedback,
                        ),
                        feedback_by_stage["innerbot_router"],
                    )
                )
                feedback_by_stage["innerbot_router"] = ""
                last_outputs["router_output"] = recheck_output
                attempt["stage_outputs"]["router_output"] = recheck_output
                recheck = adapter.parse_router(recheck_output)
                failure_owner = route(recheck.owner)
                event["router_owner"] = failure_owner
                event["router_reason"] = recheck.reason
                event["normalized_failure_verdict"] = normalized_failure
                failure_stage = "outerbot"
                failure_message = (
                    f"{execution_feedback}; router assigned {failure_owner}: "
                    f"{recheck.reason}"
                )
                replan_required = True
                if normalized_failure == "NON-RECOVERABLE":
                    last_illegal_reason = outer_verdict.reason
                    termination_reason = "non_recoverable"
                break

            attempt["output_state"] = adapter.snapshot_state(task, current_state)
            attempt["ending_state_revision"] = state_revision
            if solved:
                if execution_transaction is not None:
                    commit_execution_transaction(attempt)
                attempt["verdict"] = "TASK SUCCESS"
                attempt["feedback_out"] = ""
                attempts.append(attempt)
                termination_reason = "task_success"
                break

            if replan_required:
                if execution_transaction is not None:
                    rollback_execution_transaction(
                        execution_transaction,
                        attempt,
                        failure_message,
                    )
                    invalidate_owner(failure_owner, failure_message)
                    if (
                        continue_after_rollback
                        and termination_reason == "non_recoverable"
                    ):
                        # Reaching this branch requires the full rollback to
                        # have returned successfully.  The rejected candidate
                        # remains rejected regardless of the router's verdict;
                        # only its terminal controller classification changes.
                        remaining_attempts = max_replans - repair_index
                        attempt["rollback_continuation"] = {
                            "original_termination_reason": "non_recoverable",
                            "reclassified_as": "candidate_failure",
                            "remaining_attempts": remaining_attempts,
                            "will_retry": remaining_attempts > 0,
                        }
                        if remaining_attempts > 0:
                            repair_telemetry[
                                "candidate_rollback_continuation_count"
                            ] = int(
                                repair_telemetry[
                                    "candidate_rollback_continuation_count"
                                ]
                            ) + 1
                        termination_reason = "max_replans_exhausted"
                elif state_revision != cycle_revision:
                    invalidate_state(
                        "Committed action changed state before repair: "
                        + failure_message
                    )
                    set_owner_feedback(failure_owner, failure_message)
                else:
                    invalidate_owner(failure_owner, failure_message)
                failure_attempt(
                    attempt,
                    stage=failure_stage,
                    message=failure_message,
                    owner=failure_owner,
                )
                if termination_reason == "non_recoverable":
                    break
                continue

            authority_label = (
                "deterministic final goal"
                if online_verification_authoritative
                else "LLM-only final success"
            )
            failure_message = (
                f"Plan finished without an OuterBot-confirmed {authority_label}. "
                f"Current state is {adapter.snapshot_state(task, current_state)}."
            )
            if execution_transaction is not None:
                rollback_execution_transaction(
                    execution_transaction,
                    attempt,
                    failure_message,
                )
                invalidate_owner(OWNER_BOTH, failure_message)
            elif state_revision != cycle_revision:
                invalidate_state(failure_message)
                set_owner_feedback(OWNER_BOTH, failure_message)
            else:
                invalidate_decision(failure_message)
                set_owner_feedback(OWNER_BOTH, failure_message)
            failure_attempt(
                attempt,
                stage="outerbot",
                message=failure_message,
                owner=OWNER_BOTH,
            )
        except Exception as error:
            if not v2._is_truncated_response(error):
                if execution_transaction is not None:
                    rollback_execution_transaction(
                        execution_transaction,
                        attempt,
                        f"Exception during candidate execution: {error}",
                    )
                raise
            message = f"Truncated at {active_stage}: {error}"
            parse_errors.append(message)
            if active_stage == "state_descriptor":
                partial_output = getattr(error, "output", None)
                if partial_output:
                    rejected_outputs["state_descriptor"] = partial_output
            if execution_transaction is not None:
                rollback_execution_transaction(
                    execution_transaction,
                    attempt,
                    message,
                )
            if state_revision != cycle_revision:
                invalidate_state(message)
            elif active_stage == "state_descriptor":
                invalidate_descriptor(message)
            elif active_stage == "innerbot_state":
                invalidate_inner(message)
            elif active_stage == "h1":
                invalidate_h1(message)
            elif active_stage == "decision":
                invalidate_decision(message)
            elif active_stage in {"hierarchy_planner", "innerbot_router"}:
                # Router truncation keeps the compiled hierarchy so only the
                # verifier call is retried; hierarchy generation truncation has
                # no compiled artifact to retain.
                if active_stage == "hierarchy_planner":
                    invalidate_hierarchy(message)
            feedback_by_stage[active_stage] = (
                f"{message}. Retry with a more concise response."
            )
            failure_attempt(attempt, stage=active_stage, message=message)
            continue

    replan_count = sum(
        1 for attempt in attempts[:-1] if attempt.get("verdict") == "REPLAN"
    )
    if (
        online_verification_authoritative
        and v2._goal_reached(adapter, task, current_state)
    ):
        last_illegal_reason = None

    score_context = FinalScoreContext(
        task=task if final_score_task is None else final_score_task,
        final_state=current_state,
        executed_actions=tuple(executed_actions),
        high_level_plan=tuple(high_level_plan),
        expanded_h0_plan=tuple(expanded_h0_plan),
        parse_errors=tuple(parse_errors),
        last_illegal_reason=last_illegal_reason,
        total_top_level_count=total_top_level_count,
        total_h0_count=total_h0_count,
        level_totals=dict(level_totals),
        max_level_seen=max_level_seen,
        base_valid_any=base_valid_any,
        hierarchy_valid_any=hierarchy_valid_any,
        last_mapping_count_by_level=dict(last_mapping_count_by_level),
        hierarchy_errors_seen=tuple(hierarchy_errors_seen),
    )
    score = None
    if valid_incumbent is not None and not solved:
        # Restore an immutable, internally coherent candidate snapshot before
        # final scoring.  Later parse failures and Router/Outer artifacts must
        # not leak into the retained candidate's score or output bundle.
        incumbent_context = valid_incumbent.score_context
        if final_score_task is not None:
            incumbent_context = replace(
                incumbent_context,
                task=final_score_task,
            )
        incumbent_score = adapter.final_score(incumbent_context)
        if _score_success(incumbent_score):
            score = incumbent_score
            score_context = incumbent_context
            current_state = adapter.copy_state(task, valid_incumbent.final_state)
            executed_actions = list(valid_incumbent.executed_actions)
            high_level_plan = list(valid_incumbent.high_level_plan)
            expanded_h0_plan = list(valid_incumbent.expanded_h0_plan)
            level_totals = dict(incumbent_context.level_totals)
            max_level_seen = incumbent_context.max_level_seen
            base_valid_any = incumbent_context.base_valid_any
            hierarchy_valid_any = incumbent_context.hierarchy_valid_any
            last_mapping_count_by_level = dict(
                incumbent_context.last_mapping_count_by_level
            )
            hierarchy_errors_seen = list(
                incumbent_context.hierarchy_errors_seen
            )
            total_top_level_count = incumbent_context.total_top_level_count
            total_h0_count = incumbent_context.total_h0_count
            state_revision = valid_incumbent.state_revision
            last_illegal_reason = None
            termination_reason = "deterministic_valid_incumbent_restored"
            repair_telemetry["valid_incumbent_restored"] = True
            last_outputs = dict(valid_incumbent.outputs)
    if score is None:
        score = adapter.final_score(score_context)

    stage_counts["decision_count"] = stage_counts["plan_generation_count"]
    stage_counts["h2_generation_count"] = stage_counts[
        "hierarchy_generation_count"
    ]
    stage_counts["innerbot_plan_check_count"] = stage_counts[
        "router_check_count"
    ]
    stage_counts["innerbot_plan_llm_call_count"] = stage_counts[
        "router_llm_call_count"
    ]

    model_cache_hits = sum(model_call_cache_hits.values())
    extra_metrics: Dict[str, object] = {
        "max_hierarchy_level": max_level_seen,
        "base_pattern_valid": base_valid_any,
        "hierarchy_valid": hierarchy_valid_any,
        "mapping_count_by_level": {
            str(level): count
            for level, count in sorted(last_mapping_count_by_level.items())
        },
        "level_call_counts": {
            str(level): count for level, count in sorted(level_totals.items())
        },
        "hierarchy_errors": list(hierarchy_errors_seen),
        "router_attributions": list(router_attributions),
        "router_attribution_counts": {
            owner: router_attributions.count(owner)
            for owner in (OWNER_DECISION, OWNER_HIERARCHY, OWNER_BOTH)
        },
        "model_calls_by_stage": dict(sorted(model_calls_by_stage.items())),
        "shared_pipeline_version": PIPELINE_VERSION,
        "selective_repair": True,
        "cache_policy": "validated-artifacts-only",
        "cache_hits": dict(cache_hits),
        "model_call_cache_hits": dict(model_call_cache_hits),
        "model_calls_saved_by_cache": model_cache_hits,
        "invalidation_counts": dict(invalidation_counts),
        "invalidation_log": list(invalidation_log),
        "final_state_revision": state_revision,
        "attempt_semantics": (
            "transactional full-candidate repair rounds"
            if transactional_candidate_execution
            else "one initial pass plus stage-local repair rounds"
        ),
        "verified_prefix_repair": True,
        "repair_boundary": "deterministically-projected-subtask",
        "deterministic_projection_authoritative": online_verification_authoritative,
        "online_verification_feedback": online_verification_authoritative,
        "shortest_valid_incumbent_retained": online_verification_authoritative,
        "classical_planner_used": False,
        "valid_incumbent_candidate_serial": (
            valid_incumbent.candidate_serial
            if valid_incumbent is not None
            else None
        ),
        "valid_incumbent_action_count": (
            valid_incumbent.action_count if valid_incumbent is not None else None
        ),
        **repair_telemetry,
    }

    return SharedLoopResult(
        verifier_mode=str(getattr(adapter, "verifier_mode", "llm")),
        model_call_count=model_call_count,
        replan_count=replan_count,
        termination_reason=termination_reason,
        stage_counts=dict(stage_counts),
        score=score,
        outputs=dict(last_outputs),
        attempts=tuple(attempts),
        extra_metrics=extra_metrics,
        final_state=current_state,
        executed_actions=tuple(executed_actions),
        high_level_plan=tuple(high_level_plan),
        expanded_h0_plan=tuple(expanded_h0_plan),
        parse_errors=tuple(parse_errors),
        router_attributions=tuple(router_attributions),
    )


__all__ = [
    "PIPELINE_VERSION",
    "RepairCandidate",
    "RepairContext",
    "ValidIncumbent",
    "VerifiedRepairAdapter",
    "run_shared_nlevel_loop",
]
