"""Command-line interface for generation, prompting, oracles, and scoring."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .evaluate import evaluate_response
from .generate import DEFAULT_SEED, PROFILE_COUNTS, generate_instances
from .io import canonical_json, read_instances, validate_dataset, write_dataset
from .model import Instance
from .oracle import shortest_path
from .prompt import render_messages, render_prompt
from .report import summarize

PACKAGE_DATA = Path(__file__).resolve().parent / "data"
DEFAULT_DATASETS = {
    "paper-baseline-v1": PACKAGE_DATA / "paper_baseline_v1.jsonl",
    "paper-extension-v1": PACKAGE_DATA / "paper_extension_n6_n7_v1.jsonl",
    "unrestricted-pairs-sensitivity-v1": PACKAGE_DATA / "unrestricted_pairs_sensitivity_v1.jsonl",
    "transformer-n4-v1": PACKAGE_DATA / "transformer_n4_all_pairs_v1.jsonl",
}


def _dump(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _find_instance(path: str, instance_id: str) -> Instance:
    validate_dataset(path)
    matches = [item for item in read_instances(path) if item.instance_id == instance_id]
    if not matches:
        raise ValueError("instance id not found: {}".format(instance_id))
    if len(matches) != 1:
        raise ValueError("instance id is duplicated: {}".format(instance_id))
    return matches[0]


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("{}:{}: {}".format(path, line_number, exc)) from exc
        if not isinstance(row, dict):
            raise ValueError("{}:{} must contain a JSON object".format(path, line_number))
        rows.append(row)
    return rows


def _write_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "".join(canonical_json(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def command_generate(args: argparse.Namespace) -> int:
    output = Path(args.output)
    manifest_path = output.with_suffix(".manifest.json")
    existing = [path for path in (output, manifest_path) if path.exists()]
    if existing and not args.force:
        raise ValueError(
            "refusing to overwrite existing artifact(s): {}; pass --force explicitly"
            .format(", ".join(str(path) for path in existing))
        )
    instances = generate_instances(args.profile, args.seed)
    manifest = write_dataset(output, instances)
    _dump({"output": str(output), "manifest": manifest})
    return 0


def command_validate(args: argparse.Namespace) -> int:
    _dump(validate_dataset(
        args.dataset,
        check_oracle=not args.skip_oracle,
        require_manifest=not args.allow_missing_manifest,
    ))
    return 0


def command_prompt(args: argparse.Namespace) -> int:
    instance = _find_instance(args.dataset, args.instance)
    if args.format == "messages-json":
        _dump(render_messages(instance))
    else:
        print(render_prompt(instance), end="")
    return 0


def command_oracle(args: argparse.Namespace) -> int:
    instance = _find_instance(args.dataset, args.instance)
    moves = shortest_path(instance.start, instance.goal)
    _dump({
        "instance_id": instance.instance_id,
        "optimal_distance": len(moves),
        "moves": [list(move) for move in moves],
    })
    return 0


def command_score(args: argparse.Namespace) -> int:
    instance = _find_instance(args.dataset, args.instance)
    response = args.text
    if args.response is not None:
        response = Path(args.response).read_text(encoding="utf-8")
    assert response is not None
    result = evaluation_row(instance, response)
    _dump(result)
    return 0


def evaluation_row(instance: Instance, response: str) -> Dict[str, Any]:
    row = evaluation_to_row(instance, evaluate_response(instance, response))
    return row


def evaluation_to_row(instance: Instance, evaluation: Any) -> Dict[str, Any]:
    row = evaluation.to_dict()
    row.update({
        "instance_id": instance.instance_id,
        "n": instance.n,
        "sampling_profile": instance.sampling_profile,
    })
    return row


def command_score_batch(args: argparse.Namespace) -> int:
    validate_dataset(args.dataset)
    instances = read_instances(args.dataset)
    response_rows = _read_jsonl(args.responses)
    by_id: Dict[str, Dict[str, Any]] = {}
    known_ids = {item.instance_id for item in instances}
    for row in response_rows:
        instance_id = row.get("instance_id")
        if not isinstance(instance_id, str):
            raise ValueError("every response row needs a string instance_id")
        if instance_id in by_id:
            raise ValueError("duplicate response for {}".format(instance_id))
        if instance_id not in known_ids:
            raise ValueError("response references unknown instance {}".format(instance_id))
        by_id[instance_id] = row
    results = []
    passthrough = (
        "model", "reasoning_effort", "seed", "input_tokens", "output_tokens",
        "reasoning_tokens", "total_tokens", "cost", "finish_reason", "wall_time_seconds",
    )
    for instance in instances:
        source = by_id.get(instance.instance_id, {})
        response = source.get("response", source.get("output_text", ""))
        if not isinstance(response, str):
            response = ""
        result = evaluation_row(instance, response)
        for key in passthrough:
            if key in source:
                result[key] = source[key]
        results.append(result)
    _write_jsonl(args.output, results)
    summary = summarize(results)
    if args.summary:
        Path(args.summary).write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    _dump({"output": args.output, "summary": summary})
    return 0


def command_summarize(args: argparse.Namespace) -> int:
    _dump(summarize(_read_jsonl(args.results)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flat-hanoi")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="generate a frozen dataset and manifest")
    generate.add_argument("--profile", choices=sorted(PROFILE_COUNTS), default="paper-baseline-v1")
    generate.add_argument("--seed", type=int, default=DEFAULT_SEED)
    generate.add_argument("--output", required=True)
    generate.add_argument("--force", action="store_true")
    generate.set_defaults(handler=command_generate)

    validate = subparsers.add_parser("validate", help="validate schema, hashes, uniqueness, and oracle")
    validate.add_argument("dataset")
    validate.add_argument("--skip-oracle", action="store_true")
    validate.add_argument("--allow-missing-manifest", action="store_true")
    validate.set_defaults(handler=command_validate)

    prompt = subparsers.add_parser("prompt", help="render one paper-style prompt")
    prompt.add_argument("--dataset", default=DEFAULT_DATASETS["paper-baseline-v1"])
    prompt.add_argument("--instance", required=True)
    prompt.add_argument("--format", choices=("messages-json", "text"), default="messages-json")
    prompt.set_defaults(handler=command_prompt)

    oracle = subparsers.add_parser("oracle", help="print an exact BFS solution")
    oracle.add_argument("--dataset", default=DEFAULT_DATASETS["paper-baseline-v1"])
    oracle.add_argument("--instance", required=True)
    oracle.set_defaults(handler=command_oracle)

    score = subparsers.add_parser("score", help="score one model response")
    score.add_argument("--dataset", default=DEFAULT_DATASETS["paper-baseline-v1"])
    score.add_argument("--instance", required=True)
    response_group = score.add_mutually_exclusive_group(required=True)
    response_group.add_argument("--response", help="path to response text")
    response_group.add_argument("--text", help="response text supplied directly")
    score.set_defaults(handler=command_score)

    batch = subparsers.add_parser("score-batch", help="score a JSONL response collection")
    batch.add_argument("--dataset", required=True)
    batch.add_argument("--responses", required=True)
    batch.add_argument("--output", required=True)
    batch.add_argument("--summary")
    batch.set_defaults(handler=command_score_batch)

    summary = subparsers.add_parser("summarize", help="aggregate scored JSONL")
    summary.add_argument("results")
    summary.set_defaults(handler=command_summarize)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError) as exc:
        parser.exit(2, "error: {}\n".format(exc))
    return 2


if __name__ == "__main__":
    sys.exit(main())
