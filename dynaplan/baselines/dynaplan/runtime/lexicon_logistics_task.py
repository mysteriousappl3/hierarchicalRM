"""Strict, provenance-preserving adapter for the LexiCon Logistics tasks.

This module deliberately does not import the upstream ``lexicon.py`` harness.  It
loads the released PDDL artifacts directly, records their hashes, and evaluates
plans with the same compiled-problem simulation rule used by the release.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import threading
import types
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

from unified_planning.io import PDDLReader
from unified_planning.plans import ActionInstance
from unified_planning.shortcuts import SequentialSimulator


PAPER_CONSTRAINT_LEVELS: Tuple[int, ...] = (1, 3, 5, 7, 10)
PAPER_SEEDS: Tuple[int, ...] = tuple(range(1, 31))
# The pinned repository also ships three level-4 artifacts, but level 4 is not
# one of the five Logistics strata reported by the paper.  Keep the exact
# coordinate pairs explicit so a nearby directory (for example 4/52) can never
# become an evaluation task merely by appearing in the checkout.
DEVELOPMENT_TASK_IDS: Tuple[Tuple[int, int], ...] = (
    (4, 51),
    (4, 53),
    (4, 54),
)
EVALUATION_CONSTRAINT_LEVELS: Tuple[int, ...] = (1, 3, 4, 5, 7, 10)
EVALUATION_PACKED_INSTANCE_IDS: Tuple[int, ...] = (
    *PAPER_SEEDS,
    51,
    53,
    54,
)
PAPER_DATASET_SPLIT = "paper"
DEVELOPMENT_DATASET_SPLIT = "development-non-paper"
PINNED_OFFICIAL_COMMIT = "8dfb02ef0188e0c7fea55ca38d702c21d75f9691"
OFFICIAL_REPOSITORY = "https://github.com/Periklismant/lexicon_neurips"

# These are the six action names and arities presented by the Logistics domain.
PRIMITIVE_ARITIES: Dict[str, int] = {
    "loadtruck": 3,
    "loadairplane": 3,
    "unloadtruck": 3,
    "unloadairplane": 3,
    "drivetruck": 4,
    "flyairplane": 3,
}

# Expected argument types follow the domain's intended public action interface.
# In the released PDDL, the first argument of the two unload actions is typed as
# the broader ``obj``; the benchmark description and every shipped oracle use a
# package, so the adapter intentionally enforces the documented package type.
PRIMITIVE_SIGNATURES: Dict[str, Tuple[str, ...]] = {
    "loadtruck": ("package", "truck", "location"),
    "loadairplane": ("package", "airplane", "location"),
    "unloadtruck": ("package", "truck", "location"),
    "unloadairplane": ("package", "airplane", "location"),
    "drivetruck": ("truck", "location", "location", "city"),
    "flyairplane": ("airplane", "airport", "airport"),
}

_SOURCE_FILENAMES: Tuple[str, ...] = (
    "nl",
    "domain.pddl",
    "problem.pddl",
    "unconstrained_problem.pddl",
    "compiled_domain.pddl",
    "compiled_problem.pddl",
    "constrained_plan",
    "unconstrained_plan",
)
_TOKEN = r"[a-z][a-z0-9_]*"
_ACTION_LINE_RE = re.compile(
    rf"^(?:\((?P<paren>{_TOKEN}(?:\s+{_TOKEN})*)\)|(?P<bare>{_TOKEN}(?:\s+{_TOKEN})*))$"
)
_FENCE_RE = re.compile(
    r"\A\s*```(?:[A-Za-z][A-Za-z0-9_-]*)?[ \t]*\r?\n(?P<body>.*?)\r?\n```\s*\Z",
    re.DOTALL,
)
_GROUND_ATOM_RE = re.compile(
    rf"^\((?P<name>at_|in|incity)(?P<args>(?:\s+{_TOKEN})+)\)$"
)
_NEGATED_GROUND_ATOM_RE = re.compile(r"^\(not (?P<atom>\(.+\))\)$")
_UPSTREAM_IMPORT_LOCK = threading.Lock()


class LexiconTaskError(RuntimeError):
    """Raised when the pinned release is absent, changed, or malformed."""


class PlanParseError(ValueError):
    """Raised when model text is not exactly a supported plan representation."""


@dataclass(frozen=True)
class PrimitiveAction:
    """A normalized call to one of the six Logistics primitives."""

    name: str
    args: Tuple[str, ...]

    @property
    def pddl(self) -> str:
        return f"({self.name}{' ' if self.args else ''}{' '.join(self.args)})"

    @property
    def bare(self) -> str:
        return " ".join((self.name, *self.args))

    def to_dict(self) -> Dict[str, object]:
        return {"name": self.name, "arguments": list(self.args)}

    def __str__(self) -> str:
        return self.pddl


@dataclass(frozen=True)
class PlanVerification:
    """Detailed counterpart of the release's INVALID/SUBOPTIMAL/OPTIMAL metric."""

    status: str
    valid: bool
    optimal: bool
    submitted_length: int
    optimal_length: Optional[int]
    goal_failure: bool = False
    constraint_failure: bool = False
    failure_kind: Optional[str] = None
    failure_message: Optional[str] = None
    first_failed_action_index: Optional[int] = None
    first_failed_action: Optional[PrimitiveAction] = None
    unsatisfied_preconditions: Tuple[str, ...] = ()
    unsatisfied_goals: Tuple[str, ...] = ()
    unsatisfied_task_goals: Tuple[str, ...] = ()
    unsatisfied_constraint_goals: Tuple[str, ...] = ()

    @property
    def validity(self) -> str:
        return "VALID" if self.valid else "INVALID"

    @property
    def optimality(self) -> Optional[str]:
        if not self.valid or self.optimal_length is None:
            return None
        return "OPTIMAL" if self.optimal else "SUBOPTIMAL"

    @property
    def cost_delta(self) -> Optional[int]:
        if not self.valid or self.optimal_length is None:
            return None
        return self.submitted_length - self.optimal_length

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "valid": self.valid,
            "validity": self.validity,
            "optimal": self.optimal,
            "optimality": self.optimality,
            "submitted_length": self.submitted_length,
            "optimal_length": self.optimal_length,
            "cost_delta": self.cost_delta,
            "goal_failure": self.goal_failure,
            "constraint_failure": self.constraint_failure,
            "failure_kind": self.failure_kind,
            "failure_message": self.failure_message,
            "first_failed_action_index": self.first_failed_action_index,
            "first_failed_action": (
                self.first_failed_action.to_dict() if self.first_failed_action else None
            ),
            "unsatisfied_preconditions": list(self.unsatisfied_preconditions),
            "unsatisfied_goals": list(self.unsatisfied_goals),
            "unsatisfied_task_goals": list(self.unsatisfied_task_goals),
            "unsatisfied_constraint_goals": list(
                self.unsatisfied_constraint_goals
            ),
        }


