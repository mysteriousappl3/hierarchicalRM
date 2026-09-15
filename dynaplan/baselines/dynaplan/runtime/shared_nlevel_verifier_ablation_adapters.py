"""LexiCon adapters for the v5.5 and v5-LLM-only verifier ablations.

Neither adapter invokes the released compiled-PDDL simulator during planning.
``PromptInducedRulesLexiconAdapter`` delegates online semantics to the generic
JSON interpreter in :mod:`n_hirearchy_v5_5.rules`.  ``LLMOnlyLexiconAdapter``
uses a non-rejecting public-effect shadow state solely to give the unchanged
planning stages a current-state view; InnerBot and OuterBot remain the only
online judges.  Both call the official verifier only from ``final_score``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


WORKSPACE_DIR = Path(__file__).resolve().parents[2]
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from n_hirearchy_v5_5.rules import (  # noqa: E402
    Fact,
    PromptRuleInterpreter,
    RuleProgram,
    RuleState,
    RuleValidationError,
    load_rules_schema,
    parse_fact,
    parse_rule_program,
)

import shared_nlevel_lexicon as lexicon  # noqa: E402
from lexicon_logistics_task import (  # noqa: E402
    LexiconLogisticsTask,
    PlanVerification,
    PrimitiveAction,
    verify_plan,
)
from shared_nlevel_pipeline import (  # noqa: E402
    ArtifactCheck,
    PlannedSubtask,
    StageRequest,
    TransitionResult,
)
from shared_nlevel_verified_repair_adapters import (  # noqa: E402
    VerifiedRepairLexiconNLevelAdapter,
)


RULE_INDUCED_PIPELINE_VERSION = "shared_nlevel_v5_5_prompt_induced_rules"
LLM_ONLY_PIPELINE_VERSION = "shared_nlevel_v5_llm_only"
SYSTEM_RULESBOT = (
    "RulesBot: translate only the supplied public task rules into the strict "
    "domain-neutral JSON transition language."
)
SYSTEM_RULE_REPAIR = (
    "HierarchyPlanner verified-prefix repair from prompt-induced JSON-rule "
    "evidence (InnerBot localized controller)."
)
SYSTEM_RULE_INDUCED_OUTER = lexicon.SYSTEM_OUTERBOT.replace(
    "deterministically simulated", "JSON-rule-interpreted"
)
SYSTEM_LLM_ONLY_ROUTER = (
    "InnerBot router for the v5 LLM-only ablation: judge the DecisionBot and "
    "HierarchyPlanner artifacts without deterministic semantic evidence."
)
SYSTEM_LLM_ONLY_OUTER = (
    "OuterBot for the v5 LLM-only ablation: judge a subtask from the public "
    "task, checkpoint, action list, and unchecked shadow states."
)


def rulesbot_request(task: LexiconLogisticsTask, feedback: str = "") -> StageRequest:
    """Build an oracle-free structured request from the selected public prompt."""

    empty_condition = '{"all_of": [], "any_of": [], "none_of": []}'
    prompt = f"""Convert the public task below into one executable JSON rule artifact.

Use only information stated in the task. Do not solve the task and do not emit
a plan. Preserve every action name, argument order, object, initial fact, goal,
and temporal constraint. Infer only the minimum type hierarchy required by the
stated signatures (for example, a declared airport may be a location subtype).

JSON LANGUAGE:
- A root type uses an empty string as `parent`.
- Fact strings are flat atoms such as `(at_ ?package ?location)` or
  `(at_ p1 l1_1)`; nested expressions are not allowed inside a fact string.
- A condition is `all_of AND (one any_of item if nonempty) AND none_of absent`.
  Encode a single atom in `all_of`; encode a source `(or A B)` by putting A and
  B in `any_of`.
- Action parameters omit the `?`; references to them in facts include `?`.
- `mutable=false` means no action may add/delete that predicate.
- Temporal rules must stay in source order and use IDs `constraint_1`,
  `constraint_2`, and so on.
- For `sometime`, `always`, and `at-most-once`, put the condition in `first`
  and use {empty_condition} for `second`.
- For `sometime-before FIRST SECOND`, put FIRST in `first` and the condition
  that must have occurred strictly earlier in `second`.
- For `sometime-after FIRST SECOND`, put FIRST in `first` and the condition
  that must hold at that state or later in `second`.
- Copy the exact source temporal-constraint strings, in order, into
  `source_constraints` so omissions are auditable.

