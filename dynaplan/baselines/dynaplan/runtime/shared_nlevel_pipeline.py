"""Domain-agnostic control loop for the dynamic N-level method.

This module owns *control flow*, not a planning domain.  In particular, it is
the single implementation of the pipeline used by the Flat-Hanoi experiment::

    StateDescriptor -> InnerBot state check -> H1 generation
      -> DecisionBot (plan only) -> HierarchyPlanner (H2..Hn)
      -> deterministic per-subtask projection -> InnerBot router
      -> per-subtask execution/commit -> OuterBot -> selective replan

The adapter owns every domain-sensitive operation: state representation,
prompts, parsing the tagged/structured action language, hierarchy expansion,
primitive transitions, checkpoint checks, and final scoring.  This separation
lets a typed PDDL domain such as LexiCon use the exact same retry and state
retention semantics as Hanoi without copying the loop.

Two details are deliberate:

* ``apply_action`` is used both for a speculative projection on a copied state
  and for the real committed execution.  A domain therefore cannot silently
  use a weaker pre-flight verifier than it uses at execution time.
* OuterBot is advisory.  ``TASK SUCCESS`` is accepted only when the adapter's
  deterministic goal predicate also holds.  This is the shared-N-level-v2
  safety rule; an LLM verdict can never turn an invalid environment state into
  a successful benchmark result.

The canonical stage labels used in :class:`StageRequest` are
``state_descriptor``, ``innerbot_state``, ``h1``, ``decision``,
``hierarchy_planner``, ``innerbot_router``, and ``outerbot``.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    Generic,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    TypeVar,
    Union,
    runtime_checkable,
)


OWNER_DECISION = "decision"
OWNER_HIERARCHY = "hierarchy"
OWNER_BOTH = "both"
_OWNERS = {OWNER_DECISION, OWNER_HIERARCHY, OWNER_BOTH}

StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT")
DecisionT = TypeVar("DecisionT")
ScoreT = TypeVar("ScoreT")
ArtifactT = TypeVar("ArtifactT")


@dataclass(frozen=True)
class StageRequest:
    """One model request produced by a domain adapter.

    Structured-output schemas are optional so the same runner supports the
    tagged Flat-Hanoi grammar and LexiCon's typed JSON grammar.
    """

    stage: str
    system: str
    prompt: str
    response_schema: Optional[Dict[str, object]] = None
    schema_name: Optional[str] = None


@dataclass(frozen=True)
class LocalArtifact(Generic[ArtifactT]):
    """An artifact supplied without a model call (for example fixed H1)."""

    value: ArtifactT


ArtifactSource = Union[StageRequest, LocalArtifact[ArtifactT]]


@dataclass(frozen=True)
class ArtifactCheck(Generic[ArtifactT]):
    """Result of parsing or validating a stage artifact."""

    valid: bool
    value: Optional[ArtifactT] = None
    errors: Tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors", tuple(str(error) for error in self.errors))

    @property
    def reason(self) -> str:
        return "; ".join(self.errors) if self.errors else "N/A"

    @classmethod
    def accepted(
        cls,
        value: ArtifactT,
        *,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> "ArtifactCheck[ArtifactT]":
        return cls(True, value, (), dict(metadata or {}))

    @classmethod
    def rejected(
        cls,
        *errors: object,
        value: Optional[ArtifactT] = None,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> "ArtifactCheck[ArtifactT]":
        messages = tuple(str(error) for error in errors if str(error))
        return cls(False, value, messages or ("Artifact was rejected",), dict(metadata or {}))


@dataclass(frozen=True)
class HierarchyStats:
    """Domain-neutral hierarchy facts accumulated by the shared runner."""

    max_level: int = 0
    base_pattern_valid: bool = False
    hierarchy_valid: bool = False
    mapping_count_by_level: Mapping[int, int] = field(default_factory=dict)
    errors: Tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "mapping_count_by_level",
            {int(level): int(count) for level, count in self.mapping_count_by_level.items()},
        )
        object.__setattr__(self, "errors", tuple(str(error) for error in self.errors))


@dataclass(frozen=True)
class PlannedSubtask(Generic[ActionT]):
    """One compiled subtask before deterministic state projection.

    ``top_level_calls`` and ``h0_calls`` remain opaque.  A tagged Hanoi adapter
    can store parsed function-call objects, while a typed LexiCon adapter can
    store its ``FunctionCall`` and ``PrimitiveAction`` values.  Only ``actions``
    are interpreted by the engine, through ``adapter.apply_action``.
    """

    index: int
    description: str = ""
    top_level_calls: Tuple[object, ...] = ()
    h0_calls: Tuple[object, ...] = ()
    actions: Tuple[ActionT, ...] = ()
    level_counts: Mapping[int, int] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "top_level_calls", tuple(self.top_level_calls))
        object.__setattr__(self, "h0_calls", tuple(self.h0_calls))
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(
            self,
            "level_counts",
            {int(level): int(count) for level, count in self.level_counts.items()},
        )


@dataclass(frozen=True)
class CompiledHierarchy(Generic[ActionT]):
    """Executable hierarchy returned by an adapter's compiler."""

    subtasks: Tuple[PlannedSubtask[ActionT], ...]
    stats: HierarchyStats = field(default_factory=HierarchyStats)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "subtasks", tuple(self.subtasks))