@dataclass(frozen=True)
class LexiconLogisticsTask:
    """One released Logistics instance plus exact semantic/provenance fields."""

    constraint_count: int
    seed: int
    id: str
    dataset_split: str
    prompt_source: str
    official_nl: str
    official_mapper_nl: str
    canonical_nl: str
    objects_by_type: Dict[str, Tuple[str, ...]]
    initial_facts: Tuple[str, ...]
    goals: Tuple[str, ...]
    constraints: Tuple[str, ...]
    optimal_length: int
    oracle_actions: Tuple[PrimitiveAction, ...]
    source_hashes: Dict[str, str]
    source_commit: str
    source_commit_timestamp: str
    source_remote: str
    source_checkout_dirty: bool
    task_dir: Path
    source_files: Dict[str, Path]

    @property
    def task_id(self) -> str:
        return self.id

    @property
    def actual_constraint_count(self) -> int:
        """Number of top-level constraints (can exceed the release folder label)."""

        return len(self.constraints)

    @property
    def is_paper_task(self) -> bool:
        """Whether this coordinate belongs to the paper's 150-task matrix."""

        return self.dataset_split == PAPER_DATASET_SPLIT

    @property
    def selected_prompt(self) -> str:
        return self.prompt_text()

    def prompt_text(self, prompt_source: Optional[str] = None) -> str:
        source = self.prompt_source if prompt_source is None else prompt_source
        if source == "official-nl":
            return self.official_nl
        if source in {"official-mapper", "official-live"}:
            return self.official_mapper_nl
        if source in {"canonical-pddl-nl", "canonical-pddl", "canonical"}:
            return self.canonical_nl
        raise ValueError(
            "prompt_source must be 'official-nl', 'official-mapper', or "
            "'canonical-pddl-nl'"
        )

    def descriptor_payload(self) -> Dict[str, object]:
        """Return the exact JSON-serializable payload expected from StateDescriptor."""

        return {
            "task_id": self.id,
            "objects_by_type": {
                type_name: list(names)
                for type_name, names in self.objects_by_type.items()
            },
            "initial_facts": list(self.initial_facts),
            "goals": list(self.goals),
            "constraints": list(self.constraints),
        }

    def source_metadata(self) -> Dict[str, object]:
        return {
            "dataset_split": self.dataset_split,
            "paper_benchmark_task": self.is_paper_task,
            "repository": self.source_remote,
            "commit": self.source_commit,
            "commit_timestamp": self.source_commit_timestamp,
            "checkout_dirty": self.source_checkout_dirty,
            "sha256": dict(self.source_hashes),
        }


@dataclass(frozen=True, slots=True)
class PublicLexiconLogisticsTask:
    """Strategy-facing Logistics data with evaluator-only fields removed.

    This object deliberately has no oracle actions, optimal length, task
    directory, repository root, or plan-file mapping.  Exact online environment
    replay uses the public compiled PDDL text embedded below; final scoring is
    performed separately on the private :class:`LexiconLogisticsTask`.
    """

    constraint_count: int
    seed: int
    id: str
    dataset_split: str
    prompt_source: str
    public_prompt: str
    objects_by_type: Dict[str, Tuple[str, ...]]
    initial_facts: Tuple[str, ...]
    goals: Tuple[str, ...]
    constraints: Tuple[str, ...]
    domain_pddl: str
    problem_pddl: str
    compiled_domain_pddl: str
    compiled_problem_pddl: str
    lifted_tcore_source: str

    @property
    def task_id(self) -> str:
        return self.id

    @property
    def actual_constraint_count(self) -> int:
        return len(self.constraints)

    @property
    def is_paper_task(self) -> bool:
        return self.dataset_split == PAPER_DATASET_SPLIT

    @property
    def selected_prompt(self) -> str:
        return self.public_prompt

    def prompt_text(self, prompt_source: Optional[str] = None) -> str:
        """Return the selected public prompt without exposing source paths.

        A public view contains exactly the prompt selected when the private
        task was loaded.  Silently switching sources here would require
        retaining additional checkout-backed fields, so reject that misuse.
        """

        if prompt_source is not None and prompt_source != self.prompt_source:
            raise ValueError(
                "A public Logistics task view contains only its selected "
                f"{self.prompt_source!r} prompt"
            )
        return self.public_prompt

    def descriptor_payload(self) -> Dict[str, object]:
        return {
            "task_id": self.id,
            "objects_by_type": {
                type_name: list(names)
                for type_name, names in self.objects_by_type.items()
            },
            "initial_facts": list(self.initial_facts),
            "goals": list(self.goals),
            "constraints": list(self.constraints),
        }


