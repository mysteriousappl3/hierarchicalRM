"""Run Flat Hanoi and LexiCon Logistics through one N-level control loop.

This is the canonical entry point for ``shared_nlevel_v2``.  The two domains
provide parsing, transition, checkpoint, and scoring hooks, but both execute
``run_shared_nlevel_loop`` unchanged.  Keeping that call in one runner makes
the architecture version in result artifacts an executable claim rather than
just a naming convention.

Examples::

    python benchmarking/shared_nlevel_benchmark.py \
      --domain flat-hanoi --task hanoi_flat_3_00 --provider mock --fixed-goal

    python benchmarking/shared_nlevel_benchmark.py \
      --domain lexicon-logistics --constraints 5 --seed 18 \
      --prompt-source canonical-pddl --provider openai \
      --model gpt-5.6-luna --reasoning low

The runner never reads a LexiCon oracle plan or optimal length when preparing
model requests.  Those evaluator-only values may appear in the final score,
after the adapter has submitted the executed primitive sequence to the
official compiled-PDDL verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from hanoi_benchmark import aggregate_token_usage
from models import create_client, load_env_file
from comparison_protocol import (
    COMPARISON_PROMPT_PROTOCOL_VERSION,
    MINIMUM_ACTION_OBJECTIVE,
    common_semantics_contract,
    with_comparison_contract,
    with_minimum_action_objective,
)
from shared_nlevel_pipeline import SharedLoopResult, run_shared_nlevel_loop


ARCHITECTURE_VERSION = "shared_nlevel_v2"
BENCHMARK_VERSION = 3
EVALUATION_PROTOCOL_VERSION = "public-task-boundary-minimum-actions-v1"
DOMAINS = ("flat-hanoi", "lexicon-logistics")
PROVIDERS = (
    "mock",
    "openai",
    "anthropic",
    "gemini",
    "local",
    "openai-compatible",
)
PROMPT_SOURCES = ("canonical-pddl", "official-mapper", "official-nl")
PAPER_CONSTRAINT_LEVELS = (1, 3, 5, 7, 10)
EVALUATION_CONSTRAINT_LEVELS = (1, 3, 4, 5, 7, 10)
EVALUATION_SEEDS = (*range(1, 31), 51, 53, 54)

BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = BENCHMARK_DIR / ".env"
DEFAULT_RESULTS_DIR = BENCHMARK_DIR / "results" / ARCHITECTURE_VERSION


_ORACLE_FIELDS_BY_DOMAIN = {
    "flat-hanoi": (
        "optimal_move_count",
        "source_peg",
        "auxiliary_peg",
        "target_peg",
    ),
    "lexicon-logistics": (
        "optimal_length",
        "oracle_actions",
        "task_dir",
        "source_files",
        "source_metadata",
    ),
    "lexicon-blocksworld": (
        "optimal_length",
        "oracle_length",
        "oracle_actions",
        "unconstrained_optimal_length",
        "unconstrained_oracle_actions",
        "task_dir",
        "source_files",
        "source_metadata",
        "source_repository_root",
    ),
}


def _task_text_with_exactly_one_objective(
    text: object, domain: Optional[str] = None
) -> str:
    raw = str(text)
    if raw.count(MINIMUM_ACTION_OBJECTIVE) > 1:
        raise ValueError(
            "Model-visible task text contains the common minimum-action "
            "objective more than once"
        )
    prepared = (
        with_comparison_contract(raw, domain)
        if domain is not None
        else with_minimum_action_objective(raw)
    )
    if prepared.count(MINIMUM_ACTION_OBJECTIVE) != 1:  # pragma: no cover
        raise AssertionError("Minimum-action objective injection failed")
    return prepared


class _MinimumActionObjectiveClient:
    """Add the common public contract once to every N-level model request.

    The wrapper changes prompt content only.  Provider dispatch, response
    schemas, usage accounting, call history, and model configuration remain on
    the original client and are exposed through ``__getattr__``.
    """

    def __init__(self, client: object, domain: str) -> None:
        self._client = client
        self._domain = domain

    def __getattr__(self, name: str) -> object:
        return getattr(self._client, name)

    def generate(self, *args: object, **kwargs: object) -> str:
        generate = getattr(self._client, "generate", None)
        if not callable(generate):
            raise TypeError("client must expose a callable generate() method")

        positional = list(args)
        if "prompt" in kwargs:
            prompt = str(kwargs["prompt"])
            system = str(kwargs.get("system", ""))
            occurrences = prompt.count(MINIMUM_ACTION_OBJECTIVE) + system.count(
                MINIMUM_ACTION_OBJECTIVE
            )
            if occurrences > 1:
                raise ValueError(
                    "A shared N-level request contains the common minimum-action "
                    "objective more than once"
                )
            if occurrences == 0:
                kwargs["prompt"] = _task_text_with_exactly_one_objective(
                    prompt, self._domain
                )
        elif len(positional) >= 2:
            system = str(positional[0])
            prompt = str(positional[1])
            occurrences = prompt.count(MINIMUM_ACTION_OBJECTIVE) + system.count(
                MINIMUM_ACTION_OBJECTIVE
            )
            if occurrences > 1:
                raise ValueError(
                    "A shared N-level request contains the common minimum-action "
                    "objective more than once"
                )
            if occurrences == 0:
                positional[1] = _task_text_with_exactly_one_objective(
                    prompt, self._domain
                )
        else:  # pragma: no cover - all repository clients use system + prompt
            raise TypeError("generate() requires a model-visible prompt")
        output = generate(*positional, **kwargs)
        if not isinstance(output, str):
            raise TypeError("model client generate() must return text")
        return output


def _public_task_view(domain: str, task: object) -> object:
    """Construct and validate the domain's slot-only planning task view."""

    if domain == "flat-hanoi":
        from flat_hanoi_task_loader import public_task_view
    elif domain == "lexicon-logistics":
        from lexicon_logistics_task import public_task_view
    elif domain == "lexicon-blocksworld":
        from lexicon_blocksworld_task import public_task_view
    else:
        raise ValueError(f"Unknown shared N-level domain: {domain}")

    public_task = public_task_view(task)
    leaked = [
        name
        for name in _ORACLE_FIELDS_BY_DOMAIN[domain]
        if hasattr(public_task, name)
    ]
    if leaked:  # pragma: no cover - domain constructors enforce this too
        raise RuntimeError(
            "Public planning task leaked evaluator-only fields: "
            + ", ".join(leaked)
        )
    return public_task


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Flat Hanoi or LexiCon Logistics through the identical "
            "StateDescriptor/InnerBot/DecisionBot/N-level/OuterBot loop."
        )
    )
    parser.add_argument("--domain", required=True, choices=DOMAINS)
    parser.add_argument(
        "--task",
        default="hanoi_flat_3_00",
        help="Flat-Hanoi task id, or 'all' (ignored for LexiCon).",
    )
    parser.add_argument(
        "--constraints",
        type=int,
        choices=EVALUATION_CONSTRAINT_LEVELS,
        default=1,
        help=(
            "LexiCon constraint stratum. Levels 1,3,5,7,10 are paper strata; "
            "level 4 is an explicitly labeled development-only stratum."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        choices=EVALUATION_SEEDS,
        default=18,
        help="LexiCon packed instance id (paper: 1..30; level-4 dev: 51,53,54).",
    )
    parser.add_argument(
        "--prompt-source",
        choices=PROMPT_SOURCES,
        default="canonical-pddl",
        help="LexiCon natural-language task source (ignored for Flat Hanoi).",
    )
    parser.add_argument("--provider", choices=PROVIDERS, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument(
        "--reasoning",
        choices=("none", "low", "medium", "high", "xhigh", "max"),
        default=None,
    )
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument(
        "--max-replans",
        type=int,
        default=15,
        help="Correction rounds after the initial attempt (default: 15).",
    )
    parser.add_argument(
        "--fixed-goal",
        action="store_true",
        help="Use the adapter's deterministic StateDescriptor artifact.",
    )
    parser.add_argument(
        "--reuse-h1",
        action="store_true",
        help="Generate H1 once and retain it across selective replans.",
    )
    parser.add_argument(
        "--no-code-block",
        action="store_true",
        help="Omit the non-executable explanatory code block from hierarchy output.",
    )
    parser.add_argument(
        "--results-dir",
        default=str(DEFAULT_RESULTS_DIR),
        help="Root directory for metrics.json, steps.json, and raw_log.jsonl.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional aggregate JSONL path; one metrics record is appended per task.",
    )
    args = parser.parse_args(argv)

    if args.max_tokens <= 0:
        parser.error("--max-tokens must be positive")
    if args.max_replans < 0:
        parser.error("--max-replans must be non-negative")
    if args.domain == "lexicon-logistics":
        if args.constraints == 4 and args.seed not in {51, 53, 54}:
            parser.error(
                "LexiCon level 4 is development-only and supports seeds 51, 53, 54"
            )
        if args.constraints in PAPER_CONSTRAINT_LEVELS and args.seed not in range(1, 31):
            parser.error("LexiCon paper strata support packed instance ids 1..30")
    return args


def _load_task_and_adapter(
    domain: str,
    *,
    task_id: str,
    constraints: int,
    seed: int,
    prompt_source: str,
) -> Tuple[object, object]:
    """Load domain dependencies lazily so Flat Hanoi does not require UP."""

    if domain == "flat-hanoi":
        from flat_hanoi_task_loader import load_task
        from shared_nlevel_flat_hanoi import FlatHanoiNLevelAdapter

        return load_task(task_id), FlatHanoiNLevelAdapter()
    if domain == "lexicon-logistics":
        from lexicon_logistics_task import load_task
        from shared_nlevel_lexicon import SharedNLevelLexiconAdapter

        return (
            load_task(constraints, seed, prompt_source),
            SharedNLevelLexiconAdapter(),
        )
    raise ValueError(f"Unknown shared N-level domain: {domain}")


def _task_ids(args: argparse.Namespace) -> List[str]:
    if args.domain != "flat-hanoi" or args.task != "all":
        return [args.task]
    from flat_hanoi_task_loader import available_tasks

    return list(available_tasks())


def _score_payload(score: object) -> Dict[str, object]:
    for method_name in ("to_dict", "as_dict"):
        method = getattr(score, method_name, None)
        if callable(method):
            payload = method()
            if isinstance(payload, Mapping):
                return dict(payload)
    if is_dataclass(score):
        return asdict(score)
    if isinstance(score, Mapping):
        return dict(score)
    return {"value": str(score)}


def _jsonable(value: object) -> object:
    """Convert rich parser artifacts to stable, auditable JSON values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    for method_name in ("to_dict", "as_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            return _jsonable(method())
    if is_dataclass(value):
        return _jsonable(asdict(value))
    return str(value)


def _safe_path_part(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
    return normalized or "unknown"


def _make_result_dir(
    root: Path, domain: str, model: str, task_id: str
) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    suffix = uuid.uuid4().hex[:8]
    path = (
        root
        / _safe_path_part(model)
        / _safe_path_part(domain)
        / f"{_safe_path_part(task_id)}_{stamp}_{suffix}"
    )
    path.mkdir(parents=True, exist_ok=False)
    return path


def _write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(_jsonable(payload), handle, indent=2, sort_keys=True)
        handle.write("\n")


def _write_raw_log(
    path: Path,
    call_records: Iterable[Mapping[str, object]],
    attempts: Iterable[Mapping[str, object]],
) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index, record in enumerate(call_records, start=1):
            payload = {"event": "model_call", "call_index": index, **dict(record)}
            handle.write(json.dumps(_jsonable(payload), sort_keys=True) + "\n")
        for attempt in attempts:
            payload = {"event": "attempt_result", **dict(attempt)}
            handle.write(json.dumps(_jsonable(payload), sort_keys=True) + "\n")


def _client_call_records(client: object, start_index: int) -> List[Dict[str, object]]:
    records_since = getattr(client, "call_records_since", None)
    if callable(records_since):
        records = records_since(start_index)
        return [dict(record) for record in records]
    history = getattr(client, "call_history", None)
    if not isinstance(history, list):
        return []
    records: List[Dict[str, object]] = []
    for item in history[start_index:]:
        converted = _jsonable(item)
        records.append(dict(converted) if isinstance(converted, Mapping) else {"value": converted})
    return records


def _domain_metadata(domain: str, task: object) -> Dict[str, object]:
    if domain == "flat-hanoi":
        return {
            "ring_count": len(getattr(task, "rings", ())),
            "peg_count": len(getattr(task, "pegs", ())),
            "optimal_move_count": getattr(task, "optimal_move_count", None),
        }

    prompt = str(getattr(task, "prompt_text")())
    source_metadata = getattr(task, "source_metadata")()
    return {
        "dataset_split": getattr(task, "dataset_split"),
        "paper_benchmark_task": bool(getattr(task, "is_paper_task")),
        "nominal_constraint_count": getattr(task, "constraint_count"),
        "actual_pddl_constraint_count": getattr(task, "actual_constraint_count"),
        "packed_instance_index": getattr(task, "seed"),
        "prompt_source": getattr(task, "prompt_source"),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "source": source_metadata,
    }


def _model_visible_task_payload(domain: str, task: object) -> Dict[str, object]:
    """Record public task inputs only; intentionally exclude LexiCon oracles."""

    if domain == "flat-hanoi":
        return {
            "task_id": getattr(task, "id"),
            "instruction": _task_text_with_exactly_one_objective(
                getattr(task, "instruction"), domain
            ),
            "pegs": list(getattr(task, "pegs")),
            "initial": getattr(task, "initial"),
            "goal": getattr(task, "goal"),
        }
    return {
        "task_id": getattr(task, "id"),
        "prompt_source": getattr(task, "prompt_source"),
        "problem_text": _task_text_with_exactly_one_objective(
            getattr(task, "prompt_text")(), domain
        ),
        "authoritative_descriptor": getattr(task, "descriptor_payload")(),
    }


def _success(domain: str, score: Mapping[str, object]) -> bool:
    return bool(score.get("solved")) if domain == "flat-hanoi" else bool(score.get("valid"))


def run_shared_task(
    *,
    domain: str,
    task: object,
    adapter: object,
    client: object,
    fixed_goal: bool,
    max_tokens: int,
    max_replans: int,
    reasoning_effort: Optional[str],
    reuse_h1: bool,
    include_code_block: bool,
    results_dir: Path,
) -> Dict[str, object]:
    """Execute one task, write its structured artifacts, and return metrics."""

    public_task = _public_task_view(domain, task)
    planning_client = _MinimumActionObjectiveClient(client, domain)
    call_history = getattr(client, "call_history", None)
    call_start = len(call_history) if isinstance(call_history, list) else 0
    started_at = datetime.now().astimezone()
    timer_start = time.perf_counter()
    result: SharedLoopResult = run_shared_nlevel_loop(
        task=public_task,
        final_score_task=task,
        client=planning_client,
        adapter=adapter,
        fixed_goal=fixed_goal,
        max_tokens=max_tokens,
        max_replans=max_replans,
        reuse_h1=reuse_h1,
        include_code_block=include_code_block,
        reasoning_effort=reasoning_effort,
    )
    elapsed = time.perf_counter() - timer_start
    call_records = _client_call_records(client, call_start)
    token_usage = aggregate_token_usage(call_records)
    score = _score_payload(result.score)
    task_id = str(getattr(task, "id", getattr(task, "task_id", "unknown")))
    model = str(getattr(client, "model", "unknown"))
    provider = str(getattr(client, "provider", "unknown"))
    adapter_verifier = str(getattr(adapter, "verifier_mode", result.verifier_mode))
    extra_metrics = dict(result.extra_metrics)

    metrics: Dict[str, object] = {
        "benchmark": "shared_nlevel",
        "benchmark_version": BENCHMARK_VERSION,
        "architecture_version": ARCHITECTURE_VERSION,
        "evaluation_protocol_version": EVALUATION_PROTOCOL_VERSION,
        "comparison_prompt_protocol_version": COMPARISON_PROMPT_PROTOCOL_VERSION,
        "comparison_semantics_sha256": hashlib.sha256(
            common_semantics_contract(domain).encode("utf-8")
        ).hexdigest(),
        "minimum_action_objective": MINIMUM_ACTION_OBJECTIVE,
        "shared_control_loop": "run_shared_nlevel_loop",
        "domain": domain,
        "task_id": task_id,
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "started_at": started_at.isoformat(),
        "runtime_seconds": round(elapsed, 6),
        "fixed_goal": fixed_goal,
        "reuse_h1": reuse_h1,
        "include_code_block": include_code_block,
        "max_tokens": max_tokens,
        "max_replans": max_replans,
        "verifier_mode": adapter_verifier,
        "termination_reason": result.termination_reason,
        "success": _success(domain, score),
        "attempt_count": len(result.attempts),
        "replan_count": result.replan_count,
        "model_call_count": result.model_call_count,
        "recorded_model_call_count": len(call_records),
        "model_call_accounting_consistent": result.model_call_count == len(call_records),
        "stage_counts": dict(result.stage_counts),
        "model_calls_by_stage": extra_metrics.get("model_calls_by_stage", {}),
        "token_usage": token_usage,
        "score": score,
        "extra_metrics": extra_metrics,
        "planning_task_boundary": {
            "planning_task_type": type(public_task).__name__,
            "final_score_task_type": type(task).__name__,
            "oracle_fields_structurally_absent": True,
            "forbidden_fields": list(_ORACLE_FIELDS_BY_DOMAIN[domain]),
            "private_task_use": "final-authoritative-score-and-metadata-only",
        },
        **_domain_metadata(domain, task),
    }

    formatted_actions = [adapter.format_action(action) for action in result.executed_actions]
    steps = {
        "benchmark": "shared_nlevel",
        "architecture_version": ARCHITECTURE_VERSION,
        "evaluation_protocol_version": EVALUATION_PROTOCOL_VERSION,
        "comparison_prompt_protocol_version": COMPARISON_PROMPT_PROTOCOL_VERSION,
        "comparison_semantics_sha256": hashlib.sha256(
            common_semantics_contract(domain).encode("utf-8")
        ).hexdigest(),
        "minimum_action_objective": MINIMUM_ACTION_OBJECTIVE,
        "domain": domain,
        "task_id": task_id,
        "model_visible_task": _model_visible_task_payload(domain, public_task),
        "outputs": dict(result.outputs),
        "attempts": list(result.attempts),
        "candidate_plan": formatted_actions,
        "high_level_plan": list(result.high_level_plan),
        "expanded_h0_plan": list(result.expanded_h0_plan),
        "final_state": adapter.snapshot_state(public_task, result.final_state),
        "parse_errors": list(result.parse_errors),
        "router_attributions": list(result.router_attributions),
    }

    output_dir = _make_result_dir(results_dir, domain, model, task_id)
    metrics["result_dir"] = str(output_dir)
    _write_json(output_dir / "metrics.json", metrics)
    _write_json(output_dir / "steps.json", steps)
    _write_raw_log(output_dir / "raw_log.jsonl", call_records, result.attempts)
    candidate_name = (
        "candidate_plan.pddl"
        if domain == "lexicon-logistics"
        else "candidate_moves.txt"
    )
    with (output_dir / candidate_name).open("w", encoding="utf-8") as handle:
        for action in formatted_actions:
            handle.write(f"{action}\n")
    return dict(_jsonable(metrics))


def _append_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_jsonable(row), sort_keys=True) + "\n")


def _print_summary(rows: Sequence[Mapping[str, object]]) -> None:
    for row in rows:
        score = row.get("score", {})
        status = score.get("status") if isinstance(score, Mapping) else None
        if status is None:
            status = "SOLVED" if row.get("success") else "INVALID"
        print(
            f"{row['task_id']} {row['domain']}: status={status} "
            f"success={row['success']} calls={row['model_call_count']} "
            f"attempts={row['attempt_count']} result={row['result_dir']}"
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    load_env_file(Path(args.env_file))
    provider = args.provider or os.environ.get("DEFAULT_PROVIDER") or "mock"
    model = args.model or os.environ.get("DEFAULT_MODEL")
    configured_reasoning = args.reasoning or os.environ.get("DEFAULT_REASONING_EFFORT")
    reasoning_effort = None if configured_reasoning in {None, "none"} else configured_reasoning

    if args.domain == "lexicon-logistics" and provider == "mock":
        print(
            "provider=mock is the repository's Hanoi-specific mock and cannot "
            "produce LexiCon grammar. Select an explicit real/local provider; "
            "the offline LexiCon integration test uses a protocol-specific "
            "scripted client.",
            file=sys.stderr,
        )
        return 2

    rows: List[Dict[str, object]] = []
    for task_id in _task_ids(args):
        task, adapter = _load_task_and_adapter(
            args.domain,
            task_id=task_id,
            constraints=args.constraints,
            seed=args.seed,
            prompt_source=args.prompt_source,
        )
        client = create_client(
            provider=provider,
            model=model,
            base_url=args.base_url,
            reasoning_effort=reasoning_effort,
            temperature=args.temperature,
        )
        # create_client uses one transport class for OpenAI and compatible
        # endpoints.  Preserve the user's selected provider in audit metrics.
        client.provider = provider
        rows.append(
            run_shared_task(
                domain=args.domain,
                task=task,
                adapter=adapter,
                client=client,
                fixed_goal=args.fixed_goal,
                max_tokens=args.max_tokens,
                max_replans=args.max_replans,
                reasoning_effort=reasoning_effort,
                reuse_h1=args.reuse_h1,
                include_code_block=not args.no_code_block,
                results_dir=Path(args.results_dir),
            )
        )

    if args.output:
        _append_jsonl(Path(args.output), rows)
    _print_summary(rows)
    return 0 if all(bool(row["success"]) for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