@dataclass(frozen=True)
class TransitionResult(Generic[StateT]):
    """Result of one primitive transition.

    On failure, ``state`` must be the last valid state (normally the input
    state).  The engine never commits a failed transition.
    """

    ok: bool
    state: StateT
    reason: str = "N/A"
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectedSubtask(Generic[StateT, ActionT]):
    """A compiled subtask plus its deterministic post-state."""

    plan: PlannedSubtask[ActionT]
    projected_state: StateT
    checkpoint_metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectionResult(Generic[StateT, ActionT]):
    """Result of projecting a complete candidate from the current state."""

    valid: bool
    reason: str
    subtasks: Tuple[ProjectedSubtask[StateT, ActionT], ...]
    final_state: StateT
    failed_subtask_index: Optional[int] = None
    failed_action_index: Optional[int] = None
    failed_action: Optional[ActionT] = None
    checkpoint_failure: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "subtasks", tuple(self.subtasks))


@dataclass(frozen=True)
class RouterVerdict:
    """Parsed InnerBot router output."""

    no_mistake: bool
    owner: str = OWNER_BOTH
    reason: str = "N/A"


@dataclass(frozen=True)
class OuterVerdict:
    """Parsed OuterBot output.

    Adapters should normalize successful-progress verdicts to one of
    ``TASK SUCCESS``, ``SUBTASK SUCCESS``, or ``EXECUTE REMAINING ACTIONS``, and
    failures to ``RECOVERABLE`` or ``NON-RECOVERABLE``.
    """

    status: str
    reason: str = "N/A"


@dataclass(frozen=True)
class FinalScoreContext(Generic[StateT, ActionT]):
    """All execution facts supplied to domain-specific final scoring."""

    task: object
    final_state: StateT
    executed_actions: Tuple[ActionT, ...]
    high_level_plan: Tuple[str, ...]
    expanded_h0_plan: Tuple[str, ...]
    parse_errors: Tuple[str, ...]
    last_illegal_reason: Optional[str]
    total_top_level_count: int
    total_h0_count: int
    level_totals: Mapping[int, int]
    max_level_seen: int
    base_valid_any: bool
    hierarchy_valid_any: bool
    last_mapping_count_by_level: Mapping[int, int]
    hierarchy_errors_seen: Tuple[str, ...]


@dataclass(frozen=True)
class SharedLoopResult(Generic[StateT, ActionT, ScoreT]):
    """Normalized result of the shared N-level runner."""

    verifier_mode: str
    model_call_count: int
    replan_count: int
    termination_reason: str
    stage_counts: Mapping[str, int]
    score: ScoreT
    outputs: Mapping[str, object]
    attempts: Tuple[Mapping[str, object], ...]
    extra_metrics: Mapping[str, object]
    final_state: StateT
    executed_actions: Tuple[ActionT, ...]
    high_level_plan: Tuple[str, ...]
    expanded_h0_plan: Tuple[str, ...]
    parse_errors: Tuple[str, ...]
    router_attributions: Tuple[str, ...]

    def as_dict(self) -> Dict[str, object]:
        """Return a legacy-friendly mapping without coercing the score/state."""

        return {
            "verifier_mode": self.verifier_mode,
            "model_call_count": self.model_call_count,
            "replan_count": self.replan_count,
            "termination_reason": self.termination_reason,
            "stage_counts": dict(self.stage_counts),
            "score": self.score,
            "outputs": dict(self.outputs),
            "attempts": list(self.attempts),
            "extra_metrics": dict(self.extra_metrics),
            "final_state": self.final_state,
            "executed_actions": self.executed_actions,
            "high_level_plan": self.high_level_plan,
            "expanded_h0_plan": self.expanded_h0_plan,
            "parse_errors": self.parse_errors,
            "router_attributions": self.router_attributions,
        }

    def __getitem__(self, key: str) -> object:
        """Permit gradual migration of callers that still use result[key]."""

        try:
            return getattr(self, key)
        except AttributeError as error:
            raise KeyError(key) from error

    def get(self, key: str, default: object = None) -> object:
        return getattr(self, key, default)