def public_task_view(task: LexiconLogisticsTask) -> PublicLexiconLogisticsTask:
    """Copy only public planning information into a slot-only task object."""

    compiler_path = task.task_dir.parents[4] / "compiler" / "lifted_tcore.py"
    if not compiler_path.is_file():
        raise LexiconTaskError(
            f"Pinned LexiCon compiler source is missing: {compiler_path}"
        )
    view = PublicLexiconLogisticsTask(
        constraint_count=task.constraint_count,
        seed=task.seed,
        id=task.id,
        dataset_split=task.dataset_split,
        prompt_source=task.prompt_source,
        public_prompt=task.prompt_text(),
        objects_by_type={
            name: tuple(values) for name, values in task.objects_by_type.items()
        },
        initial_facts=tuple(task.initial_facts),
        goals=tuple(task.goals),
        constraints=tuple(task.constraints),
        domain_pddl=task.source_files["domain.pddl"].read_text(encoding="utf-8"),
        problem_pddl=task.source_files["problem.pddl"].read_text(encoding="utf-8"),
        compiled_domain_pddl=task.source_files["compiled_domain.pddl"].read_text(
            encoding="utf-8"
        ),
        compiled_problem_pddl=task.source_files[
            "compiled_problem.pddl"
        ].read_text(encoding="utf-8"),
        lifted_tcore_source=compiler_path.read_text(encoding="utf-8"),
    )
    forbidden = (
        "optimal_length",
        "oracle_actions",
        "task_dir",
        "source_files",
        "source_metadata",
    )
    if any(hasattr(view, name) for name in forbidden):  # pragma: no cover
        raise AssertionError("Public Logistics task exposes evaluator-only fields")
    return view


def checkout_root() -> Path:
    """Return the required sibling checkout of the official release."""

    return Path(__file__).resolve().parent.parent / "lexicon_neurips"


@lru_cache(maxsize=1)
def _official_logistics_mapper_class(repository: Path) -> Any:
    """Load the mapper from the pinned checkout without modifying that checkout.

    The upstream mapper uses the top-level import ``from base_mapper import
    BaseMapper`` and is not packaged for normal library imports.  Executing the
    two checked-in source files under private module names preserves the exact
    upstream implementation, avoids a permanent ``sys.path`` mutation, and—by
    compiling source bytes directly—cannot create ``__pycache__`` files in the
    provenance checkout.  The temporary compatibility alias is protected
    because ``sys.modules`` is process-global.
    """

    base_path = repository / "base_mapper.py"
    mapper_path = repository / "domains" / "logistics" / "mapper.py"
    if not base_path.is_file() or not mapper_path.is_file():
        raise LexiconTaskError(
            "Pinned LexiCon checkout is missing the Logistics mapper sources"
        )

    with _UPSTREAM_IMPORT_LOCK:
        base_module = types.ModuleType("_lexicon_pinned_base_mapper")
        base_module.__file__ = str(base_path)
        exec(
            compile(base_path.read_bytes(), str(base_path), "exec"),
            base_module.__dict__,
        )

        mapper_module = types.ModuleType("_lexicon_pinned_logistics_mapper")
        mapper_module.__file__ = str(mapper_path)
        missing = object()
        prior_base_mapper = sys.modules.get("base_mapper", missing)
        sys.modules["base_mapper"] = base_module
        try:
            exec(
                compile(mapper_path.read_bytes(), str(mapper_path), "exec"),
                mapper_module.__dict__,
            )
        finally:
            if prior_base_mapper is missing:
                del sys.modules["base_mapper"]
            else:
                sys.modules["base_mapper"] = prior_base_mapper

    mapper_class = getattr(mapper_module, "LogisticsMapper", None)
    if mapper_class is None:  # pragma: no cover - guarded by the pinned commit.
        raise LexiconTaskError("Pinned Logistics mapper has no LogisticsMapper")
    return mapper_class


def _official_mapper_prompt(repository: Path, problem: Any) -> str:
    """Reproduce the user message built by the official live evaluator.

    ``evaluate_llms`` sends the mapper's system component separately and sends
    ``domain_nl + problem_nl`` as the user message.  The local runner already
    owns the system message, so this prompt source is exactly that official
    user-message component reconstructed from ``domain.pddl`` and
    ``problem.pddl`` rather than the stale committed ``nl`` artifact.
    """

    mapper_class = _official_logistics_mapper_class(repository)
    _system_prompt, domain_nl, problem_nl = mapper_class(problem).get_problem_nl()
    if not isinstance(domain_nl, str) or not isinstance(problem_nl, str):
        raise LexiconTaskError("Pinned Logistics mapper returned malformed text")
    return domain_nl + problem_nl


def paper_task_ids() -> Tuple[Tuple[int, int], ...]:
    """The 150 Logistics cells reported at the five paper constraint levels."""

    return tuple(
        (constraint_count, seed)
        for constraint_count in PAPER_CONSTRAINT_LEVELS
        for seed in PAPER_SEEDS
    )


def available_tasks() -> Tuple[Tuple[int, int], ...]:
    """Return paper task ids whose complete released artifact set is present."""

    root = checkout_root() / "domains" / "logistics" / "data"
    available = []
    for constraint_count, seed in paper_task_ids():
        directory = root / f"data_{constraint_count}" / str(seed)
        if all((directory / filename).is_file() for filename in _SOURCE_FILENAMES):
            available.append((constraint_count, seed))
    return tuple(available)


