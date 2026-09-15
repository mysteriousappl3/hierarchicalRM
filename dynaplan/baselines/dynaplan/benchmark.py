#!/usr/bin/env python3
"""Self-contained official entry point for the DynaPlan architecture.

The runtime modules in ``runtime/`` are a frozen copy of the architecture.
Keeping them on a private import path lets the unified benchmark invoke
DynaPlan in a subprocess without sharing module state with literature ports.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


SCRIPT_PATH = Path(__file__).resolve()
METHOD_ROOT = SCRIPT_PATH.parent
RUNTIME_ROOT = METHOD_ROOT / "runtime"
DYNAPLAN_ROOT = METHOD_ROOT.parents[1]
BENCHMARKS_ROOT = DYNAPLAN_ROOT / "benchmarks"
FLAT_HANOI_ROOT = BENCHMARKS_ROOT / "Flat-Hanoi"
_VENDORED_LEXICON_ROOT = BENCHMARKS_ROOT / "LexiCon"
_WORKSPACE_LEXICON_ROOT = (
    DYNAPLAN_ROOT.parents[1] / "dynaplan" / "benchmarks" / "LexiCon"
)
LEXICON_ROOT = Path(
    os.environ.get(
        "DYNAPLAN_LEXICON_ROOT",
        str(
            _VENDORED_LEXICON_ROOT
            if (_VENDORED_LEXICON_ROOT / ".git").exists()
            else _WORKSPACE_LEXICON_ROOT
        ),
    )
).resolve()
DEFAULT_ENV_FILE = DYNAPLAN_ROOT / ".env"
DEFAULT_RESULTS_ROOT = BENCHMARKS_ROOT / "results" / "dynaplan_native"
PINNED_LEXICON_COMMIT = "8dfb02ef0188e0c7fea55ca38d702c21d75f9691"

if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))
if str(FLAT_HANOI_ROOT) not in sys.path:
    sys.path.insert(1, str(FLAT_HANOI_ROOT))

import comparison_protocol  # noqa: E402
import dynaplan_nlevel_pipeline  # noqa: E402
import shared_nlevel_benchmark as shared_runner  # noqa: E402
from dynaplan_nlevel_adapter import (  # noqa: E402
    PIPELINE_VERSION,
    DynaPlanBlocksworldAdapter,
    DynaPlanFlatHanoiAdapter,
    DynaPlanLexiconAdapter,
)
from models import create_client  # noqa: E402


BENCHMARK_VERSION = 61
DOMAINS = ("logistics", "blocksworld", "flat-hanoi")


class IntegrationError(RuntimeError):
    """Raised when the copied runtime or official task boundary is invalid."""


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_env_authoritative(path: Path) -> None:
    if not path.is_file():
        raise IntegrationError(f"Environment file does not exist: {path}")
    key_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise IntegrationError(f"Malformed dotenv entry at {path}:{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key_pattern.fullmatch(key):
            raise IntegrationError(f"Invalid dotenv key at {path}:{line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _git_head(repository: Path) -> str:
    import subprocess

    completed = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise IntegrationError(
            f"Could not inspect LexiCon checkout: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _resolve_hanoi_task(value: str) -> Tuple[str, int]:
    requested = value.strip()
    short = re.fullmatch(r"n(?P<n>[3-7])-(?P<index>\d{4})", requested)
    reversed_short = re.fullmatch(r"(?P<n>[3-7])n-(?P<index>\d{4})", requested)
    indexed = re.fullmatch(r"(?P<n>[3-7])_(?P<index>\d{2})", requested)
    canonical = re.fullmatch(
        r"paper-(?:baseline|extension)-v1-n(?P<n>[3-7])-(?P<index>\d{4})",
        requested,
    )
    match = short or reversed_short or indexed or canonical
    if match is None:
        raise IntegrationError(
            "Flat-Hanoi task must be n3-0017, 3n-0017, 3_00, or a canonical "
            "paper-* instance ID"
        )
    n = int(match.group("n"))
    if canonical:
        return requested, n
    index = int(match.group("index"))
    profile = "paper-baseline-v1" if n <= 5 else "paper-extension-v1"
    return f"{profile}-n{n}-{index:04d}", n


def _load_flat_task(task_name: str) -> object:
    from flat_hanoi.io import read_instances
    from flat_hanoi_task_loader import FlatHanoiTask, validate_task
    from task_loader import Ring

    task_id, n = _resolve_hanoi_task(task_name)
    dataset_name = (
        "paper_baseline_v1.jsonl"
        if n <= 5
        else "paper_extension_n6_n7_v1.jsonl"
    )
    dataset = FLAT_HANOI_ROOT / "flat_hanoi" / "data" / dataset_name
    instance = next(
        (item for item in read_instances(dataset) if item.instance_id == task_id),
        None,
    )
    if instance is None:
        raise IntegrationError(f"Flat-Hanoi instance is absent: {task_id}")
    pegs = ["peg_0", "peg_1", "peg_2"]

    def stacks(state: Sequence[int]) -> Dict[str, list[str]]:
        return {
            pegs[peg]: [
                f"ring_{disk}"
                for disk in range(instance.n, 0, -1)
                if state[disk - 1] == peg
            ]
            for peg in range(3)
        }

    task = FlatHanoiTask(
        id=task_id,
        name=f"Paper-derived Flat-Hanoi {task_name}",
        pegs=pegs,
        rings=[
            Ring(name=f"ring_{disk}", size=disk, label=f"ring {disk}")
            for disk in range(1, instance.n + 1)
        ],
        initial=stacks(instance.start),
        goal=stacks(instance.goal),
        instruction=(
            "Transform the arbitrary initial stacks into the exact goal stacks "
            "using legal Tower of Hanoi moves."
        ),
        optimal_move_count=instance.optimal_distance,
    )
    validate_task(task)
    return task


def _load_task(domain: str, task_name: str, constraints: int, lexicon_id: int) -> object:
    if domain == "flat-hanoi":
        return _load_flat_task(task_name)
    if _git_head(LEXICON_ROOT) != PINNED_LEXICON_COMMIT:
        raise IntegrationError(
            f"LexiCon must be pinned at {PINNED_LEXICON_COMMIT}"
        )
    if domain == "logistics":
        import lexicon_logistics_task as task_module

        task_module.checkout_root = lambda: LEXICON_ROOT
        task = task_module.load_task(
            constraints, lexicon_id, prompt_source="official-mapper"
        )
        return dataclasses.replace(
            task, id=f"lexicon-logistics-c{constraints}-id{lexicon_id}"
        )
    if domain == "blocksworld":
        import lexicon_blocksworld_task as task_module

        return task_module.load_task(
            constraints,
            lexicon_id,
            prompt_source="official-mapper",
            checkout=LEXICON_ROOT,
        )
    raise IntegrationError(f"Unsupported domain: {domain}")


def _adapter(domain: str) -> object:
    return {
        "logistics": DynaPlanLexiconAdapter,
        "blocksworld": DynaPlanBlocksworldAdapter,
        "flat-hanoi": DynaPlanFlatHanoiAdapter,
    }[domain]()


class _SharedHanoiExampleClient:
    """Apply the registered common example without changing model-call count."""

    def __init__(self, client: object, *, enabled: bool) -> None:
        self._client = client
        self._enabled = enabled

    def __getattr__(self, name: str) -> object:
        return getattr(self._client, name)

    def generate(self, *args: object, **kwargs: object) -> str:
        positional = list(args)
        if self._enabled:
            if "prompt" in kwargs:
                prompt = str(kwargs["prompt"])
                if comparison_protocol.FLAT_HANOI_SHARED_SOLVED_EXAMPLE not in prompt:
                    kwargs["prompt"] = (
                        prompt.rstrip()
                        + "\n\n"
                        + comparison_protocol.FLAT_HANOI_SHARED_SOLVED_EXAMPLE
                    )
            elif len(positional) >= 2:
                prompt = str(positional[1])
                if comparison_protocol.FLAT_HANOI_SHARED_SOLVED_EXAMPLE not in prompt:
                    positional[1] = (
                        prompt.rstrip()
                        + "\n\n"
                        + comparison_protocol.FLAT_HANOI_SHARED_SOLVED_EXAMPLE
                    )
        generate = getattr(self._client, "generate")
        return generate(*positional, **kwargs)


def _public_boundary(domain: str, task: object) -> Dict[str, Any]:
    internal_domain = {
        "logistics": "lexicon-logistics",
        "blocksworld": "lexicon-blocksworld",
        "flat-hanoi": "flat-hanoi",
    }[domain]
    public = shared_runner._public_task_view(internal_domain, task)
    forbidden = tuple(shared_runner._ORACLE_FIELDS_BY_DOMAIN[internal_domain])
    leaked = [name for name in forbidden if hasattr(public, name)]
    return {
        "planning_task_type": type(public).__name__,
        "private_task_type": type(task).__name__,
        "oracle_fields_structurally_absent": not leaked,
        "forbidden_fields": list(forbidden),
        "leaked_fields": leaked,
        "slot_only": not hasattr(public, "__dict__"),
    }


def preflight(args: argparse.Namespace) -> Dict[str, Any]:
    task = _load_task(args.domain, args.task, args.constraints, args.lexicon_id)
    adapter = _adapter(args.domain)
    boundary = _public_boundary(args.domain, task)
    runtime_files = sorted(RUNTIME_ROOT.glob("*.py"))
    if not runtime_files:
        raise IntegrationError("Copied DynaPlan runtime is empty")
    if PIPELINE_VERSION != "dynaplan_v1_3_compact_fallback":
        raise IntegrationError(f"Unexpected DynaPlan version: {PIPELINE_VERSION}")
    if not boundary["oracle_fields_structurally_absent"] or not boundary["slot_only"]:
        raise IntegrationError(f"Public task boundary failed: {boundary}")
    return {
        "status": "PASS",
        "framework": "DynaPlan",
        "architecture_version": PIPELINE_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "domain": args.domain,
        "task_id": str(getattr(task, "id")),
        "adapter_type": type(adapter).__name__,
        "runtime_file_count": len(runtime_files),
        "runtime_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in runtime_files
        },
        "public_task_boundary": boundary,
        "model_inference_performed": False,
    }


def run(args: argparse.Namespace) -> Dict[str, Any]:
    _load_env_authoritative(args.env_file)
    if args.provider == "anthropic":
        if args.anthropic_thinking_budget is None:
            raise IntegrationError(
                "Anthropic DynaPlan runs require --anthropic-thinking-budget"
            )
        os.environ["ANTHROPIC_THINKING_BUDGET_TOKENS"] = str(
            args.anthropic_thinking_budget
        )
    task = _load_task(args.domain, args.task, args.constraints, args.lexicon_id)
    adapter = _adapter(args.domain)
    client = create_client(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        reasoning_effort=args.reasoning,
    )
    client.provider = args.provider
    fair_client = _SharedHanoiExampleClient(
        client, enabled=args.domain == "flat-hanoi"
    )
    internal_domain = {
        "logistics": "lexicon-logistics",
        "blocksworld": "lexicon-blocksworld",
        "flat-hanoi": "flat-hanoi",
    }[args.domain]

    shared_runner.ARCHITECTURE_VERSION = PIPELINE_VERSION
    shared_runner.BENCHMARK_VERSION = BENCHMARK_VERSION
    shared_runner.run_shared_nlevel_loop = dynaplan_nlevel_pipeline.run_shared_nlevel_loop
    metrics = shared_runner.run_shared_task(
        domain=internal_domain,
        task=task,
        adapter=adapter,
        client=fair_client,
        fixed_goal=False,
        max_tokens=args.max_output_tokens,
        max_replans=args.max_replans,
        reasoning_effort=args.reasoning,
        reuse_h1=True,
        include_code_block=True,
        results_dir=args.results_dir,
    )
    metrics["official_integration"] = {
        "entrypoint": str(SCRIPT_PATH),
        "copied_runtime_root": str(RUNTIME_ROOT),
        "copied_runtime_only": True,
        "common_hanoi_solved_example_injected": args.domain == "flat-hanoi",
        "common_minimum_action_objective_injected": True,
        "official_final_evaluator_call_count": int(
            getattr(adapter, "official_final_evaluator_call_count", 0)
        ),
        "public_task_boundary": _public_boundary(args.domain, task),
    }
    result_dir = Path(str(metrics["result_dir"]))
    _write_json(result_dir / "metrics.json", metrics)
    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, choices=DOMAINS)
    parser.add_argument("--task", default="n3-0017")
    parser.add_argument("--constraints", type=int, default=1)
    parser.add_argument("--lexicon-id", type=int, default=1)
    parser.add_argument(
        "--provider", choices=("openai", "openrouter", "anthropic"), default="openai"
    )
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--reasoning", default="medium")
    parser.add_argument("--anthropic-thinking-budget", type=int)
    parser.add_argument("--base-url")
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--max-replans", type=int, default=15)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_output_tokens <= 0 or args.max_replans < 0:
        parser.error("token and replan limits must be non-negative/positive")
    if args.preflight == args.execute:
        parser.error("select exactly one of --preflight or --execute")
    if args.provider == "anthropic":
        if args.anthropic_thinking_budget is None:
            parser.error("Anthropic requires --anthropic-thinking-budget")
        if not 1024 <= args.anthropic_thinking_budget < args.max_output_tokens:
            parser.error(
                "Anthropic thinking budget must be >=1024 and below max output"
            )
    try:
        payload = preflight(args) if args.preflight else run(args)
        if args.output_json:
            _write_json(args.output_json, payload)
        print(json.dumps(_jsonable(payload), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