@runtime_checkable
class NLevelDomainAdapter(Protocol[StateT, ActionT, DecisionT, ScoreT]):
    """Domain/prompt boundary required by :func:`run_shared_nlevel_loop`.

    Implementations may be ordinary classes; inheriting from this Protocol is
    optional.  State copies must be independent whenever ``apply_action`` can
    mutate its input.  A functional/immutable state may simply be returned by
    ``copy_state``.
    """

    # --- Environment state -------------------------------------------------
    def initial_state(self, task: object) -> StateT:
        ...

    def copy_state(self, task: object, state: StateT) -> StateT:
        ...

    def snapshot_state(self, task: object, state: StateT) -> object:
        ...

    def render_state(self, task: object, state: StateT) -> object:
        ...

    def goal_reached(self, task: object, state: StateT) -> bool:
        ...

    def apply_action(
        self,
        task: object,
        state: StateT,
        action: ActionT,
        action_index: int,
    ) -> TransitionResult[StateT]:
        ...

    # --- StateDescriptor / InnerBot state check ----------------------------
    def fixed_state_descriptor(
        self, task: object, state: StateT, scene: object
    ) -> object:
        ...

    def state_descriptor_request(
        self,
        task: object,
        state: StateT,
        scene: object,
        previous_state_output: object,
        feedback: str,
    ) -> StageRequest:
        ...

    def validate_state_descriptor(
        self,
        task: object,
        state: StateT,
        scene: object,
        output: object,
    ) -> ArtifactCheck[object]:
        ...

    def inner_state_request(
        self,
        task: object,
        state: StateT,
        scene: object,
        state_output: object,
    ) -> StageRequest:
        ...

    def parse_inner_state(self, output: str) -> Tuple[bool, str]:
        ...

    # --- H1 / DecisionBot / HierarchyPlanner -------------------------------
    def h1_source(
        self,
        task: object,
        state: StateT,
        scene: object,
        feedback: str,
    ) -> Union[StageRequest, LocalArtifact[object]]:
        ...

    def decision_request(
        self,
        task: object,
        state: StateT,
        scene: object,
        state_output: object,
        h1_output: object,
        feedback: str,
    ) -> StageRequest:
        ...

    def parse_decision(
        self, task: object, output: str
    ) -> ArtifactCheck[DecisionT]:
        ...

    def hierarchy_request(
        self,
        task: object,
        state: StateT,
        scene: object,
        state_output: object,
        h1_output: object,
        decision_output: str,
        feedback: str,
        include_code_block: bool,
    ) -> StageRequest:
        ...

    def compile_hierarchy(
        self,
        task: object,
        state: StateT,
        h1_output: object,
        decision_output: str,
        decision: Optional[DecisionT],
        hierarchy_output: str,
    ) -> ArtifactCheck[CompiledHierarchy[ActionT]]:
        ...

    # --- Deterministic checkpoints / verifiers -----------------------------
    def validate_projected_subtask(
        self,
        task: object,
        decision: DecisionT,
        subtask: PlannedSubtask[ActionT],
        projected_state: StateT,
        is_last: bool,
    ) -> ArtifactCheck[object]:
        ...

    def router_request(
        self,
        task: object,
        state: StateT,
        scene: object,
        state_output: object,
        decision_output: str,
        hierarchy_output: str,
        projection: ProjectionResult[StateT, ActionT],
        execution_feedback: Optional[str] = None,
    ) -> StageRequest:
        ...

    def parse_router(self, output: str) -> RouterVerdict:
        ...

    def outer_request(
        self,
        task: object,
        decision: DecisionT,
        hierarchy: CompiledHierarchy[ActionT],
        subtask: ProjectedSubtask[StateT, ActionT],
        previous_state: StateT,
        current_state: StateT,
        is_last: bool,
    ) -> StageRequest:
        ...

    def parse_outer(self, output: str) -> OuterVerdict:
        ...

    # --- Presentation / accounting ----------------------------------------
    def format_action(self, action: ActionT) -> object:
        ...

    def format_call(self, call: object) -> str:
        ...

    def reasoning_effort_for(
        self, stage: str, base_effort: Optional[str]
    ) -> Optional[str]:
        ...

    def final_score(self, context: FinalScoreContext[StateT, ActionT]) -> ScoreT:
        ...


# A descriptive alias for callers that regard prompts/compilation as part of
# the benchmark adapter rather than the task domain itself.
SharedNLevelAdapter = NLevelDomainAdapter


def new_stage_counts() -> Dict[str, int]:
    """The Flat-Hanoi counters, including legacy aliases added at completion."""

    return {
        "scene_descriptor_count": 0,
        "state_descriptor_count": 0,
        "h1_generation_count": 0,
        "plan_generation_count": 0,
        "hierarchy_generation_count": 0,
        "innerbot_state_check_count": 0,
        "innerbot_state_llm_call_count": 0,
        "router_check_count": 0,
        "router_llm_call_count": 0,
        "outerbot_check_count": 0,
        "outerbot_llm_call_count": 0,
        "executed_subtask_count": 0,
    }