def evaluation_task_ids() -> Tuple[Tuple[int, int], ...]:
    """All explicitly admitted coordinates, including labeled dev artifacts.

    This helper intentionally does not alter :func:`paper_task_ids` or
    :func:`available_tasks`; those remain the exact 150-task paper inventory.
    """

    return tuple(sorted((*paper_task_ids(), *DEVELOPMENT_TASK_IDS)))


def available_evaluation_tasks() -> Tuple[Tuple[int, int], ...]:
    """Return complete paper and explicitly allowlisted development tasks."""

    root = checkout_root() / "domains" / "logistics" / "data"
    return tuple(
        (constraint_count, seed)
        for constraint_count, seed in evaluation_task_ids()
        if all(
            (
                root
                / f"data_{constraint_count}"
                / str(seed)
                / filename
            ).is_file()
            for filename in _SOURCE_FILENAMES
        )
    )


def task_dataset_split(constraint_count: int, seed: int) -> str:
    """Classify an admitted coordinate or reject it fail-closed."""

    if isinstance(constraint_count, bool) or isinstance(seed, bool):
        raise ValueError("constraint_count and seed must be integers, not booleans")
    coordinate = (constraint_count, seed)
    if (
        constraint_count in PAPER_CONSTRAINT_LEVELS
        and seed in PAPER_SEEDS
    ):
        return PAPER_DATASET_SPLIT
    if coordinate in DEVELOPMENT_TASK_IDS:
        return DEVELOPMENT_DATASET_SPLIT
    raise ValueError(
        f"Unsupported LexiCon Logistics coordinate {coordinate!r}; expected a "
        "paper coordinate (levels 1,3,5,7,10 with packed ID 1..30) or one "
        f"of the non-paper development coordinates {DEVELOPMENT_TASK_IDS}"
    )


def load_task(
    constraint_count: int,
    seed: int,
    prompt_source: str = "canonical-pddl-nl",
) -> LexiconLogisticsTask:
    """Load one allowlisted evaluation task from the pinned sibling checkout.

    This admits the five published Logistics levels with packed IDs 1..30 plus
    exactly three separately labeled, non-paper level-4 development artifacts.
    """

    dataset_split = task_dataset_split(constraint_count, seed)
    if prompt_source not in {
        "official-nl",
        "official-mapper",
        "official-live",
        "canonical-pddl-nl",
        "canonical-pddl",
        "canonical",
    }:
        raise ValueError(
            "prompt_source must be 'official-nl', 'official-mapper', or "
            "'canonical-pddl-nl'"
        )
    if prompt_source in {"canonical", "canonical-pddl"}:
        normalized_prompt_source = "canonical-pddl-nl"
    elif prompt_source == "official-live":
        normalized_prompt_source = "official-mapper"
    else:
        normalized_prompt_source = prompt_source

    repository = checkout_root()
    if not repository.is_dir():
        raise LexiconTaskError(
            f"Official LexiCon checkout not found at required sibling path {repository}"
        )
    commit = _git(repository, "rev-parse", "HEAD")
    if commit != PINNED_OFFICIAL_COMMIT:
        raise LexiconTaskError(
            "LexiCon checkout is not at the adapter's pinned commit: "
            f"expected {PINNED_OFFICIAL_COMMIT}, found {commit}"
        )
    dirty_output = _git(
        repository, "status", "--porcelain", "--untracked-files=no"
    )
    meaningful_tracked_changes = []
    for status_line in dirty_output.splitlines():
        path = status_line[3:] if len(status_line) > 3 else status_line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        tracked_generated_bytecode = path.endswith(".pyc") and (
            path.startswith("__pycache__/") or "/__pycache__/" in path
        )
        if not tracked_generated_bytecode:
            meaningful_tracked_changes.append(status_line)
    if meaningful_tracked_changes:
        raise LexiconTaskError(
            "LexiCon checkout has modified tracked source/artifact files; restore "
            "or separately commit them before running the pinned benchmark: "
            + "; ".join(meaningful_tracked_changes)
        )

    task_dir = (
        repository
        / "domains"
        / "logistics"
        / "data"
        / f"data_{constraint_count}"
        / str(seed)
    )
    source_files = {name: task_dir / name for name in _SOURCE_FILENAMES}
    missing = [name for name, path in source_files.items() if not path.is_file()]
    if missing:
        raise LexiconTaskError(
            f"Released task {constraint_count}/{seed} is missing files: {missing}"
        )

    source_hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in source_files.items()
    }
    official_nl = source_files["nl"].read_text(encoding="utf-8")

    reader = PDDLReader()
    try:
        original_problem = reader.parse_problem(
            str(source_files["domain.pddl"]), str(source_files["problem.pddl"])
        )
        compiled_problem = reader.parse_problem(
            str(source_files["compiled_domain.pddl"]),
            str(source_files["compiled_problem.pddl"]),
        )
        oracle_plan = reader.parse_plan(
            compiled_problem, str(source_files["constrained_plan"])
        )
    except Exception as error:  # pragma: no cover - a corrupt release is exceptional.
        raise LexiconTaskError(
            f"Could not parse released task {constraint_count}/{seed}: {error}"
        ) from error

    object_types = {
        obj.name: obj.type.name for obj in original_problem.all_objects
    }
    objects_by_type_mut: Dict[str, list[str]] = {}
    for obj in original_problem.all_objects:
        objects_by_type_mut.setdefault(obj.type.name, []).append(obj.name)
    objects_by_type = {
        type_name: tuple(sorted(names))
        for type_name, names in sorted(objects_by_type_mut.items())
    }

    initial_facts = tuple(
        sorted(
            _expr_to_pddl(fluent)
            for fluent, value in original_problem.initial_values.items()
            if value.is_true() and fluent.is_fluent_exp()
        )
    )
    goal_nodes = []
    for goal in original_problem.goals:
        goal_nodes.extend(_flatten_and(goal))
    goals = tuple(_expr_to_pddl(goal) for goal in goal_nodes)
    constraints = tuple(
        _expr_to_pddl(constraint)
        for constraint in original_problem.trajectory_constraints
    )
    oracle_actions = tuple(
        PrimitiveAction(
            action.action.name,
            tuple(str(argument) for argument in action.actual_parameters),
        )
        for action in oracle_plan.actions
    )
    canonical_nl = _canonical_prompt(
        constraint_count=constraint_count,
        seed=seed,
        dataset_split=dataset_split,
        objects_by_type=objects_by_type,
        initial_nodes=tuple(
            fluent
            for fluent, value in original_problem.initial_values.items()
            if value.is_true() and fluent.is_fluent_exp()
        ),
        goal_nodes=tuple(goal_nodes),
        constraint_nodes=tuple(original_problem.trajectory_constraints),
        object_types=object_types,
    )
    official_mapper_nl = _official_mapper_prompt(repository, original_problem)

    remote = _git(repository, "config", "--get", "remote.origin.url")
    commit_timestamp = _git(repository, "show", "-s", "--format=%cI", "HEAD")
    return LexiconLogisticsTask(
        constraint_count=constraint_count,
        seed=seed,
        id=(
            f"lexicon-logistics-c{constraint_count}-s{seed}"
            if dataset_split == PAPER_DATASET_SPLIT
            else f"lexicon-logistics-dev-c{constraint_count}-s{seed}"
        ),
        dataset_split=dataset_split,
        prompt_source=normalized_prompt_source,
        official_nl=official_nl,
        official_mapper_nl=official_mapper_nl,
        canonical_nl=canonical_nl,
        objects_by_type=objects_by_type,
        initial_facts=initial_facts,
        goals=goals,
        constraints=constraints,
        optimal_length=len(oracle_actions),
        oracle_actions=oracle_actions,
        source_hashes=source_hashes,
        source_commit=commit,
        source_commit_timestamp=commit_timestamp,
        source_remote=remote or OFFICIAL_REPOSITORY,
        source_checkout_dirty=False,
        task_dir=task_dir,
        source_files=source_files,
    )


