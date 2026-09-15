"""JSONL persistence and cryptographic manifests."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from .generate import GENERATOR_VERSION, PROFILE_COUNTS
from .model import Instance, is_strict_flat
from .oracle import shortest_distance

PathLike = Union[str, Path]
_PACKAGE_ROOT = Path(__file__).resolve().parent


def benchmark_artifact_hashes() -> Dict[str, str]:
    """Bind manifests to the exact prompt and scoring implementation."""

    files = {
        "prompt_system": "paper_derived_system_v1.txt",
        "prompt_user": "paper_derived_user_v1.txt",
        "prompt_renderer_source": "prompt.py",
        "generator_source": "generate.py",
        "batch_cli_source": "cli.py",
        "manifest_io_source": "io.py",
        "parser_source": "parse.py",
        "state_model_source": "model.py",
        "simulator_source": "state.py",
        "oracle_source": "oracle.py",
        "evaluator_source": "evaluate.py",
        "report_source": "report.py",
    }
    return {
        label + "_sha256": sha256_bytes((_PACKAGE_ROOT / filename).read_bytes())
        for label, filename in sorted(files.items())
    }


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def jsonl_bytes(instances: Iterable[Instance]) -> bytes:
    return b"".join((canonical_json(item.to_dict()) + "\n").encode("utf-8")
                    for item in instances)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_manifest(instances: List[Instance], payload: Optional[bytes] = None) -> Dict[str, Any]:
    if not instances:
        raise ValueError("cannot manifest an empty dataset")
    raw = payload if payload is not None else jsonl_bytes(instances)
    counts = Counter(str(item.n) for item in instances)
    distances = Counter(str(item.optimal_distance) for item in instances)
    splits = Counter(item.split for item in instances if item.split is not None)
    profile = instances[0].sampling_profile
    policies = {
        "paper-baseline-v1": "uniform_without_replacement_conditioned_on_both_endpoints_using_multiple_pegs",
        "paper-extension-v1": "uniform_without_replacement_conditioned_on_both_endpoints_using_multiple_pegs",
        "unrestricted-pairs-sensitivity-v1": "uniform_without_replacement_over_all_distinct_ordered_pairs",
        "transformer-n4-v1": "exhaustive_all_distinct_ordered_pairs",
    }
    manifest: Dict[str, Any] = {
        "schema_version": 1,
        "generator_version": GENERATOR_VERSION,
        "sampling_profile": profile,
        "sampling_policy": policies.get(profile, "unspecified"),
        "generator_seed": instances[0].generator_seed,
        "instance_count": len(instances),
        "counts_by_n": dict(sorted(counts.items(), key=lambda pair: int(pair[0]))),
        "optimal_distance_histogram": dict(sorted(distances.items(), key=lambda pair: int(pair[0]))),
        "jsonl_sha256": sha256_bytes(raw),
        "benchmark_artifact_hashes": benchmark_artifact_hashes(),
        "evaluation_protocol": {
            "headline_metric": "optimal_accuracy",
            "max_output_tokens": 32000,
            "output_budget_scope": "answer_only; provider-side reasoning may be additional",
            "temperature": 1.0,
            "temperature_basis": "inherited_from_the_cited_shojaee_baseline_protocol",
            "tools_allowed": False,
            "unparseable_in_denominator": True,
        },
    }
    if splits:
        manifest["counts_by_split"] = dict(sorted(splits.items()))
    return manifest


def write_dataset(path: PathLike, instances: List[Instance]) -> Dict[str, Any]:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = jsonl_bytes(instances)
    destination.write_bytes(raw)
    manifest = build_manifest(instances, raw)
    manifest_path = destination.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def read_instances(path: PathLike) -> List[Instance]:
    source = Path(path)
    records = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            records.append(Instance.from_dict(raw))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("{}:{}: {}".format(source, line_number, exc)) from exc
    if not records:
        raise ValueError("dataset is empty")
    return records


def validate_dataset(
    path: PathLike,
    check_oracle: bool = True,
    require_manifest: bool = True,
) -> Dict[str, Any]:
    source = Path(path)
    raw = source.read_bytes()
    instances = read_instances(source)
    ids = [item.instance_id for item in instances]
    pairs = [(item.n, item.start, item.goal) for item in instances]
    if len(ids) != len(set(ids)):
        raise ValueError("instance ids are not unique")
    if len(pairs) != len(set(pairs)):
        raise ValueError("start/goal pairs are not unique")
    profiles = {item.sampling_profile for item in instances}
    seeds = {item.generator_seed for item in instances}
    if len(profiles) != 1 or len(seeds) != 1:
        raise ValueError("dataset mixes profiles or generator seeds")
    profile = next(iter(profiles))
    if profile in PROFILE_COUNTS:
        actual_counts = Counter(item.n for item in instances)
        if dict(actual_counts) != PROFILE_COUNTS[profile]:
            raise ValueError("dataset counts do not match its named generation profile")
    if profile in ("paper-baseline-v1", "paper-extension-v1"):
        if any(not is_strict_flat(item.start) or not is_strict_flat(item.goal)
               for item in instances):
            raise ValueError("paper profile contains an endpoint that is not spread across pegs")
    if profile == "transformer-n4-v1":
        split_counts = Counter(item.split for item in instances)
        if split_counts != {"train": 5184, "validation": 1296}:
            raise ValueError("transformer profile does not have its exact 80/20 split")
    if check_oracle:
        for item in instances:
            exact = shortest_distance(item.start, item.goal)
            if exact != item.optimal_distance:
                raise ValueError("{} has incorrect optimal_distance".format(item.instance_id))
    calculated = build_manifest(instances, raw)
    manifest_path = source.with_suffix(".manifest.json")
    if not manifest_path.exists():
        if require_manifest:
            raise ValueError("adjacent manifest is missing: {}".format(manifest_path))
    else:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Dict equality conflates JSON booleans/floats with integers in Python
        # (for example, True == 1). Canonical JSON preserves those type
        # distinctions and makes type-only manifest tampering detectable.
        if canonical_json(recorded) != canonical_json(calculated):
            raise ValueError("manifest does not match dataset bytes or metadata")
    calculated["validated"] = True
    calculated["oracle_checked"] = check_oracle
    calculated["manifest_checked"] = manifest_path.exists()
    return calculated