def project_compiled_hierarchy(
    task: object,
    adapter: NLevelDomainAdapter[StateT, ActionT, DecisionT, ScoreT],
    current_state: StateT,
    decision: DecisionT,
    hierarchy: CompiledHierarchy[ActionT],
) -> ProjectionResult[StateT, ActionT]:
    """Expand a compiled candidate through the domain's real transition rule.

    This is the domain-neutral counterpart of Flat-Hanoi's
    ``validate_dynamic_plan``.  It projects each subtask in order and stores an
    independent post-state for OuterBot.  The optional checkpoint hook makes
    the projection explicitly correspond to the matching DecisionBot subtask;
    LexiCon can therefore validate target facts at subtask boundaries, while a
    parity Hanoi adapter can return an unconditional accepted check.
    """

    simulated_state = adapter.copy_state(task, current_state)
    projected: List[ProjectedSubtask[StateT, ActionT]] = []
    action_index = 0
    subtask_count = len(hierarchy.subtasks)

    for position, subtask in enumerate(hierarchy.subtasks):
        for action in subtask.actions:
            action_index += 1
            transition = adapter.apply_action(
                task, simulated_state, action, action_index
            )
            if not transition.ok:
                return ProjectionResult(
                    valid=False,
                    reason=transition.reason or "Deterministic action projection failed",
                    subtasks=tuple(projected),
                    final_state=simulated_state,
                    failed_subtask_index=subtask.index,
                    failed_action_index=action_index,
                    failed_action=action,
                    metadata=dict(transition.metadata),
                )
            simulated_state = transition.state

        projected_state = adapter.copy_state(task, simulated_state)
        checkpoint_validator = getattr(adapter, "validate_projected_subtask", None)
        if callable(checkpoint_validator):
            raw_checkpoint = checkpoint_validator(
                task,
                decision,
                subtask,
                projected_state,
                position == subtask_count - 1,
            )
            checkpoint = _coerce_artifact_check(raw_checkpoint)
        else:
            checkpoint = ArtifactCheck.accepted(None)

        if not checkpoint.valid:
            return ProjectionResult(
                valid=False,
                reason=(
                    f"Subtask {subtask.index} checkpoint failed: "
                    f"{checkpoint.reason}"
                ),
                subtasks=tuple(projected),
                final_state=projected_state,
                failed_subtask_index=subtask.index,
                checkpoint_failure=True,
                metadata=dict(checkpoint.metadata),
            )

        projected.append(
            ProjectedSubtask(
                plan=subtask,
                projected_state=projected_state,
                checkpoint_metadata=dict(checkpoint.metadata),
            )
        )

    return ProjectionResult(
        valid=True,
        reason="N/A",
        subtasks=tuple(projected),
        final_state=adapter.copy_state(task, simulated_state),
    )