PUBLIC TASK (the only semantic source):
{task.prompt_text()}

SCHEMA-LOCAL VALIDATION FEEDBACK:
{feedback or 'N/A'}

Return only the JSON object selected by the response schema.
"""
    return StageRequest(
        stage="rulesbot",
        system=SYSTEM_RULESBOT,
        prompt=prompt,
        response_schema=load_rules_schema(),
        schema_name="n_hierarchy_prompt_induced_rules_v1",
    )


def _state_digest(actions: Sequence[object], facts: Sequence[Fact]) -> str:
    rendered_actions = []
    for action in actions:
        rendered_actions.append(
            [
                str(getattr(action, "name", action)),
                *[str(value) for value in getattr(action, "args", ())],
            ]
        )
    payload = {
        "actions": rendered_actions,
        "facts": sorted(fact.pddl for fact in facts),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _coerce_primitive(action: object) -> PrimitiveAction:
    if isinstance(action, PrimitiveAction):
        return action
    return PrimitiveAction(
        str(getattr(action, "name")),
        tuple(str(value) for value in getattr(action, "args")),
    )


class _OfficialFinalScoreMixin:
    official_final_evaluator_call_count: int

    def _init_final_counter(self) -> None:
        self.official_final_evaluator_call_count = 0

    def final_score(self, context: object) -> PlanVerification:
        self.official_final_evaluator_call_count += 1
        if self.official_final_evaluator_call_count != 1:
            raise RuntimeError(
                "verifier ablation attempted to call the official evaluator more than once"
            )
        return verify_plan(
            getattr(context, "task"),
            tuple(getattr(context, "executed_actions")),
        )


class PromptInducedRulesLexiconAdapter(
    _OfficialFinalScoreMixin, VerifiedRepairLexiconNLevelAdapter
):
    """V5 controller whose online authority is an LLM-induced rule program."""

    verifier_mode = "prompt-induced-json-rules; official-pddl-final-only"
    architecture_mode = RULE_INDUCED_PIPELINE_VERSION
    online_verification_authoritative = True

    def __init__(self) -> None:
        self.program: Optional[RuleProgram] = None
        self.interpreter: Optional[PromptRuleInterpreter] = None
        self.rules_output: Optional[str] = None
        self.rules_sha256: Optional[str] = None
        self._init_final_counter()

    def install_rules(
        self, task: LexiconLogisticsTask, output: str
    ) -> ArtifactCheck:
        try:
            program = parse_rule_program(output)
        except RuleValidationError as error:
            return ArtifactCheck.rejected(str(error))
        expected_sources = tuple(task.constraints)
        if program.source_constraints != expected_sources:
            return ArtifactCheck.rejected(
                "source_constraints must copy every public constraint exactly and in order"
            )
        if len(program.temporal_constraints) != len(expected_sources):
            return ArtifactCheck.rejected(
                "temporal_constraints count differs from copied public constraints"
            )
        expected_ids = tuple(
            f"constraint_{index}" for index in range(1, len(expected_sources) + 1)
        )
        observed_ids = tuple(rule.identifier for rule in program.temporal_constraints)
        if observed_ids != expected_ids:
            return ArtifactCheck.rejected(
                f"temporal rule IDs must be {list(expected_ids)}; got {list(observed_ids)}"
            )
        self.program = program
        self.interpreter = PromptRuleInterpreter(program)
        self.rules_output = output
        self.rules_sha256 = hashlib.sha256(output.encode("utf-8")).hexdigest()
        return ArtifactCheck.accepted(
            program,
            metadata={
                "rules_sha256": self.rules_sha256,
                "action_count": len(program.actions),
                "constraint_count": len(program.temporal_constraints),
            },
        )

    def _interpreter(self) -> PromptRuleInterpreter:
        if self.interpreter is None:
            raise RuntimeError("RulesBot artifact must be installed before planning")
        return self.interpreter

    def initial_state(self, task: LexiconLogisticsTask) -> RuleState:
        del task
        return self._interpreter().initial_state()

    def copy_state(self, task: LexiconLogisticsTask, state: RuleState) -> RuleState:
        del task
        return self._interpreter().copy_state(state)

    def goal_reached(self, task: LexiconLogisticsTask, state: RuleState) -> bool:
        del task
        return self._interpreter().complete(state)

    is_goal = goal_reached

    def apply_action(
        self,
        task: LexiconLogisticsTask,
        state: RuleState,
        action: object,
        action_index: int,
    ) -> TransitionResult:
        del task
        transition = self._interpreter().apply(state, action, action_index)
        return TransitionResult(
            transition.ok,
            transition.state,
            transition.reason,
            dict(transition.metadata),
        )

    def validate_projected_subtask(
        self,
        task: LexiconLogisticsTask,
        decision: object,
        subtask: object,
        projected_state: RuleState,
        is_last: bool,
    ) -> ArtifactCheck:
        del task
        if not isinstance(decision, lexicon.LexiconDecisionPlan):
            return ArtifactCheck.rejected("Invalid Decision artifact")
        decision_subtask = decision.by_index().get(int(getattr(subtask, "index", -1)))
        if decision_subtask is None:
            return ArtifactCheck.rejected(
                f"No Decision checkpoint for subtask {getattr(subtask, 'index', '?')}"
            )
        checkpoint_ok, evidence = lexicon._checkpoint_result(
            projected_state, decision_subtask.checkpoint
        )
        constraint_report = self._interpreter().constraint_report(projected_state)
        addressed_failures: List[str] = []
        if self.program is None:
            raise RuntimeError("missing installed rule program")
        for constraint_index in decision_subtask.checkpoint.constraints_addressed:
            if 1 <= constraint_index <= len(self.program.temporal_constraints):
                identifier = self.program.temporal_constraints[constraint_index - 1].identifier
                item = constraint_report.get(identifier, {})
                if not isinstance(item, Mapping) or item.get("satisfied") is not True:
                    addressed_failures.append(identifier)
        errors: List[str] = []
        if not checkpoint_ok:
            errors.append(
                f"Subtask {getattr(subtask, 'index', '?')} does not satisfy its Decision checkpoint"
            )
        if addressed_failures:
            errors.append(
                "Checkpoint claims unsatisfied induced temporal constraints: "
                + ", ".join(addressed_failures)
            )
        completion = self._interpreter().completion_report(projected_state)
        if is_last and completion.get("valid") is not True:
            errors.append(
                "Final projected prefix does not satisfy the prompt-induced JSON rules"
            )
        evidence.update(
            {
                "induced_constraint_status": constraint_report,
                "induced_final_verification": completion if is_last else None,
                "rule_source": "prompt-induced-json",
            }
        )
        return ArtifactCheck(
            valid=not errors,
            value=projected_state if not errors else None,
            errors=tuple(errors),
            metadata=evidence,
        )

    def router_request(self, *args: object, **kwargs: object) -> StageRequest:
        request = super().router_request(*args, **kwargs)
        prompt = request.prompt.replace(
            "DETERMINISTIC COMPILED-PDDL EVIDENCE",
            "DETERMINISTIC PROMPT-INDUCED JSON-RULE EVIDENCE",
        ).replace(
            "compiled-PDDL", "prompt-induced JSON-rule"
        ).replace(
            "PDDL", "JSON-rule"
        )
        return replace(request, prompt=prompt)

    def outer_request(
        self,
        task: LexiconLogisticsTask,
        decision: object,
        hierarchy: object,
        subtask: object,
        previous_state: RuleState,
        current_state: RuleState,
        is_last: bool,
    ) -> StageRequest:
        del hierarchy
        plan = getattr(subtask, "plan", subtask)
        if not isinstance(plan, PlannedSubtask):
            raise TypeError("OuterBot received an invalid projected subtask")
        decision_subtask = (
            decision.by_index().get(plan.index)
            if isinstance(decision, lexicon.LexiconDecisionPlan)
            else None
        )
        checkpoint = (
            decision_subtask.checkpoint
            if decision_subtask is not None
            else lexicon.LexiconCheckpoint((), (), ())
        )
        checkpoint_ok, checkpoint_evidence = lexicon._checkpoint_result(
            current_state, checkpoint
        )
        deterministic: Dict[str, object] = {
            "transition_applicable": True,
            "checkpoint_satisfied": checkpoint_ok,
            **checkpoint_evidence,
            "remaining_subtasks": not is_last,
            "authority": "prompt-induced-json-rule-interpreter",
        }
        if is_last:
            deterministic["final_verification"] = (
                self._interpreter().completion_report(current_state)
            )
        before_count = len(previous_state.executed_actions)
        segment = current_state.executed_actions[before_count:]
        prompt = lexicon.outerbot_prompt(
            lexicon._model_task_text(task),
            plan.description,
            checkpoint.to_dict(),
            lexicon._public_state_payload(previous_state),
            lexicon._public_state_payload(current_state),
            [self.format_action(action) for action in segment],
            deterministic,
        )
        prompt = prompt.replace(
            "PDDL simulator's facts",
            "prompt-induced JSON-rule interpreter's facts",
        ).replace(
            "DETERMINISTIC COMPILED-PDDL EVIDENCE",
            "DETERMINISTIC PROMPT-INDUCED JSON-RULE EVIDENCE",
        ).replace(
            "deterministic final verification",
            "prompt-induced JSON-rule final verification",
        )
        return StageRequest(
            stage="outerbot",
            system=SYSTEM_RULE_INDUCED_OUTER,
            prompt=prompt,
        )

    def hierarchy_repair_request(self, *args: object, **kwargs: object) -> StageRequest:
        request = super().hierarchy_repair_request(*args, **kwargs)
        return replace(
            request,
            system=SYSTEM_RULE_REPAIR,
            prompt=request.prompt.replace(
                "PUBLIC DETERMINISTIC FAILURE CERTIFICATE",
                "PROMPT-INDUCED JSON-RULE FAILURE CERTIFICATE",
            ).replace("compiled PDDL", "prompt-induced JSON rules"),
        )

    def augment_decision_repair_request(
        self, *args: object, **kwargs: object
    ) -> StageRequest:
        request = super().augment_decision_repair_request(*args, **kwargs)
        return replace(
            request,
            prompt=request.prompt.replace(
                "PUBLIC DETERMINISTIC CHECKPOINT FAILURE CERTIFICATE",
                "PROMPT-INDUCED JSON-RULE CHECKPOINT FAILURE CERTIFICATE",
            ),
        )


class LLMOnlyLexiconAdapter(_OfficialFinalScoreMixin, VerifiedRepairLexiconNLevelAdapter):
    """V5 ablation with no online semantic rejection or goal authority."""

    verifier_mode = "llm-only-online; official-pddl-final-only"
    architecture_mode = LLM_ONLY_PIPELINE_VERSION
    llm_only_online = True
    online_verification_authoritative = False

    def __init__(self) -> None:
        self._init_final_counter()

    def initial_state(self, task: LexiconLogisticsTask) -> RuleState:
        facts = tuple(
            parse_fact(value, f"public initial fact {index}")
            for index, value in enumerate(task.initial_facts)
        )
        frozen = frozenset(facts)
        return RuleState((), frozen, (frozen,), (), _state_digest((), facts))

    def copy_state(self, task: LexiconLogisticsTask, state: RuleState) -> RuleState:
        del task
        return RuleState(
            tuple(state.executed_actions),
            frozenset(state.facts),
            tuple(frozenset(snapshot) for snapshot in state.trace),
            (),
            state.digest,
        )

    def goal_reached(self, task: LexiconLogisticsTask, state: RuleState) -> bool:
        del task, state
        # Completion is deliberately unavailable online.  The controller's
        # LLM-only authority hook lets an OuterBot TASK SUCCESS end planning.
        return False

    is_goal = goal_reached

    def apply_action(
        self,
        task: LexiconLogisticsTask,
        state: RuleState,
        action: object,
        action_index: int,
    ) -> TransitionResult:
        del task, action_index
        primitive = _coerce_primitive(action)
        facts = set(state.facts)
        args = primitive.args
        # This shadow reducer applies only the public effects stated in the
        # prompt.  It never checks preconditions, types, temporal constraints,
        # checkpoints, or goals and can never reject an action.
        if primitive.name in {"loadtruck", "loadairplane"} and len(args) == 3:
            package, vehicle, location = args
            facts.discard(Fact("at_", (package, location)))
            facts.add(Fact("in", (package, vehicle)))
        elif primitive.name in {"unloadtruck", "unloadairplane"} and len(args) == 3:
            package, vehicle, location = args
            facts.discard(Fact("in", (package, vehicle)))
            facts.add(Fact("at_", (package, location)))
        elif primitive.name == "drivetruck" and len(args) == 4:
            truck, source, target, _city = args
            facts.discard(Fact("at_", (truck, source)))
            facts.add(Fact("at_", (truck, target)))
        elif primitive.name == "flyairplane" and len(args) == 3:
            airplane, source, target = args
            facts.discard(Fact("at_", (airplane, source)))
            facts.add(Fact("at_", (airplane, target)))
        actions = (*state.executed_actions, primitive)
        frozen = frozenset(facts)
        next_state = RuleState(
            actions,
            frozen,
            (*state.trace, frozen),
            (),
            _state_digest(actions, tuple(frozen)),
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
        task: LexiconLogisticsTask,
        state: RuleState,
        scene: object,
        state_output: str,
        decision_output: str,
        hierarchy_output: str,
        projection: object,
        execution_feedback: Optional[str] = None,
    ) -> StageRequest:
        del state, scene
        hierarchy = getattr(projection, "subtasks", ())
        evidence = {
            "semantic_verification": "WITHHELD",
            "structural_compilation_succeeded": bool(getattr(projection, "valid", False)),
            "compiled_subtask_count": len(hierarchy),
            "candidate_h0_action_count": sum(
                len(getattr(getattr(item, "plan", item), "actions", ()))
                for item in hierarchy
            ),
            "official_evaluator_available_during_planning": False,
        }
        prompt = lexicon.router_prompt(
            lexicon._model_task_text(task),
            state_output,
            decision_output,
            hierarchy_output,
            evidence,
            execution_feedback,
        )
        prompt = prompt.replace(
            "DETERMINISTIC COMPILED-PDDL EVIDENCE",
            "WITHHELD SEMANTIC-VERIFICATION RECORD",
        ).replace(
            "Treat successful parsing, call-graph inference, binding checks, and simulator\n"
            "facts in the deterministic evidence as authoritative. Judge semantic\n"
            "ownership:",
            "No semantic verifier result is available. Independently judge semantic\n"
            "correctness and ownership from the public task and artifacts:",
        )
        return StageRequest(
            stage="innerbot_router",
            system=SYSTEM_LLM_ONLY_ROUTER,
            prompt=prompt,
        )

    def outer_request(
        self,
        task: LexiconLogisticsTask,
        decision: object,
        hierarchy: object,
        subtask: object,
        previous_state: RuleState,
        current_state: RuleState,
        is_last: bool,
    ) -> StageRequest:
        del hierarchy
        plan = getattr(subtask, "plan", subtask)
        if not isinstance(plan, PlannedSubtask):
            raise TypeError("OuterBot received an invalid projected subtask")
        decision_subtask = (
            decision.by_index().get(plan.index)
            if isinstance(decision, lexicon.LexiconDecisionPlan)
            else None
        )
        checkpoint = (
            decision_subtask.checkpoint
            if decision_subtask is not None
            else lexicon.LexiconCheckpoint((), (), ())
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
        prompt = lexicon.outerbot_prompt(
            lexicon._model_task_text(task),
            plan.description,
            checkpoint.to_dict(),
            lexicon._public_state_payload(previous_state),
            lexicon._public_state_payload(current_state),
            [self.format_action(action) for action in segment],
            evidence,
        )
        prompt = prompt.replace(
            "The PDDL simulator's facts are authoritative.  You may explain and classify\n"
            "the transition, but may not override its applicability, checkpoint, goal, or\n"
            "temporal-constraint result.",
            "No deterministic applicability, checkpoint, goal, or temporal-constraint\n"
            "result is available. The displayed state is an unchecked public-effect shadow.\n"
            "You are the sole online semantic judge for this ablation.",
        ).replace(
            "DETERMINISTIC COMPILED-PDDL EVIDENCE",
            "WITHHELD SEMANTIC-VERIFICATION RECORD",
        ).replace(
            "TASK SUCCESS: permitted only when deterministic final verification is valid.",
            "TASK SUCCESS: choose only when your own task-level review finds the full plan complete.",
        ).replace(
            "SUBTASK SUCCESS: transition was applicable and its checkpoint is satisfied,",
            "SUBTASK SUCCESS: your own review finds the subtask and checkpoint satisfied,",
        )
        return StageRequest(
            stage="outerbot",
            system=SYSTEM_LLM_ONLY_OUTER,
            prompt=prompt,
        )


__all__ = [
    "LLM_ONLY_PIPELINE_VERSION",
    "RULE_INDUCED_PIPELINE_VERSION",
    "LLMOnlyLexiconAdapter",
    "PromptInducedRulesLexiconAdapter",
    "SYSTEM_LLM_ONLY_OUTER",
    "SYSTEM_LLM_ONLY_ROUTER",
    "SYSTEM_RULE_INDUCED_OUTER",
    "SYSTEM_RULESBOT",
    "rulesbot_request",
]
