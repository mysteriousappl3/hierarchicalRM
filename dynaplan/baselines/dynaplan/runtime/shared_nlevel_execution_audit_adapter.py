"""Execution-boundary InnerBot adapter for the v5 LLM-only ablation.

The adapter exposes the hierarchy compiler's canonical H0 expansion, grouped
by Decision subtask, to one InnerBot Router call.  It deliberately exposes no
action-applicability, projected-state, checkpoint, goal, temporal-constraint,
or official-evaluator verdict.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Dict, List, Mapping, Optional, Tuple

import shared_nlevel_lexicon as lexicon
import shared_nlevel_blocksworld as blocksworld
from lexicon_blocksworld_task import (
    LexiconBlocksworldTask,
    PlanVerification as BlocksworldPlanVerification,
    PrimitiveAction as BlocksworldPrimitiveAction,
    verify_plan as verify_blocksworld_plan,
)
from shared_nlevel_pipeline import (
    ArtifactCheck,
    PlannedSubtask,
    RouterVerdict,
    StageRequest,
    TransitionResult,
)
from shared_nlevel_verified_repair_blocksworld import (
    VerifiedRepairBlocksworldNLevelAdapter,
)
from shared_nlevel_verifier_ablation_adapters import LLMOnlyLexiconAdapter


PIPELINE_VERSION = "shared_nlevel_v5_llm_only_execution_audit"
EXECUTION_AUDIT_IMPLEMENTATION_REVISION = (
    "shared_nlevel_v5_llm_only_execution_audit_v2_transactional"
)
SYSTEM_EXECUTION_AUDIT_ROUTER = (
    "InnerBot execution-boundary auditor: validate the composed hierarchy and "
    "its canonical primitive expansion using only the supplied public rules."
)
SYSTEM_EXECUTION_AUDIT_OUTER_BLOCKSWORLD = (
    "OuterBot for the v5 LLM-only Blocksworld ablation: judge a subtask from "
    "public rules, actions, checkpoints, and unchecked shadow states."
)

EXECUTION_AUDIT_SCHEMA: Dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict",
        "first_bad_subtask",
        "first_bad_action_in_subtask",
        "owner",
        "reason",
    ],
    "properties": {
        "verdict": {"type": "string", "enum": ["VALID", "INVALID"]},
        "first_bad_subtask": {"type": "integer", "minimum": 0},
        "first_bad_action_in_subtask": {"type": "integer", "minimum": 0},
        "owner": {
            "type": "string",
            "enum": ["NA", "DecisionBot", "HierarchyPlanner", "both"],
        },
        "reason": {"type": "string"},
    },
}


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _execution_boundary_payload(adapter: object, projection: object) -> List[Dict[str, object]]:
    """Serialize structural compiler output without semantic projection state."""

    payload: List[Dict[str, object]] = []
    for projected in getattr(projection, "subtasks", ()):
        plan = getattr(projected, "plan", projected)
        payload.append(
            {
                "subtask_index": int(getattr(plan, "index", 0)),
                "objective": str(getattr(plan, "description", "")),
                "composed_calls": [
                    adapter.format_call(call)
                    for call in getattr(plan, "top_level_calls", ())
                ],
                "expanded_execution_actions": [
                    adapter.format_call(call)
                    for call in getattr(plan, "h0_calls", ())
                ],
            }
        )
    return payload


def execution_audit_router_prompt(
    *,
    problem_text: str,
    descriptor_output: str,
    decision_output: str,
    hierarchy_output: str,
    execution_boundary_actions: List[Mapping[str, object]],
    feedback: Optional[str],
) -> str:
    """Build the domain-rule-grounded, verifier-free InnerBot audit prompt."""

    total_actions = sum(
        len(item.get("expanded_execution_actions", ()))
        for item in execution_boundary_actions
    )
    withheld = {
        "semantic_verification": "WITHHELD",
        "structural_compilation_succeeded": True,
        "compiled_subtask_count": len(execution_boundary_actions),
        "candidate_execution_action_count": total_actions,
        "official_evaluator_available_during_planning": False,
    }
    return f"""You are the InnerBot execution-boundary auditor.

DecisionBot supplied semantic checkpoints but no actions. HierarchyPlanner
supplied composed mappings and calls. A deterministic structural compiler
expanded those calls into the canonical execution-boundary sequence shown
below. Structural expansion proves only that names, bindings, and the call
graph are representable; it does not prove that any action is applicable or
that any checkpoint, goal, or temporal constraint is satisfied.

Using only the public task rules, audit the expanded actions sequentially from
the stated current state. Mentally apply each action's explicit effects before
checking the next action. Check subtask checkpoints at their boundaries and
the task goals and temporal constraints at the end. Use the composed calls to
identify which artifact owns the earliest error.