def run_shared_nlevel_loop(
    task: object,
    client: object,
    adapter: NLevelDomainAdapter[StateT, ActionT, DecisionT, ScoreT],
    *,
    fixed_goal: bool,
    max_tokens: int,
    max_replans: int,
    reuse_h1: bool,
    include_code_block: bool,
    reasoning_effort: Optional[str] = None,
    final_score_task: Optional[object] = None,
) -> SharedLoopResult[StateT, ActionT, ScoreT]:
    """Run the shared dynamic N-level pipeline.

    ``max_replans`` counts correction rounds after the initial attempt, so the
    loop performs at most ``max_replans + 1`` attempts.  Only a hierarchy-owned
    rejection keeps the DecisionBot plan.  State changes that were actually
    committed before a recoverable failure survive into the next attempt.

    ``task`` is the planning-loop view.  ``final_score_task`` may carry private
    evaluator metadata (for example an optimum) and is used only after all
    model calls and online execution have finished.  This makes oracle fields
    structurally inaccessible throughout planning without weakening final
    authoritative scoring.
    """

    if max_replans < 0:
        raise ValueError("max_replans must be non-negative")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    current_state = adapter.initial_state(task)
    executed_actions: List[ActionT] = []
    high_level_plan: List[str] = []
    expanded_h0_plan: List[str] = []
    parse_errors: List[str] = []
    attempts: List[Dict[str, object]] = []
    router_attributions: List[str] = []

    feedback = ""
    plan_output: Optional[str] = None
    h1_output: Optional[object] = None
    regenerate_plan = True
    model_call_count = 0
    model_calls_by_stage: Dict[str, int] = {}
    stage_counts = new_stage_counts()

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
    previous_state_output: object = "N/A"
    initial_scene = adapter.render_state(task, current_state)
    last_outputs: Dict[str, object] = {"scene_json": initial_scene}

    def call(request: StageRequest) -> str:
        nonlocal model_call_count
        model_call_count += 1
        model_calls_by_stage[request.stage] = model_calls_by_stage.get(request.stage, 0) + 1
        effort_resolver = getattr(adapter, "reasoning_effort_for", None)
        effort = (
            effort_resolver(request.stage, reasoning_effort)
            if callable(effort_resolver)
            else reasoning_effort
        )
        return _call_client(client, request, max_tokens, effort)

    def route(owner: str) -> str:
        """Apply Flat-Hanoi routing: only hierarchy ownership keeps the plan."""

        nonlocal regenerate_plan
        canonical = _canonical_owner(owner)
        router_attributions.append(canonical)
        regenerate_plan = canonical != OWNER_HIERARCHY
        return canonical

    for attempt_index in range(max_replans + 1):
        try:
            feedback_in = feedback
            scene = adapter.render_state(task, current_state)
            stage_counts["scene_descriptor_count"] += 1

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
            else:
                state_output = call(
                    adapter.state_descriptor_request(
                        task,
                        current_state,
                        scene,
                        previous_state_output,
                        feedback or "N/A",
                    )
                )
                previous_state_output = state_output

            descriptor_check = _coerce_artifact_check(
                adapter.validate_state_descriptor(
                    task, current_state, scene, state_output
                )
            )

            stage_counts["innerbot_state_check_count"] += 1
            stage_counts["innerbot_state_llm_call_count"] += 1
            innerbot_state_output = call(
                adapter.inner_state_request(
                    task, current_state, scene, state_output
                )
            )
            inner_valid, inner_reason = adapter.parse_inner_state(innerbot_state_output)
            state_valid = descriptor_check.valid and bool(inner_valid)
            state_reason = (
                "N/A"
                if state_valid
                else descriptor_check.reason
                if not descriptor_check.valid
                else str(inner_reason)
            )
            if not state_valid:
                feedback = f"InnerBot state verifier rejected the state descriptor: {state_reason}"
                parse_errors.append(f"InnerBotState: {state_reason}")
                regenerate_plan = True
                attempts.append(
                    {
                        "attempt_index": attempt_index,
                        "input_state": adapter.snapshot_state(task, current_state),
                        "feedback_in": feedback_in,
                        "innerbot_state_check": {
                            "result": "NO",
                            "reason": state_reason,
                            "deterministic_descriptor_valid": descriptor_check.valid,
                        },
                        "stage_outputs": {
                            "scene_json": scene,
                            "state_output": state_output,
                            "innerbot_state_output": innerbot_state_output,
                        },
                        "events": [],
                        "verdict": "REPLAN",
                        "feedback_out": feedback,
                    }
                )
                continue

            if h1_output is None or not reuse_h1:
                h1_source = adapter.h1_source(
                    task, current_state, scene, feedback
                )
                if isinstance(h1_source, StageRequest):
                    stage_counts["h1_generation_count"] += 1
                    h1_output = call(h1_source)
                elif isinstance(h1_source, LocalArtifact):
                    h1_output = h1_source.value
                else:
                    raise TypeError(
                        "adapter.h1_source() must return StageRequest or LocalArtifact"
                    )

            plan_regenerated = regenerate_plan or plan_output is None
            if plan_regenerated:
                stage_counts["plan_generation_count"] += 1
                plan_output = call(
                    adapter.decision_request(
                        task,
                        current_state,
                        scene,
                        state_output,
                        h1_output,
                        feedback,
                    )
                )
            assert plan_output is not None
            decision_check = _coerce_artifact_check(
                adapter.parse_decision(task, plan_output)
            )

            # Flat-Hanoi always gives the raw DecisionBot output to the
            # HierarchyPlanner before rejecting either artifact.  Keeping that
            # ordering here is part of using the exact same stage flow.
            stage_counts["hierarchy_generation_count"] += 1
            hierarchy_output = call(
                adapter.hierarchy_request(
                    task,
                    current_state,
                    scene,
                    state_output,
                    h1_output,
                    plan_output,
                    feedback,
                    include_code_block,
                )
            )
            hierarchy_check = _coerce_artifact_check(
                adapter.compile_hierarchy(
                    task,
                    current_state,
                    h1_output,
                    plan_output,
                    decision_check.value,
                    hierarchy_output,
                )
            )

            last_outputs = {
                "scene_json": scene,
                "state_output": state_output,
                "innerbot_state_output": innerbot_state_output,
                "h1_output": h1_output,
                "plan_output": plan_output,
                "decision_output": plan_output,
                "hierarchy_output": hierarchy_output,
            }
            attempt: Dict[str, object] = {
                "attempt_index": attempt_index,
                "input_state": adapter.snapshot_state(task, current_state),
                "feedback_in": feedback_in,
                "plan_regenerated": plan_regenerated,
                "innerbot_state_check": {
                    "result": "YES",
                    "reason": str(inner_reason),
                    "deterministic_descriptor_valid": descriptor_check.valid,
                },
                "events": [],
                "stage_outputs": dict(last_outputs),
                "decision_validation": _check_payload(decision_check),
                "hierarchy_validation": _check_payload(hierarchy_check),
            }

            plan_errors = [f"Plan: {error}" for error in decision_check.errors]
            # The hierarchy adapter owns its grammar and therefore supplies
            # already-attributed diagnostics (Flat Hanoi distinguishes H1,
            # hierarchy mappings, call blocks, and expansion errors here).
            hierarchy_errors = list(hierarchy_check.errors)
            parse_errors.extend(plan_errors + hierarchy_errors)
            hierarchy = hierarchy_check.value
            if hierarchy is not None:
                stats = hierarchy.stats
                base_valid_any = base_valid_any or stats.base_pattern_valid
                hierarchy_valid_any = hierarchy_valid_any or stats.hierarchy_valid
                max_level_seen = max(max_level_seen, stats.max_level)
                last_mapping_count_by_level = dict(stats.mapping_count_by_level)
                for error in stats.errors:
                    if error not in hierarchy_errors_seen:
                        hierarchy_errors_seen.append(error)

            missing_subtasks = hierarchy is None or not hierarchy.subtasks
            if not decision_check.valid or not hierarchy_check.valid or missing_subtasks:
                combined = plan_errors + hierarchy_errors
                if missing_subtasks and not hierarchy_errors:
                    combined.append("Hierarchy: no executable subtasks were produced")
                feedback = "Hierarchy or plan could not be parsed: " + "; ".join(combined)
                owner = OWNER_DECISION if not decision_check.valid else OWNER_HIERARCHY
                canonical_owner = route(owner)
                stage_counts["router_check_count"] += 1
                attempt["router_check"] = {
                    "result": "NO",
                    "owner": canonical_owner,
                    "reason": feedback,
                    "source": "deterministic",
                }
                attempt["verdict"] = "REPLAN"
                attempt["feedback_out"] = feedback
                attempts.append(attempt)
                continue

            assert hierarchy is not None
            assert decision_check.value is not None
            projection = project_compiled_hierarchy(
                task,
                adapter,
                current_state,
                decision_check.value,
                hierarchy,
            )

            stage_counts["router_check_count"] += 1
            if not projection.valid:
                feedback = f"Symbolic validation rejected the hierarchy: {projection.reason}"
                parse_errors.append(f"Symbolic: {projection.reason}")
                canonical_owner = route(OWNER_HIERARCHY)
                attempt["projection"] = _projection_payload(
                    adapter, task, projection
                )
                attempt["router_check"] = {
                    "result": "NO",
                    "owner": canonical_owner,
                    "reason": projection.reason,
                    "source": "symbolic",
                }
                attempt["verdict"] = "REPLAN"
                attempt["feedback_out"] = feedback
                attempts.append(attempt)
                continue

            stage_counts["router_llm_call_count"] += 1
            router_output = call(
                adapter.router_request(
                    task,
                    current_state,
                    scene,
                    state_output,
                    plan_output,
                    hierarchy_output,
                    projection,
                )
            )
            last_outputs["router_output"] = router_output
            attempt["stage_outputs"]["router_output"] = router_output
            router_verdict = adapter.parse_router(router_output)
            owner = _canonical_owner(router_verdict.owner)
            if not router_verdict.no_mistake:
                feedback = (
                    f"InnerBot router assigned the mistake to {owner}: "
                    f"{router_verdict.reason}"
                )
                parse_errors.append(f"Router: {router_verdict.reason}")
                route(owner)
                attempt["router_check"] = {
                    "result": "NO",
                    "owner": owner,
                    "reason": router_verdict.reason,
                    "source": "llm",
                }
                attempt["verdict"] = "REPLAN"
                attempt["feedback_out"] = feedback
                attempts.append(attempt)
                continue

            attempt["router_check"] = {
                "result": "YES",
                "owner": "NA",
                "reason": router_verdict.reason,
            }
            attempt["projection"] = _projection_payload(adapter, task, projection)
            replan_required = False
            solved = False

            for position, projected_subtask in enumerate(projection.subtasks):
                subtask = projected_subtask.plan
                previous_state = adapter.copy_state(task, current_state)

                total_top_level_count += len(subtask.top_level_calls)
                total_h0_count += len(subtask.h0_calls)
                for level, count in subtask.level_counts.items():
                    level_totals[int(level)] = level_totals.get(int(level), 0) + int(count)
                high_level_plan.extend(
                    adapter.format_call(item) for item in subtask.top_level_calls
                )
                expanded_h0_plan.extend(
                    adapter.format_call(item) for item in subtask.h0_calls
                )

                executed_this_subtask: List[object] = []
                for action in subtask.actions:
                    action_number = len(executed_actions) + 1
                    transition = adapter.apply_action(
                        task, current_state, action, action_number
                    )
                    if not transition.ok:
                        last_illegal_reason = transition.reason
                        feedback = (
                            f"Recoverable execution error at action {action_number}: "
                            f"{transition.reason}. Current state is "
                            f"{adapter.snapshot_state(task, current_state)}. "
                            "Rebuild the hierarchy from this state."
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
                        route(OWNER_HIERARCHY)
                        replan_required = True
                        break
                    current_state = transition.state
                    executed_actions.append(action)
                    executed_this_subtask.append(adapter.format_action(action))

                if replan_required:
                    break

                stage_counts["executed_subtask_count"] += 1
                stage_counts["scene_descriptor_count"] += 1
                stage_counts["outerbot_check_count"] += 1
                stage_counts["outerbot_llm_call_count"] += 1
                outerbot_output = call(
                    adapter.outer_request(
                        task,
                        decision_check.value,
                        hierarchy,
                        projected_subtask,
                        previous_state,
                        current_state,
                        position == len(projection.subtasks) - 1,
                    )
                )
                last_outputs["outerbot_output"] = outerbot_output
                outer_verdict = adapter.parse_outer(outerbot_output)
                outer_status = _canonical_outer_status(outer_verdict.status)
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
                    # Hanoi's legacy consumers call this field executed_moves.
                    "executed_moves": executed_this_subtask,
                    "state": adapter.snapshot_state(task, current_state),
                }
                attempt["events"].append(event)

                if outer_status == "TASK SUCCESS":
                    if _goal_reached(adapter, task, current_state):
                        feedback = ""
                        solved = True
                        break
                    # Shared v2 safety: an LLM cannot override the deterministic
                    # environment goal/constraint predicate.
                    guard_reason = (
                        "OuterBot claimed TASK SUCCESS, but deterministic goal "
                        "and constraint validation is false"
                    )
                    event["deterministic_goal_guard"] = {
                        "accepted": False,
                        "reason": guard_reason,
                    }
                    feedback = (
                        f"{guard_reason}. Current state is "
                        f"{adapter.snapshot_state(task, current_state)}."
                    )
                    parse_errors.append(f"OuterBot: {guard_reason}")
                    route(OWNER_BOTH)
                    replan_required = True
                    break

                if outer_status in {
                    "SUBTASK SUCCESS",
                    "EXECUTE REMAINING ACTIONS",
                }:
                    continue

                # RECOVERABLE, NON-RECOVERABLE, and any adapter-specific failure
                # verdict all go back through the same InnerBot router.
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
                recheck_output = call(
                    adapter.router_request(
                        task,
                        current_state,
                        current_scene,
                        state_output,
                        plan_output,
                        hierarchy_output,
                        projection,
                        execution_feedback=execution_feedback,
                    )
                )
                last_outputs["router_output"] = recheck_output
                recheck = adapter.parse_router(recheck_output)
                recheck_owner = route(recheck.owner)
                event["router_owner"] = recheck_owner
                event["router_reason"] = recheck.reason
                event["normalized_failure_verdict"] = normalized_failure
                feedback = (
                    f"{execution_feedback} Router assigned this to "
                    f"{recheck_owner}: {recheck.reason}"
                )
                replan_required = True
                if normalized_failure == "NON-RECOVERABLE":
                    last_illegal_reason = outer_verdict.reason
                    termination_reason = "non_recoverable"
                break

            attempt["output_state"] = adapter.snapshot_state(task, current_state)
            if solved:
                attempt["verdict"] = "TASK SUCCESS"
                attempt["feedback_out"] = ""
                attempts.append(attempt)
                termination_reason = "task_success"
                break

            if replan_required:
                attempt["verdict"] = "REPLAN"
                attempt["feedback_out"] = feedback
                attempts.append(attempt)
                if termination_reason == "non_recoverable":
                    break
                continue

            feedback = (
                "Plan finished without an OuterBot-confirmed, deterministic "
                f"final goal. Current state is {adapter.snapshot_state(task, current_state)}. "
                "Generate a corrected plan from this state."
            )
            route(OWNER_BOTH)
            attempt["verdict"] = "REPLAN"
            attempt["feedback_out"] = feedback
            attempts.append(attempt)
        except Exception as error:
            if not _is_truncated_response(error):
                raise
            attempts.append(
                {
                    "attempt_index": attempt_index,
                    "input_state": adapter.snapshot_state(task, current_state),
                    "feedback_in": feedback,
                    "events": [],
                    "verdict": "REPLAN",
                    "feedback_out": f"Truncated: {error}",
                }
            )
            feedback = f"Truncated: {error} Retry with a more concise response."
            continue

    replan_count = sum(
        1 for attempt in attempts[:-1] if attempt.get("verdict") == "REPLAN"
    )
    if _goal_reached(adapter, task, current_state):
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
    score = adapter.final_score(score_context)

    # Back-compatible aliases used by the existing Hanoi metrics/figures.
    stage_counts["decision_count"] = stage_counts["plan_generation_count"]
    stage_counts["h2_generation_count"] = stage_counts["hierarchy_generation_count"]
    stage_counts["innerbot_plan_check_count"] = stage_counts["router_check_count"]
    stage_counts["innerbot_plan_llm_call_count"] = stage_counts[
        "router_llm_call_count"
    ]

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
        "shared_pipeline_version": "shared_nlevel_v2",
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


