"""Strict adapter for the released LexiCon Blocksworld benchmark.

The adapter reads the official, pre-generated artifacts without importing the
upstream benchmark harness or regenerating any problem.  Model plans are scored
against the released compiled PDDL with the same sequential-simulation and
oracle-length rule used by LexiCon's metrics code.  In particular, malformed
actions are never repaired with edit distance.
"""

from __future__ import annotations

import hashlib
import pickletools
import re
import subprocess
import sys
import threading
import types
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

from unified_planning.io import PDDLReader
from unified_planning.plans import ActionInstance
from unified_planning.shortcuts import SequentialSimulator


PAPER_CONSTRAINT_LEVELS: Tuple[int, ...] = (1, 3, 5, 7, 10)
PAPER_PACKED_INSTANCE_IDS: Tuple[int, ...] = tuple(range(1, 31))
PAPER_DATASET_SPLIT = "paper"
PINNED_OFFICIAL_COMMIT = "8dfb02ef0188e0c7fea55ca38d702c21d75f9691"
OFFICIAL_REPOSITORY = "https://github.com/Periklismant/lexicon_neurips"

# The three smallest released generation seeds shared by c=1,3,5,7.  The
# directory number is a packed release ID, not the embedded generation seed.
CONTROLLED_CAMPAIGN_PACKED_IDS: Dict[int, Dict[int, int]] = {
    2002: {1: 14, 3: 4, 5: 12, 7: 2},
    2005: {1: 17, 3: 6, 5: 14, 7: 3},
    2006: {1: 18, 3: 7, 5: 15, 7: 4},
}

PRIMITIVE_SIGNATURES: Dict[str, Tuple[str, ...]] = {
    "pickup": ("block",),
    "putdown": ("block",),
    "stack": ("block", "block"),
    "unstack": ("block", "block"),
}
PRIMITIVE_ARITIES: Dict[str, int] = {
    name: len(signature) for name, signature in PRIMITIVE_SIGNATURES.items()
}

_FACT_SIGNATURES: Dict[str, Tuple[str, ...]] = {
    "clear": ("block",),
    "ontable": ("block",),
    "handempty": (),
    "holding": ("block",),
    "on": ("block", "block"),
}
_SOURCE_FILENAMES: Tuple[str, ...] = (
    "data",
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
    rf"^(?:\((?P<paren>{_TOKEN}(?:\s+{_TOKEN})*)\)|"
    rf"(?P<bare>{_TOKEN}(?:\s+{_TOKEN})*))$"
)
_FENCE_RE = re.compile(
    r"\A\s*```(?:[A-Za-z][A-Za-z0-9_-]*)?[ \t]*\r?\n"
    r"(?P<body>.*?)\r?\n```\s*\Z",
    re.DOTALL,
)
_GROUND_ATOM_RE = re.compile(
    rf"^\((?P<name>clear|ontable|handempty|holding|on)"
    rf"(?P<args>(?:\s+{_TOKEN})*)\)$"
)
_NEGATED_GROUND_ATOM_RE = re.compile(r"^\(not (?P<atom>\(.+\))\)$")
_UPSTREAM_IMPORT_LOCK = threading.Lock()


class LexiconTaskError(RuntimeError):
    """The pinned official checkout or one of its artifacts is invalid."""


class PlanParseError(ValueError):
    """A candidate plan is not an exact sequence of known primitives."""


@dataclass(frozen=True)
class PrimitiveAction:
    """One normalized Blocksworld primitive call."""

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
    """Detailed form of LexiCon's INVALID/SUBOPTIMAL/OPTIMAL outcome."""

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
                self.first_failed_action.to_dict()
                if self.first_failed_action is not None
                else None
            ),
            "unsatisfied_preconditions": list(self.unsatisfied_preconditions),
            "unsatisfied_goals": list(self.unsatisfied_goals),
            "unsatisfied_task_goals": list(self.unsatisfied_task_goals),
            "unsatisfied_constraint_goals": list(
                self.unsatisfied_constraint_goals
            ),
        }