def parse_direct_plan(text: str) -> Tuple[PrimitiveAction, ...]:
    """Extract a strict plan without fuzzy matching or prose recovery.

    Accepted representations are either one and only one fenced block (with an
    optional safe one-word info tag) or bare action lines.  Each
    line can use released PDDL parentheses or the benchmark's bare format.
    """

    if not isinstance(text, str):
        raise PlanParseError("Plan output must be text")
    if not text.strip():
        raise PlanParseError("Plan output is empty")

    if "```" in text:
        match = _FENCE_RE.fullmatch(text)
        if match is None or match.group("body").count("```"):
            raise PlanParseError(
                "Plan output must contain exactly one fenced block and no prose"
            )
        body = match.group("body")
    else:
        body = text.strip()

    lines = body.splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise PlanParseError("Plan must contain non-empty action lines only")

    actions = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        match = _ACTION_LINE_RE.fullmatch(line)
        if match is None:
            raise PlanParseError(
                f"Line {line_number} is not a clean Logistics action: {raw_line!r}"
            )
        tokens = (match.group("paren") or match.group("bare")).split()
        name, args = tokens[0], tuple(tokens[1:])
        expected_arity = PRIMITIVE_ARITIES.get(name)
        if expected_arity is None:
            raise PlanParseError(
                f"Line {line_number} uses unknown primitive {name!r}"
            )
        if len(args) != expected_arity:
            raise PlanParseError(
                f"Line {line_number} calls {name} with {len(args)} arguments; "
                f"expected {expected_arity}"
            )
        actions.append(PrimitiveAction(name, args))
    return tuple(actions)


def validate_ground_fact(task: LexiconLogisticsTask, fact: str) -> str:
    """Validate and return one canonical, ground, possibly-negated literal."""

    if not isinstance(fact, str) or fact != fact.strip():
        raise ValueError("Fact must be a trimmed string")
    atom = fact
    negative = _NEGATED_GROUND_ATOM_RE.fullmatch(fact)
    if negative is not None:
        atom = negative.group("atom")
    match = _GROUND_ATOM_RE.fullmatch(atom)
    if match is None:
        raise ValueError(
            "Fact must use canonical syntax for at_, in, or incity, e.g. "
            "'(at_ p1 l1_2)'"
        )
    name = match.group("name")
    args = tuple(match.group("args").split())
    signatures = {
        "at_": ("obj", "location"),
        "in": ("obj", "obj"),
        "incity": ("location", "city"),
    }
    expected_types = signatures[name]
    if len(args) != len(expected_types):
        raise ValueError(
            f"{name} has {len(args)} arguments; expected {len(expected_types)}"
        )
    object_types = _object_type_map(task)
    for position, (argument, expected_type) in enumerate(
        zip(args, expected_types), start=1
    ):
        actual_type = object_types.get(argument)
        if actual_type is None:
            raise ValueError(f"Unknown object {argument!r}")
        if not _is_subtype(actual_type, expected_type):
            raise ValueError(
                f"Argument {position} of {name} is {actual_type}; "
                f"expected {expected_type}"
            )
    return fact


def validate_primitive_action(
    task: LexiconLogisticsTask, action: PrimitiveAction
) -> None:
    """Reject unknown objects, wrong arity, and wrong typed dispatch arguments."""

    expected_types = PRIMITIVE_SIGNATURES.get(action.name)
    if expected_types is None:
        raise ValueError(f"Unknown Logistics primitive {action.name!r}")
    if len(action.args) != len(expected_types):
        raise ValueError(
            f"{action.name} has {len(action.args)} arguments; expected {len(expected_types)}"
        )
    object_types = _object_type_map(task)
    for position, (argument, expected_type) in enumerate(
        zip(action.args, expected_types), start=1
    ):
        actual_type = object_types.get(argument)
        if actual_type is None:
            raise ValueError(f"Unknown object {argument!r}")
        if not _is_subtype(actual_type, expected_type):
            raise ValueError(
                f"Argument {position} of {action.name} is {actual_type}; "
                f"expected {expected_type}"
            )