def _call_client(
    client: object,
    request: StageRequest,
    max_tokens: int,
    reasoning_effort: Optional[str],
) -> str:
    """Call a ModelClient while remaining compatible with small test doubles."""

    generate = getattr(client, "generate", None)
    if not callable(generate):
        raise TypeError("client must expose a callable generate() method")

    candidate_kwargs: Dict[str, object] = {
        "system": request.system,
        "prompt": request.prompt,
        "max_tokens": max_tokens,
    }
    if request.response_schema is not None:
        candidate_kwargs["response_schema"] = request.response_schema
        candidate_kwargs["schema_name"] = request.schema_name
    if reasoning_effort is not None:
        candidate_kwargs["reasoning_effort"] = reasoning_effort

    try:
        signature = inspect.signature(generate)
    except (TypeError, ValueError):
        kwargs = candidate_kwargs
    else:
        parameters = signature.parameters
        accepts_arbitrary = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        kwargs = (
            candidate_kwargs
            if accepts_arbitrary
            else {
                key: value
                for key, value in candidate_kwargs.items()
                if key in parameters
            }
        )

    output = generate(**kwargs)
    if not isinstance(output, str):
        raise TypeError(
            f"Model stage {request.stage!r} returned {type(output).__name__}; expected str"
        )
    return output