@dataclass(frozen=True)
class LexiconBlocksworldTask:
    """One official Blocksworld cell with prompt, semantics, and provenance."""

    constraint_count: int
    packed_id: int
    generation_seed: int
    id: str
    dataset_split: str
    prompt_source: str
    official_system_prompt: str
    official_user_prompt: str
    official_nl: str
    objects_by_type: Dict[str, Tuple[str, ...]]
    initial_facts: Tuple[str, ...]
    goals: Tuple[str, ...]
    constraints: Tuple[str, ...]
    optimal_length: int
    unconstrained_optimal_length: int
    oracle_actions: Tuple[PrimitiveAction, ...]
    unconstrained_oracle_actions: Tuple[PrimitiveAction, ...]
    unconstrained_problem_sha256: str
    source_hashes: Dict[str, str]
    source_repository_root: Path
    source_commit: str
    source_commit_timestamp: str
    source_remote: str
    source_checkout_dirty: bool
    source_tracked_checkout_dirty: bool
    source_checkout_has_untracked: bool
    task_dir: Path
    source_files: Dict[str, Path]

    @property
    def task_id(self) -> str:
        return self.id

    @property
    def seed(self) -> int:
        """Compatibility alias: this is the packed ID, not generation seed."""

        return self.packed_id

    @property
    def nominal_constraint_count(self) -> int:
        return self.constraint_count

    @property
    def actual_constraint_count(self) -> int:
        return len(self.constraints)

    @property
    def raw_constraint_count(self) -> int:
        return self.actual_constraint_count

    @property
    def oracle_length(self) -> int:
        return self.optimal_length

    @property
    def problem_hash(self) -> str:
        """Hash identifying the common unconstrained problem across strata."""

        return self.unconstrained_problem_sha256

    @property
    def is_paper_task(self) -> bool:
        return self.dataset_split == PAPER_DATASET_SPLIT

    @property
    def official_mapper_nl(self) -> str:
        """Compatibility alias for the exact live-evaluator user message."""

        return self.official_user_prompt

    @property
    def canonical_nl(self) -> str:
        """Compatibility alias; no corrected or synthetic prompt is introduced."""

        return self.official_user_prompt

    @property
    def selected_prompt(self) -> str:
        return self.prompt_text()

    @property
    def complete_official_prompt(self) -> str:
        """Both exact messages concatenated; use ``prompt_messages`` for roles."""

        return self.official_system_prompt + self.official_user_prompt

    def prompt_text(self, prompt_source: Optional[str] = None) -> str:
        """Return the exact user message for the requested official source."""

        source = self.prompt_source if prompt_source is None else prompt_source
        if source in {"official-mapper", "official-live"}:
            return self.official_user_prompt
        if source == "official-nl":
            return self.official_nl
        raise ValueError(
            "prompt_source must be 'official-mapper', 'official-live', or "
            "'official-nl'"
        )

    def prompt_messages(
        self, prompt_source: Optional[str] = None
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Return the official two-role request without an oracle or examples."""

        return (
            {"role": "system", "content": self.official_system_prompt},
            {"role": "user", "content": self.prompt_text(prompt_source)},
        )

    def descriptor_payload(self) -> Dict[str, object]:
        return {
            "task_id": self.id,
            "nominal_constraint_count": self.constraint_count,
            "raw_constraint_count": self.raw_constraint_count,
            "packed_id": self.packed_id,
            "generation_seed": self.generation_seed,
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
            "nominal_constraint_count": self.constraint_count,
            "raw_constraint_count": self.raw_constraint_count,
            "packed_id": self.packed_id,
            "generation_seed": self.generation_seed,
            "oracle_length": self.optimal_length,
            "unconstrained_oracle_length": self.unconstrained_optimal_length,
            "unconstrained_problem_sha256": self.unconstrained_problem_sha256,
            "repository_root": str(self.source_repository_root),
            "repository": self.source_remote,
            "commit": self.source_commit,
            "commit_timestamp": self.source_commit_timestamp,
            "checkout_dirty": self.source_checkout_dirty,
            "tracked_checkout_dirty": self.source_tracked_checkout_dirty,
            "checkout_has_untracked": self.source_checkout_has_untracked,
            "sha256": dict(self.source_hashes),
        }


@dataclass(frozen=True, slots=True)
class PublicLexiconBlocksworldTask:
    """Strategy-facing Blocksworld task without oracle or optimum fields."""

    constraint_count: int
    packed_id: int
    generation_seed: int
    id: str
    dataset_split: str
    prompt_source: str
    public_prompt: str
    official_system_prompt: str
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
    def seed(self) -> int:
        return self.packed_id

    @property
    def nominal_constraint_count(self) -> int:
        return self.constraint_count

    @property
    def actual_constraint_count(self) -> int:
        return len(self.constraints)

    @property
    def raw_constraint_count(self) -> int:
        return self.actual_constraint_count

    @property
    def is_paper_task(self) -> bool:
        return self.dataset_split == PAPER_DATASET_SPLIT

    @property
    def selected_prompt(self) -> str:
        return self.public_prompt

    def prompt_text(self, prompt_source: Optional[str] = None) -> str:
        """Return the one selected public prompt carried by this view."""

        if prompt_source is not None and prompt_source != self.prompt_source:
            raise ValueError(
                "A public Blocksworld task view contains only its selected "
                f"{self.prompt_source!r} prompt"
            )
        return self.public_prompt

    def descriptor_payload(self) -> Dict[str, object]:
        return {
            "task_id": self.id,
            "nominal_constraint_count": self.constraint_count,
            "raw_constraint_count": self.raw_constraint_count,
            "packed_id": self.packed_id,
            "generation_seed": self.generation_seed,
            "objects_by_type": {
                type_name: list(names)
                for type_name, names in self.objects_by_type.items()
            },
            "initial_facts": list(self.initial_facts),
            "goals": list(self.goals),
            "constraints": list(self.constraints),
        }


def public_task_view(task: LexiconBlocksworldTask) -> PublicLexiconBlocksworldTask:
    """Copy public task semantics into an oracle-free slot-only object."""

    compiler_path = task.source_repository_root / "compiler" / "lifted_tcore.py"
    if not compiler_path.is_file():
        raise LexiconTaskError(
            f"Pinned LexiCon compiler source is missing: {compiler_path}"
        )
    view = PublicLexiconBlocksworldTask(
        constraint_count=task.constraint_count,
        packed_id=task.packed_id,
        generation_seed=task.generation_seed,
        id=task.id,
        dataset_split=task.dataset_split,
        prompt_source=task.prompt_source,
        public_prompt=task.prompt_text(),
        official_system_prompt=task.official_system_prompt,
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
        "oracle_length",
        "oracle_actions",
        "unconstrained_optimal_length",
        "unconstrained_oracle_actions",
        "task_dir",
        "source_files",
        "source_metadata",
    )
    if any(hasattr(view, name) for name in forbidden):  # pragma: no cover
        raise AssertionError("Public Blocksworld task exposes evaluator-only fields")
    return view


def checkout_root(explicit: Optional[Union[str, Path]] = None) -> Path:
    """Resolve an explicit checkout or either supported sibling directory."""

    if explicit is not None:
        return Path(explicit).expanduser().resolve()

    project = Path(__file__).resolve().parent.parent
    candidates = (
        # Fresh clone requested alongside ``simmer-style-libero``.
        project.parent / "lexicon",
        # Historical checkout kept inside ``simmer-style-libero``.
        project / "lexicon_neurips",
    )
    present = [
        candidate
        for candidate in candidates
        if (candidate / "domains" / "blocksworld" / "data").is_dir()
    ]
    for candidate in present:
        try:
            if _git(candidate, "rev-parse", "HEAD") == PINNED_OFFICIAL_COMMIT:
                return candidate.resolve()
        except LexiconTaskError:
            continue
    if present:
        return present[0].resolve()
    expected = " or ".join(str(candidate) for candidate in candidates)
    raise LexiconTaskError(f"Official LexiCon checkout not found at {expected}")


def paper_task_ids() -> Tuple[Tuple[int, int], ...]:
    """All 150 official Blocksworld evaluation coordinates."""

    return tuple(
        (constraint_count, packed_id)
        for constraint_count in PAPER_CONSTRAINT_LEVELS
        for packed_id in PAPER_PACKED_INSTANCE_IDS
    )


def available_tasks(
    checkout: Optional[Union[str, Path]] = None,
) -> Tuple[Tuple[int, int], ...]:
    """Return official coordinates whose complete artifact set is present."""

    repository = checkout_root(checkout)
    data_root = repository / "domains" / "blocksworld" / "data"
    available = []
    for constraint_count, packed_id in paper_task_ids():
        directory = data_root / f"data_{constraint_count}" / str(packed_id)
        if all((directory / filename).is_file() for filename in _SOURCE_FILENAMES):
            available.append((constraint_count, packed_id))
    return tuple(available)


def load_task(
    constraint_count: int,
    packed_id: int,
    prompt_source: str = "official-mapper",
    *,
    checkout: Optional[Union[str, Path]] = None,
) -> LexiconBlocksworldTask:
    """Load one allowlisted official cell by nominal c and packed ID."""

    _validate_coordinate(constraint_count, packed_id)
    if prompt_source == "official-live":
        normalized_prompt_source = "official-mapper"
    elif prompt_source in {"official-mapper", "official-nl"}:
        normalized_prompt_source = prompt_source
    else:
        raise ValueError(
            "prompt_source must be 'official-mapper', 'official-live', or "
            "'official-nl'"
        )

    repository = checkout_root(checkout)
    if not repository.is_dir():
        raise LexiconTaskError(f"LexiCon checkout does not exist: {repository}")
    commit = _git(repository, "rev-parse", "HEAD")
    if commit != PINNED_OFFICIAL_COMMIT:
        raise LexiconTaskError(
            "LexiCon checkout is not at the adapter's pinned commit: "
            f"expected {PINNED_OFFICIAL_COMMIT}, found {commit}"
        )

    tracked_status = _git(
        repository, "status", "--porcelain", "--untracked-files=no"
    )
    meaningful_tracked_changes = []
    for status_line in tracked_status.splitlines():
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
            "or commit them before running the benchmark: "
            + "; ".join(meaningful_tracked_changes)
        )
    full_status = _git(repository, "status", "--porcelain")

    task_dir = (
        repository
        / "domains"
        / "blocksworld"
        / "data"
        / f"data_{constraint_count}"
        / str(packed_id)
    )
    source_files = {name: task_dir / name for name in _SOURCE_FILENAMES}
    missing = [name for name, path in source_files.items() if not path.is_file()]
    if missing:
        raise LexiconTaskError(
            f"Released Blocksworld task {constraint_count}/{packed_id} is missing "
            f"files: {missing}"
        )
    source_hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in source_files.items()
    }

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
        unconstrained_problem = reader.parse_problem(
            str(source_files["domain.pddl"]),
            str(source_files["unconstrained_problem.pddl"]),
        )
        unconstrained_plan = reader.parse_plan(
            unconstrained_problem, str(source_files["unconstrained_plan"])
        )
    except Exception as error:
        raise LexiconTaskError(
            f"Could not parse released Blocksworld task "
            f"{constraint_count}/{packed_id}: {error}"
        ) from error

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
    oracle_actions = _plan_actions(oracle_plan)
    unconstrained_oracle_actions = _plan_actions(unconstrained_plan)
    generation_seed = _read_generation_seed(source_files["data"])
    official_system_prompt, official_user_prompt = _official_mapper_messages(
        repository, original_problem
    )

    remote = _git(repository, "config", "--get", "remote.origin.url")
    commit_timestamp = _git(repository, "show", "-s", "--format=%cI", "HEAD")
    return LexiconBlocksworldTask(
        constraint_count=constraint_count,
        packed_id=packed_id,
        generation_seed=generation_seed,
        id=f"lexicon-blocksworld-c{constraint_count}-id{packed_id}",
        dataset_split=PAPER_DATASET_SPLIT,
        prompt_source=normalized_prompt_source,
        official_system_prompt=official_system_prompt,
        official_user_prompt=official_user_prompt,
        official_nl=source_files["nl"].read_text(encoding="utf-8"),
        objects_by_type=objects_by_type,
        initial_facts=initial_facts,
        goals=goals,
        constraints=constraints,
        optimal_length=len(oracle_actions),
        unconstrained_optimal_length=len(unconstrained_oracle_actions),
        oracle_actions=oracle_actions,
        unconstrained_oracle_actions=unconstrained_oracle_actions,
        unconstrained_problem_sha256=source_hashes[
            "unconstrained_problem.pddl"
        ],
        source_hashes=source_hashes,
        source_repository_root=repository,
        source_commit=commit,
        source_commit_timestamp=commit_timestamp,
        source_remote=remote or OFFICIAL_REPOSITORY,
        source_checkout_dirty=bool(
            meaningful_tracked_changes
            or any(line.startswith("??") for line in full_status.splitlines())
        ),
        source_tracked_checkout_dirty=bool(meaningful_tracked_changes),
        source_checkout_has_untracked=any(
            line.startswith("??") for line in full_status.splitlines()
        ),
        task_dir=task_dir,
        source_files=source_files,
    )


def parse_direct_plan(text: str) -> Tuple[PrimitiveAction, ...]:
    """Parse exact action lines; never fuzzy-match, recover prose, or repair."""

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
                f"Line {line_number} is not a clean Blocksworld action: "
                f"{raw_line!r}"
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


def validate_ground_fact(task: LexiconBlocksworldTask, fact: str) -> str:
    """Validate one canonical, ground, optionally negated Blocksworld fact."""

    if not isinstance(fact, str) or fact != fact.strip():
        raise ValueError("Fact must be a trimmed string")
    atom = fact
    negative = _NEGATED_GROUND_ATOM_RE.fullmatch(fact)
    if negative is not None:
        atom = negative.group("atom")
    match = _GROUND_ATOM_RE.fullmatch(atom)
    if match is None:
        raise ValueError(
            "Fact must use canonical clear, ontable, handempty, holding, or on "
            "syntax, e.g. '(on blue_block_1 white_block_1)'"
        )
    name = match.group("name")
    args = tuple(match.group("args").split())
    expected_types = _FACT_SIGNATURES[name]
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
        if actual_type != expected_type:
            raise ValueError(
                f"Argument {position} of {name} is {actual_type}; "
                f"expected {expected_type}"
            )
    return fact


def validate_primitive_action(
    task: LexiconBlocksworldTask, action: PrimitiveAction
) -> None:
    """Reject unknown primitives, wrong arity, objects, or argument types."""

    expected_types = PRIMITIVE_SIGNATURES.get(action.name)
    if expected_types is None:
        raise ValueError(f"Unknown Blocksworld primitive {action.name!r}")
    if len(action.args) != len(expected_types):
        raise ValueError(
            f"{action.name} has {len(action.args)} arguments; "
            f"expected {len(expected_types)}"
        )
    object_types = _object_type_map(task)
    for position, (argument, expected_type) in enumerate(
        zip(action.args, expected_types), start=1
    ):
        actual_type = object_types.get(argument)
        if actual_type is None:
            raise ValueError(f"Unknown object {argument!r}")
        if actual_type != expected_type:
            raise ValueError(
                f"Argument {position} of {action.name} is {actual_type}; "
                f"expected {expected_type}"
            )


def verify_plan(
    task: Union[LexiconBlocksworldTask, PublicLexiconBlocksworldTask],
    actions: Union[str, Sequence[Union[PrimitiveAction, str, Any]]],
) -> PlanVerification:
    """Strictly score a plan on the released compiled problem and oracle."""

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
        if isinstance(task, PublicLexiconBlocksworldTask):
            problem = reader.parse_problem_string(
                task.compiled_domain_pddl, task.compiled_problem_pddl
            )
        else:
            problem = reader.parse_problem(
                str(task.source_files["compiled_domain.pddl"]),
                str(task.source_files["compiled_problem.pddl"]),
            )
    except Exception as error:
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
                    message = f"Action is inapplicable: {action.pddl}"
                    if unsatisfied:
                        message += f"; unsatisfied {list(unsatisfied)}"
                    if reason is not None:
                        message += f" ({reason})"
                    return PlanVerification(
                        status="INVALID",
                        valid=False,
                        optimal=False,
                        submitted_length=len(normalized),
                        optimal_length=optimum,
                        constraint_failure=constraint_failure,
                        failure_kind=(
                            "constraint"
                            if constraint_failure
                            else "action_precondition"
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
    unsatisfied_task_goals = tuple(
        _expr_to_pddl(goal) for goal in task_goal_nodes
    )
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
            failure_message="Final state does not satisfy the compiled problem goals",
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


def _validate_coordinate(constraint_count: int, packed_id: int) -> None:
    if isinstance(constraint_count, bool) or not isinstance(constraint_count, int):
        raise ValueError("constraint_count must be an integer, not a boolean")
    if isinstance(packed_id, bool) or not isinstance(packed_id, int):
        raise ValueError("packed_id must be an integer, not a boolean")
    if constraint_count not in PAPER_CONSTRAINT_LEVELS:
        raise ValueError(
            f"Unsupported nominal constraint level {constraint_count}; expected "
            f"one of {PAPER_CONSTRAINT_LEVELS}"
        )
    if packed_id not in PAPER_PACKED_INSTANCE_IDS:
        raise ValueError("packed_id must be in the official evaluation range 1..30")


def _plan_actions(plan: Any) -> Tuple[PrimitiveAction, ...]:
    return tuple(
        PrimitiveAction(
            action.action.name,
            tuple(str(argument) for argument in action.actual_parameters),
        )
        for action in plan.actions
    )


def _read_generation_seed(data_file: Path) -> int:
    """Read ``Sample.seed`` from the tiny pickle without executing the pickle."""

    waiting_for_value = False
    integer_opcodes = {
        "BININT",
        "BININT1",
        "BININT2",
        "INT",
        "LONG",
        "LONG1",
        "LONG4",
    }
    memo_opcodes = {"MEMOIZE", "BINPUT", "LONG_BINPUT", "PUT"}
    try:
        operations = pickletools.genops(data_file.read_bytes())
        for opcode, argument, _position in operations:
            if (
                opcode.name in {"SHORT_BINUNICODE", "BINUNICODE", "UNICODE"}
                and argument == "seed"
            ):
                waiting_for_value = True
                continue
            if waiting_for_value and opcode.name in memo_opcodes:
                continue
            if waiting_for_value and opcode.name in integer_opcodes:
                return int(argument)
            if waiting_for_value:
                break
    except Exception as error:
        raise LexiconTaskError(
            f"Could not inspect generation seed in {data_file}: {error}"
        ) from error
    raise LexiconTaskError(f"No integer Sample.seed found in {data_file}")


@lru_cache(maxsize=4)
def _official_blocksworld_mapper_class(repository: Path) -> Any:
    """Load mapper source bytes without mutating sys.path or writing pycache."""

    base_path = repository / "base_mapper.py"
    mapper_path = repository / "domains" / "blocksworld" / "mapper.py"
    if not base_path.is_file() or not mapper_path.is_file():
        raise LexiconTaskError(
            "Official LexiCon checkout is missing Blocksworld mapper sources"
        )
    with _UPSTREAM_IMPORT_LOCK:
        base_module = types.ModuleType("_lexicon_pinned_base_mapper_blocksworld")
        base_module.__file__ = str(base_path)
        exec(
            compile(base_path.read_bytes(), str(base_path), "exec"),
            base_module.__dict__,
        )

        mapper_module = types.ModuleType("_lexicon_pinned_blocksworld_mapper")
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

    mapper_class = getattr(mapper_module, "BlocksworldMapper", None)
    if mapper_class is None:
        raise LexiconTaskError("Official mapper has no BlocksworldMapper")
    return mapper_class


def _official_mapper_messages(
    repository: Path, problem: Any
) -> Tuple[str, str]:
    """Reproduce exactly the two messages sent by upstream ``evaluate_llms``."""

    mapper_class = _official_blocksworld_mapper_class(repository)
    system_prompt, domain_nl, problem_nl = mapper_class(problem).get_problem_nl()
    if not all(isinstance(value, str) for value in (system_prompt, domain_nl, problem_nl)):
        raise LexiconTaskError("Official Blocksworld mapper returned malformed text")
    return system_prompt, domain_nl + problem_nl


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
        if args is None:
            args = getattr(action, "arguments", None)
        if isinstance(name, str) and isinstance(args, (tuple, list)) and all(
            isinstance(argument, str) for argument in args
        ):
            normalized.append(PrimitiveAction(name, tuple(args)))
            continue
        raise TypeError(f"Unsupported action at index {index}: {action!r}")
    return tuple(normalized)


def _object_type_map(task: LexiconBlocksworldTask) -> Dict[str, str]:
    return {
        object_name: type_name
        for type_name, object_names in task.objects_by_type.items()
        for object_name in object_names
    }


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


__all__ = [
    "CONTROLLED_CAMPAIGN_PACKED_IDS",
    "LexiconBlocksworldTask",
    "PublicLexiconBlocksworldTask",
    "LexiconTaskError",
    "OFFICIAL_REPOSITORY",
    "PAPER_CONSTRAINT_LEVELS",
    "PAPER_DATASET_SPLIT",
    "PAPER_PACKED_INSTANCE_IDS",
    "PINNED_OFFICIAL_COMMIT",
    "PRIMITIVE_ARITIES",
    "PRIMITIVE_SIGNATURES",
    "PlanParseError",
    "PlanVerification",
    "PrimitiveAction",
    "available_tasks",
    "checkout_root",
    "load_task",
    "paper_task_ids",
    "parse_direct_plan",
    "public_task_view",
    "validate_ground_fact",
    "validate_primitive_action",
    "verify_plan",
]