def verify_plan(
    task: Union[LexiconLogisticsTask, PublicLexiconLogisticsTask],
    actions: Union[
        str,
        Sequence[Union[PrimitiveAction, str, Any]],
    ],
) -> PlanVerification:
    """Simulate a submitted plan on the released compiled PDDL problem.

    Status follows the official release exactly: a valid plan longer than the
    shipped optimal plan is SUBOPTIMAL; a valid plan no longer than it is
    OPTIMAL; every parse, binding, applicability, goal, or constraint failure is
    INVALID.
    """

    optimum = getattr(task, "optimal_length", None)
    try:
        normalized = _coerce_actions(actions)
    except (PlanParseError, TypeError, ValueError) as error:
        return PlanVerification(
            status="INVALID",
            valid=False,
            optimal=False,
            submitted_length=0,
            optimal_length=optimum,
            failure_kind="plan_format",
            failure_message=str(error),
        )

    reader = PDDLReader()
    try:
        if isinstance(task, PublicLexiconLogisticsTask):
            problem = reader.parse_problem_string(
                task.compiled_domain_pddl, task.compiled_problem_pddl
            )
        else:
            problem = reader.parse_problem(
                str(task.source_files["compiled_domain.pddl"]),
                str(task.source_files["compiled_problem.pddl"]),
            )
    except Exception as error:  # pragma: no cover - protected by loader/tests.
        raise LexiconTaskError(f"Could not parse compiled task: {error}") from error

    bound_actions = []
    for index, action in enumerate(normalized, start=1):
        try:
            validate_primitive_action(task, action)
            declaration = problem.action(action.name)
            manager = problem.environment.expression_manager
            parameters = tuple(
                manager.ObjectExp(problem.object(argument))
                for argument in action.args
            )
            bound_actions.append(ActionInstance(declaration, parameters))
        except Exception as error:
            return PlanVerification(
                status="INVALID",
                valid=False,
                optimal=False,
                submitted_length=len(normalized),
                optimal_length=optimum,
                failure_kind="action_binding",
                failure_message=str(error),
                first_failed_action_index=index,
                first_failed_action=action,
            )

    with SequentialSimulator(problem) as simulator:
        state = simulator.get_initial_state()
        for index, (action, bound_action) in enumerate(
            zip(normalized, bound_actions), start=1
        ):
            try:
                if not simulator.is_applicable(state, bound_action):
                    conditions, reason = simulator.get_unsatisfied_conditions(
                        state, bound_action
                    )
                    unsatisfied = tuple(
                        _expr_to_pddl(condition) for condition in conditions
                    )
                    constraint_failure = any(
                        _expr_has_constraint_fluent(condition)
                        for condition in conditions
                    )
                    reason_text = str(reason) if reason is not None else None
                    message = f"Action is inapplicable: {action.pddl}"
                    if unsatisfied:
                        message += f"; unsatisfied {list(unsatisfied)}"
                    if reason_text:
                        message += f" ({reason_text})"
                    return PlanVerification(
                        status="INVALID",
                        valid=False,
                        optimal=False,
                        submitted_length=len(normalized),
                        optimal_length=optimum,
                        constraint_failure=constraint_failure,
                        failure_kind=(
                            "constraint" if constraint_failure else "action_precondition"
                        ),
                        failure_message=message,
                        first_failed_action_index=index,
                        first_failed_action=action,
                        unsatisfied_preconditions=unsatisfied,
                    )
                next_state = simulator.apply(state, bound_action)
            except Exception as error:
                return PlanVerification(
                    status="INVALID",
                    valid=False,
                    optimal=False,
                    submitted_length=len(normalized),
                    optimal_length=optimum,
                    failure_kind="simulation",
                    failure_message=str(error),
                    first_failed_action_index=index,
                    first_failed_action=action,
                )
            if next_state is None:
                return PlanVerification(
                    status="INVALID",
                    valid=False,
                    optimal=False,
                    submitted_length=len(normalized),
                    optimal_length=optimum,
                    failure_kind="simulation",
                    failure_message=f"Simulator rejected {action.pddl}",
                    first_failed_action_index=index,
                    first_failed_action=action,
                )
            state = next_state

        unsatisfied_nodes = []
        for goal in simulator.get_unsatisfied_goals(state):
            unsatisfied_nodes.extend(_flatten_and(goal))

    unsatisfied_goals = tuple(_expr_to_pddl(goal) for goal in unsatisfied_nodes)
    constraint_nodes = tuple(
        goal for goal in unsatisfied_nodes if _expr_has_constraint_fluent(goal)
    )
    task_goal_nodes = tuple(
        goal for goal in unsatisfied_nodes if not _expr_has_constraint_fluent(goal)
    )
    unsatisfied_constraint_goals = tuple(
        _expr_to_pddl(goal) for goal in constraint_nodes
    )
    unsatisfied_task_goals = tuple(_expr_to_pddl(goal) for goal in task_goal_nodes)
    if unsatisfied_nodes:
        goal_failure = bool(task_goal_nodes)
        constraint_failure = bool(constraint_nodes)
        if goal_failure and constraint_failure:
            failure_kind = "goal_and_constraint"
        elif constraint_failure:
            failure_kind = "constraint"
        else:
            failure_kind = "goal"
        return PlanVerification(
            status="INVALID",
            valid=False,
            optimal=False,
            submitted_length=len(normalized),
            optimal_length=optimum,
            goal_failure=goal_failure,
            constraint_failure=constraint_failure,
            failure_kind=failure_kind,
            failure_message=(
                "Final state does not satisfy the compiled problem goals"
            ),
            unsatisfied_goals=unsatisfied_goals,
            unsatisfied_task_goals=unsatisfied_task_goals,
            unsatisfied_constraint_goals=unsatisfied_constraint_goals,
        )

    optimal = bool(optimum is not None and len(normalized) <= optimum)
    return PlanVerification(
        status=("OPTIMAL" if optimal else "SUBOPTIMAL") if optimum is not None else "VALID",
        valid=True,
        optimal=optimal,
        submitted_length=len(normalized),
        optimal_length=optimum,
    )