def _coerce_artifact_check(value: object) -> ArtifactCheck[Any]:
    """Accept the documented dataclass plus lightweight test-adapter forms."""

    if isinstance(value, ArtifactCheck):
        return value
    if isinstance(value, bool):
        return ArtifactCheck(value, None, () if value else ("Artifact was rejected",))
    if isinstance(value, tuple):
        if len(value) == 2 and isinstance(value[0], bool):
            valid, second = value
            if valid:
                return ArtifactCheck.accepted(second)
            return ArtifactCheck.rejected(second)
        if len(value) == 3 and isinstance(value[0], bool):
            valid, artifact, reason = value
            return ArtifactCheck(
                valid=valid,
                value=artifact,
                errors=() if valid else (str(reason),),
            )
    raise TypeError(
        "Adapter validation hooks must return ArtifactCheck (or a supported "
        "boolean/tuple shorthand)"
    )


def _canonical_owner(owner: object) -> str:
    normalized = str(owner).strip().lower()
    aliases = {
        "decisionbot": OWNER_DECISION,
        "decision_bot": OWNER_DECISION,
        "planner": OWNER_DECISION,
        "hierarchyplanner": OWNER_HIERARCHY,
        "hierarchy_planner": OWNER_HIERARCHY,
        "h2": OWNER_HIERARCHY,
        "both": OWNER_BOTH,
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in _OWNERS else OWNER_BOTH


def _canonical_outer_status(status: object) -> str:
    return " ".join(str(status).strip().upper().replace("_", " ").split())


def _goal_reached(
    adapter: NLevelDomainAdapter[StateT, ActionT, DecisionT, ScoreT],
    task: object,
    state: StateT,
) -> bool:
    """Support ``is_goal`` as a spelling alias while keeping one protocol."""

    is_goal = getattr(adapter, "is_goal", None)
    if callable(is_goal):
        return bool(is_goal(task, state))
    return bool(adapter.goal_reached(task, state))


def _check_payload(check: ArtifactCheck[object]) -> Dict[str, object]:
    return {
        "valid": check.valid,
        "errors": list(check.errors),
        "metadata": dict(check.metadata),
    }


def _projection_payload(
    adapter: NLevelDomainAdapter[StateT, ActionT, DecisionT, ScoreT],
    task: object,
    projection: ProjectionResult[StateT, ActionT],
) -> Dict[str, object]:
    return {
        "valid": projection.valid,
        "reason": projection.reason,
        "failed_subtask_index": projection.failed_subtask_index,
        "failed_action_index": projection.failed_action_index,
        "failed_action": (
            adapter.format_action(projection.failed_action)
            if projection.failed_action is not None
            else None
        ),
        "checkpoint_failure": projection.checkpoint_failure,
        "projected_subtasks": [
            {
                "subtask_index": item.plan.index,
                "state": adapter.snapshot_state(task, item.projected_state),
                "checkpoint_metadata": dict(item.checkpoint_metadata),
            }
            for item in projection.subtasks
        ],
        "final_state": adapter.snapshot_state(task, projection.final_state),
        "metadata": dict(projection.metadata),
    }


def _is_truncated_response(error: BaseException) -> bool:
    """Avoid importing a provider module solely for one recoverable exception."""

    return error.__class__.__name__ == "TruncatedResponseError" or bool(
        getattr(error, "truncated", False)
    )


__all__ = [
    "OWNER_BOTH",
    "OWNER_DECISION",
    "OWNER_HIERARCHY",
    "ArtifactCheck",
    "ArtifactSource",
    "CompiledHierarchy",
    "FinalScoreContext",
    "HierarchyStats",
    "LocalArtifact",
    "NLevelDomainAdapter",
    "OuterVerdict",
    "PlannedSubtask",
    "ProjectedSubtask",
    "ProjectionResult",
    "RouterVerdict",
    "SharedLoopResult",
    "SharedNLevelAdapter",
    "StageRequest",
    "TransitionResult",
    "new_stage_counts",
    "project_compiled_hierarchy",
    "run_shared_nlevel_loop",
]
