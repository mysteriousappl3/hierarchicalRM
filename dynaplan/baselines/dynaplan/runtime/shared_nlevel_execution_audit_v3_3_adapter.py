"""Success-first v3.1 successor; public rules, not online semantic execution.

The four changes are checkpoint review, precise final/temporal review, retry
after clean rollback, and compact structured InnerBot requirement evidence.
No extra critic, oracle, action simulator, or online evaluator is introduced.
"""

from dataclasses import replace

from comparison_protocol import (
    COMMON_BLOCKSWORLD_SEMANTICS,
    COMMON_FLAT_HANOI_SEMANTICS,
    COMMON_LOGISTICS_SEMANTICS,
    COMMON_TEMPORAL_SEMANTICS,
    with_comparison_contract,
)

from shared_nlevel_execution_audit_v3_1_adapter import (
    SingleInnerBotDualPassOuterTraceBlocksworldAdapter,
    SingleInnerBotDualPassOuterTraceFlatHanoiAdapter,
    SingleInnerBotDualPassOuterTraceLexiconAdapter,
)
from shared_nlevel_execution_audit_v3_2_adapter import (
    _FrozenCandidateStartContextMixin,
)
from shared_nlevel_execution_audit_v3_3_evidence import (
    StructuredRequirementEvidenceMixin,
)


PIPELINE_VERSION = "shared_nlevel_v5_llm_only_execution_audit_v3_3_success_first"
SINGLE_INNERBOT_AUDIT_IMPLEMENTATION_REVISION = PIPELINE_VERSION

CHECKPOINT_REVIEW = """SUCCESS-FIRST CHECKPOINT REVIEW (inside this DecisionBot call)
Before returning the existing checkpoint format, review your decomposition:
1. Separate final-state goals, historical witnesses, and continuing or triggered
   obligations. Include EVERY stated goal and temporal constraint; never relax
   a requirement for convenience, shorter output, or fewer actions.
2. Require a fact at a boundary only when the task or a necessary dependency
   requires it there. A past witness need not remain true at later checkpoints.
   Do not accidentally require a historical witness and a later goal to hold
   simultaneously. Persistent triggers can, however, create new obligations.
3. Check that each checkpoint is internally consistent and reachable from the
   preceding checkpoint under the public action rules. Do not invent terminal
   object positions, empty-hand conditions, restoration, or unrelated stacking.
   Where the output contract requires complete state snapshots, provide them
   exactly; this review does NOT permit dropping required state fields.
4. First choose a plausible legal sequence that satisfies the task. Among such
   sequences, compare necessary milestone orders by estimated EXPANDED primitive
   actions, including temporary moves and restoration, not hierarchy call count.
   Prefer fewer unnecessary moves only when correctness is preserved. Do not
   spend the response budget proving optimality or claim an oracle lower bound.
5. Recheck that the final checkpoint is compatible with ALL final goals and
   outstanding temporal obligations. If repair feedback identifies an impossible
   or unnecessarily restrictive checkpoint, revise the checkpoint itself.
Return only the existing DecisionBot output contract, not this review.
"""

TEMPORAL_REVIEW = COMMON_TEMPORAL_SEMANTICS

BLOCKSWORLD_RULES = COMMON_BLOCKSWORLD_SEMANTICS
LOGISTICS_RULES = COMMON_LOGISTICS_SEMANTICS
HANOI_RULES = COMMON_FLAT_HANOI_SEMANTICS

HANOI_INTERNAL_H0_RULES = """DYNAPLAN INTERNAL H0 COMPILER SEMANTICS
DynaPlan expands each public MoveHoop into MoveArm, Grab, MoveArm, and Drop.
Moving the arm alone does not transfer a ring. Grab removes and holds the
actual top ring of the source peg. Drop appends that same held ring to the
target only when the target is empty or its top ring is larger. Track arm
position and the held ring across every expanded H0 call. These internal calls
are DynaPlan's method representation, not additional benchmark actions."""


class _SuccessFirstPromptMixin:
    architecture_mode = PIPELINE_VERSION
    execution_audit_implementation_revision = PIPELINE_VERSION
    continue_after_rollback = True
    public_action_rules = ""
    comparison_domain = ""
    internal_action_rules = ""

    def _with_internal_rules(self, prompt):
        if not self.internal_action_rules or self.internal_action_rules in prompt:
            return prompt
        return prompt + "\n\n" + self.internal_action_rules

    def _with_public_rules(self, request):
        return replace(
            request,
            prompt=self._with_internal_rules(
                with_comparison_contract(request.prompt, self.comparison_domain)
            ),
        )

    def _problem_text(self, task):
        text = super()._problem_text(task).replace(
            "Every expanded H0 primitive must nevertheless receive its\n"
            "  own proof record.",
            "Check every expanded H0 primitive in the forward pass; return\n"
            "  only compact requirement evidence, not a separate proof per action.",
        )
        return self._with_internal_rules(
            with_comparison_contract(text, self.comparison_domain)
        )

    def decision_request(self, *args, **kwargs):
        request = self._with_public_rules(super().decision_request(*args, **kwargs))
        return replace(request, prompt=request.prompt + "\n\n" + CHECKPOINT_REVIEW)

    def hierarchy_request(self, *args, **kwargs):
        return self._with_public_rules(super().hierarchy_request(*args, **kwargs))

    def h1_source(self, *args, **kwargs):
        return self._with_public_rules(super().h1_source(*args, **kwargs))

    def router_request(self, *args, **kwargs):
        return self._with_public_rules(super().router_request(*args, **kwargs))

    def outer_request(self, *args, **kwargs):
        request = self._with_public_rules(super().outer_request(*args, **kwargs))
        return replace(request, prompt=request.prompt
                       + "\nIndependently check these requirements; the InnerBot's"
                       " verdict and certificate are deliberately not provided.")


class V33SuccessFirstLexiconAdapter(
    _SuccessFirstPromptMixin,
    _FrozenCandidateStartContextMixin,
    StructuredRequirementEvidenceMixin,
    SingleInnerBotDualPassOuterTraceLexiconAdapter,
):
    public_action_rules = LOGISTICS_RULES
    comparison_domain = "logistics"


class V33SuccessFirstBlocksworldAdapter(
    _SuccessFirstPromptMixin,
    _FrozenCandidateStartContextMixin,
    StructuredRequirementEvidenceMixin,
    SingleInnerBotDualPassOuterTraceBlocksworldAdapter,
):
    public_action_rules = BLOCKSWORLD_RULES
    comparison_domain = "blocksworld"


class V33SuccessFirstFlatHanoiAdapter(
    _SuccessFirstPromptMixin,
    _FrozenCandidateStartContextMixin,
    StructuredRequirementEvidenceMixin,
    SingleInnerBotDualPassOuterTraceFlatHanoiAdapter,
):
    public_action_rules = HANOI_RULES
    comparison_domain = "flat-hanoi"
    internal_action_rules = HANOI_INTERNAL_H0_RULES