def _git(repository: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise LexiconTaskError(
            f"Could not inspect LexiCon checkout metadata: {error}"
        ) from error
    return result.stdout.strip()


def _coerce_actions(
    actions: Union[str, Sequence[Union[PrimitiveAction, str, Any]]]
) -> Tuple[PrimitiveAction, ...]:
    if isinstance(actions, str):
        return parse_direct_plan(actions)
    normalized = []
    for index, action in enumerate(actions):
        if isinstance(action, PrimitiveAction):
            normalized.append(action)
            continue
        if isinstance(action, str):
            parsed = parse_direct_plan(action)
            if len(parsed) != 1:
                raise ValueError(f"Action {index} must contain exactly one call")
            normalized.append(parsed[0])
            continue
        name = getattr(action, "name", None)
        args = getattr(action, "args", None)
        if isinstance(name, str) and isinstance(args, (tuple, list)) and all(
            isinstance(argument, str) for argument in args
        ):
            normalized.append(PrimitiveAction(name, tuple(args)))
            continue
        raise TypeError(f"Unsupported action at index {index}: {action!r}")
    return tuple(normalized)


def _object_type_map(task: LexiconLogisticsTask) -> Dict[str, str]:
    return {
        object_name: type_name
        for type_name, object_names in task.objects_by_type.items()
        for object_name in object_names
    }


def _is_subtype(actual_type: str, expected_type: str) -> bool:
    if actual_type == expected_type:
        return True
    parents = {
        "airport": "location",
        "location": "object",
        "city": "object",
        "package": "obj",
        "truck": "obj",
        "airplane": "obj",
        "obj": "object",
    }
    current = actual_type
    while current in parents:
        current = parents[current]
        if current == expected_type:
            return True
    return False


def _flatten_and(expression: Any) -> Tuple[Any, ...]:
    if expression.is_and():
        flattened = []
        for argument in expression.args:
            flattened.extend(_flatten_and(argument))
        return tuple(flattened)
    return (expression,)


def _expr_to_pddl(expression: Any) -> str:
    if expression.is_fluent_exp():
        arguments = " ".join(_expr_to_pddl(argument) for argument in expression.args)
        return f"({expression.fluent().name}{' ' if arguments else ''}{arguments})"
    if expression.is_object_exp():
        return expression.object().name
    if expression.is_parameter_exp():
        return f"?{expression.parameter().name}"
    if expression.is_variable_exp():
        return f"?{expression.variable().name}"
    if expression.is_bool_constant():
        return "true" if expression.bool_constant_value() else "false"
    if expression.is_not():
        return f"(not {_expr_to_pddl(expression.arg(0))})"
    operator = None
    if expression.is_and():
        operator = "and"
    elif expression.is_or():
        operator = "or"
    elif expression.is_always():
        operator = "always"
    elif expression.is_sometime():
        operator = "sometime"
    elif expression.is_at_most_once():
        operator = "at-most-once"
    elif expression.is_sometime_before():
        operator = "sometime-before"
    elif expression.is_sometime_after():
        operator = "sometime-after"
    elif expression.is_equals():
        operator = "="
    if operator is not None:
        arguments = " ".join(_expr_to_pddl(argument) for argument in expression.args)
        return f"({operator}{' ' if arguments else ''}{arguments})"
    if expression.is_exists() or expression.is_forall():
        operator = "exists" if expression.is_exists() else "forall"
        variables = " ".join(
            f"?{variable.name} - {variable.type.name}"
            for variable in expression.variables()
        )
        return f"({operator} ({variables}) {_expr_to_pddl(expression.arg(0))})"
    return str(expression)


def _expr_has_constraint_fluent(expression: Any) -> bool:
    if expression.is_fluent_exp():
        name = expression.fluent().name
        return name.startswith("hold_") or name.startswith("seen_")
    return any(_expr_has_constraint_fluent(argument) for argument in expression.args)


def _expr_to_nl(expression: Any, object_types: Mapping[str, str]) -> str:
    if expression.is_fluent_exp():
        name = expression.fluent().name
        arguments = [
            argument.object().name if argument.is_object_exp() else str(argument)
            for argument in expression.args
        ]
        if name == "at_":
            subject, location = arguments
            label = object_types.get(subject, "object").capitalize()
            return f"{label} {subject} is at location {location}"
        if name == "in":
            subject, vehicle = arguments
            subject_label = object_types.get(subject, "object").capitalize()
            vehicle_label = object_types.get(vehicle, "vehicle").capitalize()
            return f"{subject_label} {subject} is inside {vehicle_label} {vehicle}"
        if name == "incity":
            return f"Location {arguments[0]} is in city {arguments[1]}"
        return _expr_to_pddl(expression)
    if expression.is_not():
        return f"it is not the case that {_expr_to_nl(expression.arg(0), object_types)}"
    if expression.is_and():
        return "all of: " + "; ".join(
            _expr_to_nl(argument, object_types) for argument in expression.args
        )
    if expression.is_or():
        return "at least one of: " + "; ".join(
            _expr_to_nl(argument, object_types) for argument in expression.args
        )
    if expression.is_always():
        return (
            "At every state, "
            + _expr_to_nl(expression.arg(0), object_types)
            + "."
        )
    if expression.is_sometime():
        return (
            "At some state, "
            + _expr_to_nl(expression.arg(0), object_types)
            + "."
        )
    if expression.is_at_most_once():
        return (
            "The following may hold during at most one continuous interval: "
            + _expr_to_nl(expression.arg(0), object_types)
            + "."
        )
    if expression.is_sometime_before():
        return (
            "Whenever the first expression occurs, the second must have occurred "
            "strictly earlier. First: "
            + _expr_to_nl(expression.arg(0), object_types)
            + ". Second: "
            + _expr_to_nl(expression.arg(1), object_types)
            + "."
        )
    if expression.is_sometime_after():
        return (
            "Whenever the first expression occurs, the second must hold then or "
            "later. First: "
            + _expr_to_nl(expression.arg(0), object_types)
            + ". Second: "
            + _expr_to_nl(expression.arg(1), object_types)
            + "."
        )
    return _expr_to_pddl(expression)


def _canonical_prompt(
    *,
    constraint_count: int,
    seed: int,
    dataset_split: str,
    objects_by_type: Mapping[str, Tuple[str, ...]],
    initial_nodes: Iterable[Any],
    goal_nodes: Iterable[Any],
    constraint_nodes: Iterable[Any],
    object_types: Mapping[str, str],
) -> str:
    action_lines = (
        "- `loadtruck package truck location`: load the package into the truck; "
        "both must be at the location.",
        "- `loadairplane package airplane location`: load the package into the "
        "airplane; both must be at the location.",
        "- `unloadtruck package truck location`: unload a package carried by the "
        "truck; the truck must be at the location.",
        "- `unloadairplane package airplane location`: unload a package carried by "
        "the airplane; the airplane must be at the location.",
        "- `drivetruck truck from_location to_location city`: move a truck between "
        "two locations in the same city.",
        "- `flyairplane airplane from_airport to_airport`: move an airplane "
        "between airports.",
    )
    lines = [
        "CANONICAL PDDL-DERIVED LOGISTICS TASK (CORRECTED)",
        (
            f"Released paper instance: constraint-folder {constraint_count}, "
            f"packed instance {seed}."
            if dataset_split == PAPER_DATASET_SPLIT
            else "NON-PAPER DEVELOPMENT INSTANCE: "
            f"constraint-folder {constraint_count}, packed instance {seed}."
        ),
        "",
        "This prompt is generated from domain.pddl and problem.pddl. It is not the "
        "verbatim `nl` artifact. It deliberately restores every conjunct of the "
        "PDDL goal and corrects the released prose's duplicate loadairplane label, "
        "airplane-load precondition typo, and vehicle-as-Package labels.",
        "",
        "Objective: produce a minimum-length valid plan that reaches every goal "
        "and obeys every temporal constraint. Use exactly one action per line.",
        "",
        "Available actions:",
        *action_lines,
        "",
        "Action effects:",
        "- Loading removes `(at_ package location)` and adds `(in package vehicle)`.",
        "- Unloading removes `(in package vehicle)` and adds `(at_ package location)`.",
        "- Driving or flying replaces the vehicle's current `at_` fact with its "
        "destination `at_` fact.",
        "",
        "Objects by their declared PDDL type:",
    ]
    for type_name, names in objects_by_type.items():
        lines.append(f"- {type_name}: {', '.join(names)}")

    lines.extend(("", "Initial state (exact PDDL fact followed by its meaning):"))
    for node in sorted(initial_nodes, key=_expr_to_pddl):
        lines.append(
            f"- `{_expr_to_pddl(node)}` — {_expr_to_nl(node, object_types)}."
        )

    lines.extend(("", "Goals (ALL listed facts are required):"))
    for node in goal_nodes:
        lines.append(
            f"- `{_expr_to_pddl(node)}` — {_expr_to_nl(node, object_types)}."
        )

    lines.extend(("", "Temporal constraints (all are required):"))
    for index, node in enumerate(constraint_nodes, start=1):
        lines.append(
            f"{index}. `{_expr_to_pddl(node)}` — {_expr_to_nl(node, object_types)}"
        )

    lines.extend(
        (
            "",
            "Output only the plan: either clean action lines or exactly one fenced "
            "block containing clean action lines. Do not include analysis or prose.",
        )
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "DEVELOPMENT_DATASET_SPLIT",
    "DEVELOPMENT_TASK_IDS",
    "EVALUATION_CONSTRAINT_LEVELS",
    "EVALUATION_PACKED_INSTANCE_IDS",
    "LexiconLogisticsTask",
    "PublicLexiconLogisticsTask",
    "LexiconTaskError",
    "OFFICIAL_REPOSITORY",
    "PAPER_CONSTRAINT_LEVELS",
    "PAPER_DATASET_SPLIT",
    "PAPER_SEEDS",
    "PINNED_OFFICIAL_COMMIT",
    "PRIMITIVE_ARITIES",
    "PRIMITIVE_SIGNATURES",
    "PlanParseError",
    "PlanVerification",
    "PrimitiveAction",
    "available_tasks",
    "available_evaluation_tasks",
    "checkout_root",
    "load_task",
    "evaluation_task_ids",
    "paper_task_ids",
    "parse_direct_plan",
    "public_task_view",
    "task_dataset_split",
    "validate_ground_fact",
    "validate_primitive_action",
    "verify_plan",
]