PUBLIC TASK AND ACTION RULES:
{problem_text}

CURRENT STATE DESCRIPTOR:
{descriptor_output}

DECISIONBOT CHECKPOINTS:
{decision_output}

COMPOSED HIERARCHY:
{hierarchy_output}

CANONICAL EXECUTION-BOUNDARY ACTIONS BY SUBTASK:
{_json(execution_boundary_actions)}

SEMANTIC-VERIFICATION RECORD:
{_json(withheld)}

ADDITIONAL FEEDBACK:
{feedback or 'N/A'}

Return `VALID` only after checking the complete ordered action sequence and all
final requirements. For `VALID`, both indices must be 0 and owner must be `NA`.
For `INVALID`, report the one-based earliest failing subtask and one-based
action within that subtask. If a checkpoint/decomposition is wrong, use action
index 0. Owner is `DecisionBot` for a bad decomposition/checkpoint,
`HierarchyPlanner` for bad mappings/calls, or `both` when both independently
need changes. Give only the compact object required by the response schema.
"""


class ExecutionAuditLLMOnlyLexiconAdapter(LLMOnlyLexiconAdapter):
    """LLM-only semantics with explicit composed-plus-expanded InnerBot input."""

    verifier_mode = "llm-only-execution-audit-online; official-pddl-final-only"
    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = (
        EXECUTION_AUDIT_IMPLEMENTATION_REVISION
    )
    transactional_candidate_execution = True

    def __init__(self) -> None:
        super().__init__()
        self.execution_audit_records: List[Dict[str, object]] = []

    def router_request(
        self,
        task: object,
        state: object,
        scene: object,
        state_output: str,
        decision_output: str,
        hierarchy_output: str,
        projection: object,
        execution_feedback: Optional[str] = None,
    ) -> StageRequest:
        del state, scene
        boundary = _execution_boundary_payload(self, projection)
        return StageRequest(
            stage="innerbot_router",
            system=SYSTEM_EXECUTION_AUDIT_ROUTER,
            prompt=execution_audit_router_prompt(
                problem_text=lexicon._model_task_text(task),
                descriptor_output=state_output,
                decision_output=decision_output,
                hierarchy_output=hierarchy_output,
                execution_boundary_actions=boundary,
                feedback=execution_feedback,
            ),
            response_schema=EXECUTION_AUDIT_SCHEMA,
            schema_name="n_hierarchy_execution_boundary_audit_v1",
        )

    def parse_router(self, output: str) -> RouterVerdict:
        try:
            payload = json.loads(output)
            if not isinstance(payload, dict) or set(payload) != set(
                EXECUTION_AUDIT_SCHEMA["required"]
            ):
                raise ValueError("audit response has incorrect fields")
            verdict = str(payload["verdict"])
            subtask = int(payload["first_bad_subtask"])
            action = int(payload["first_bad_action_in_subtask"])
            owner_text = str(payload["owner"])
            reason = str(payload["reason"]).strip() or "N/A"
            if verdict == "VALID":
                if subtask != 0 or action != 0 or owner_text != "NA":
                    raise ValueError("VALID requires zero indices and owner NA")
                normalized_owner = "both"
                no_mistake = True
            elif verdict == "INVALID":
                if subtask <= 0 or action < 0 or owner_text == "NA":
                    raise ValueError(
                        "INVALID requires a positive subtask and non-NA owner"
                    )
                normalized_owner = {
                    "DecisionBot": "decision",
                    "HierarchyPlanner": "hierarchy",
                    "both": "both",
                }.get(owner_text, "both")
                no_mistake = False
                reason = (
                    f"Subtask {subtask}, action {action}: {reason}"
                    if action
                    else f"Subtask {subtask}, checkpoint/decomposition: {reason}"
                )
            else:
                raise ValueError(f"unknown verdict {verdict!r}")
            record = {
                "verdict": verdict,
                "first_bad_subtask": subtask,
                "first_bad_action_in_subtask": action,
                "owner": owner_text,
                "reason": str(payload["reason"]),
                "parse_valid": True,
            }
            self.execution_audit_records.append(record)
            return RouterVerdict(no_mistake, normalized_owner, reason)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            self.execution_audit_records.append(
                {
                    "verdict": "INVALID",
                    "first_bad_subtask": 0,
                    "first_bad_action_in_subtask": 0,
                    "owner": "both",
                    "reason": f"Malformed execution audit: {error}",
                    "parse_valid": False,
                }
            )
            return RouterVerdict(
                False,
                "both",
                f"Malformed execution-boundary audit: {error}",
            )


def _blocksworld_shadow_digest(
    actions: Tuple[BlocksworldPrimitiveAction, ...], facts: Tuple[str, ...]
) -> str:
    payload = {
        "actions": [action.pddl for action in actions],
        "facts": list(facts),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


class ExecutionAuditLLMOnlyBlocksworldAdapter(
    VerifiedRepairBlocksworldNLevelAdapter
):
    """Blocksworld port of the composed-plus-expanded LLM execution audit.

    The online state is a non-rejecting reducer over the public Blocksworld
    effects.  It deliberately contains no compiled-PDDL monitor state and
    never checks applicability, checkpoints, goals, or temporal constraints.
    The released verifier is called exactly once by :meth:`final_score`.
    """

    verifier_mode = "llm-only-execution-audit-online; official-pddl-final-only"
    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = (
        EXECUTION_AUDIT_IMPLEMENTATION_REVISION
    )
    llm_only_online = True
    online_verification_authoritative = False
    transactional_candidate_execution = True

    def __init__(self) -> None:
        self.official_final_evaluator_call_count = 0
        self.execution_audit_records: List[Dict[str, object]] = []

    def initial_state(
        self, task: LexiconBlocksworldTask
    ) -> blocksworld.LexiconExecutionState:
        facts = tuple(sorted(task.initial_facts))
        actions: Tuple[BlocksworldPrimitiveAction, ...] = ()
        return blocksworld.LexiconExecutionState(
            actions,
            facts,
            (),
            _blocksworld_shadow_digest(actions, facts),
        )

    def copy_state(
        self,
        task: LexiconBlocksworldTask,
        state: blocksworld.LexiconExecutionState,
    ) -> blocksworld.LexiconExecutionState:
        del task
        return replace(state)

    def goal_reached(
        self,
        task: LexiconBlocksworldTask,
        state: blocksworld.LexiconExecutionState,
    ) -> bool:
        del task, state
        return False

    is_goal = goal_reached

    def apply_action(
        self,
        task: LexiconBlocksworldTask,
        state: blocksworld.LexiconExecutionState,
        action: object,
        action_index: int,
    ) -> TransitionResult:
        del task, action_index
        primitive = (
            action
            if isinstance(action, BlocksworldPrimitiveAction)
            else BlocksworldPrimitiveAction(
                str(getattr(action, "name")),
                tuple(str(value) for value in getattr(action, "args")),
            )
        )
        facts = set(state.public_facts)
        args = primitive.args
        # Apply only the explicit public effects.  Missing preconditions,
        # types, monitor state, checkpoints, and goals are intentionally not
        # consulted and can never reject an action in this ablation.
        if primitive.name == "pickup" and len(args) == 1:
            (upper,) = args
            facts.discard(f"(ontable {upper})")
            facts.discard(f"(clear {upper})")
            facts.discard("(handempty)")
            facts.add(f"(holding {upper})")
        elif primitive.name == "putdown" and len(args) == 1:
            (upper,) = args
            facts.discard(f"(holding {upper})")
            facts.add(f"(ontable {upper})")
            facts.add(f"(clear {upper})")
            facts.add("(handempty)")
        elif primitive.name == "stack" and len(args) == 2:
            upper, lower = args
            facts.discard(f"(holding {upper})")
            facts.discard(f"(clear {lower})")
            facts.add(f"(on {upper} {lower})")
            facts.add(f"(clear {upper})")
            facts.add("(handempty)")
        elif primitive.name == "unstack" and len(args) == 2:
            upper, lower = args
            facts.discard(f"(on {upper} {lower})")
            facts.discard(f"(clear {upper})")
            facts.discard("(handempty)")
            facts.add(f"(holding {upper})")
            facts.add(f"(clear {lower})")
        actions = (*state.executed_actions, primitive)
        ordered_facts = tuple(sorted(facts))
        next_state = blocksworld.LexiconExecutionState(
            actions,
            ordered_facts,
            (),
            _blocksworld_shadow_digest(actions, ordered_facts),
        )
        return TransitionResult(
            True,
            next_state,
            "semantic verification withheld",
            {
                "semantic_verification": "WITHHELD",
                "state_kind": "non-rejecting-public-effect-shadow",
            },
        )

    def validate_projected_subtask(
        self,
        task: object,
        decision: object,
        subtask: object,
        projected_state: object,
        is_last: bool,
    ) -> ArtifactCheck:
        del task, decision, subtask, projected_state, is_last
        return ArtifactCheck.accepted(
            None,
            metadata={
                "semantic_verification": "WITHHELD",
                "checkpoint_checked": False,
                "goal_checked": False,
            },
        )

    def router_request(
        self,
        task: LexiconBlocksworldTask,
        state: object,
        scene: object,
        state_output: str,
        decision_output: str,
        hierarchy_output: str,
        projection: object,
        execution_feedback: Optional[str] = None,
    ) -> StageRequest:
        del state, scene
        boundary = _execution_boundary_payload(self, projection)
        return StageRequest(
            stage="innerbot_router",
            system=SYSTEM_EXECUTION_AUDIT_ROUTER,
            prompt=execution_audit_router_prompt(
                problem_text=blocksworld._model_task_text(task),
                descriptor_output=state_output,
                decision_output=decision_output,
                hierarchy_output=hierarchy_output,
                execution_boundary_actions=boundary,
                feedback=execution_feedback,
            ),
            response_schema=EXECUTION_AUDIT_SCHEMA,
            schema_name="n_hierarchy_execution_boundary_audit_v1",
        )

    def parse_router(self, output: str) -> RouterVerdict:
        return ExecutionAuditLLMOnlyLexiconAdapter.parse_router(self, output)

    def outer_request(
        self,
        task: LexiconBlocksworldTask,
        decision: object,
        hierarchy: object,
        subtask: object,
        previous_state: blocksworld.LexiconExecutionState,
        current_state: blocksworld.LexiconExecutionState,
        is_last: bool,
    ) -> StageRequest:
        del hierarchy
        plan = getattr(subtask, "plan", subtask)
        if not isinstance(plan, PlannedSubtask):
            raise TypeError("OuterBot received an invalid projected subtask")
        decision_subtask = (
            decision.by_index().get(plan.index)
            if isinstance(decision, blocksworld.LexiconDecisionPlan)
            else None
        )
        checkpoint = (
            decision_subtask.checkpoint
            if decision_subtask is not None
            else blocksworld.LexiconCheckpoint((), (), ())
        )
        before_count = len(previous_state.executed_actions)
        segment = current_state.executed_actions[before_count:]
        evidence = {
            "semantic_verification": "WITHHELD",
            "shadow_state_is_authoritative": False,
            "checkpoint_checked": False,
            "goal_checked": False,
            "temporal_constraints_checked": False,
            "remaining_subtasks": not is_last,
            "official_evaluator_available_during_planning": False,
        }
        prompt = blocksworld.outerbot_prompt(
            blocksworld._model_task_text(task),
            plan.description,
            checkpoint.to_dict(),
            blocksworld._public_state_payload(previous_state),
            blocksworld._public_state_payload(current_state),
            [self.format_action(item) for item in segment],
            evidence,
        )
        prompt = prompt.replace(
            "The PDDL simulator's facts are authoritative.  Explain and classify the\n"
            "transition, but never override applicability, checkpoint, goal, or temporal\n"
            "constraint results.",
            "No deterministic applicability, checkpoint, goal, or temporal-constraint\n"
            "result is available. The displayed state is an unchecked public-effect shadow.\n"
            "You are the sole online semantic judge for this ablation.",
        ).replace(
            "DETERMINISTIC COMPILED-PDDL EVIDENCE",
            "WITHHELD SEMANTIC-VERIFICATION RECORD",
        ).replace(
            "- TASK SUCCESS: only when deterministic final verification is valid.",
            "- TASK SUCCESS: only when your own task-level review finds the full plan complete.",
        ).replace(
            "- SUBTASK SUCCESS: the transition and checkpoint hold, but the full task is not\n"
            "  yet certified.",
            "- SUBTASK SUCCESS: your own review finds the subtask and checkpoint satisfied,\n"
            "  but the full task is not yet complete.",
        )
        return StageRequest(
            stage="outerbot",
            system=SYSTEM_EXECUTION_AUDIT_OUTER_BLOCKSWORLD,
            prompt=prompt,
        )

    def final_score(self, context: object) -> BlocksworldPlanVerification:
        self.official_final_evaluator_call_count += 1
        if self.official_final_evaluator_call_count != 1:
            raise RuntimeError(
                "execution-audit ablation attempted to call the official "
                "Blocksworld evaluator more than once"
            )
        return verify_blocksworld_plan(
            getattr(context, "task"),
            tuple(getattr(context, "executed_actions")),
        )


__all__ = [
    "EXECUTION_AUDIT_SCHEMA",
    "EXECUTION_AUDIT_IMPLEMENTATION_REVISION",
    "PIPELINE_VERSION",
    "SYSTEM_EXECUTION_AUDIT_OUTER_BLOCKSWORLD",
    "SYSTEM_EXECUTION_AUDIT_ROUTER",
    "ExecutionAuditLLMOnlyBlocksworldAdapter",
    "ExecutionAuditLLMOnlyLexiconAdapter",
    "execution_audit_router_prompt",
]
