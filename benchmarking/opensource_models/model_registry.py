from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Dict, List, Mapping, Optional


HERE = Path(__file__).resolve().parent
DEFAULT_REGISTRY = HERE / "registry.json"
REQUIRED_FIELDS = {
    "display_name",
    "family",
    "capacity_tier",
    "parameter_tier",
    "model_id",
    "served_model_name",
    "backend",
    "port",
    "dtype",
    "tensor_parallel_size",
    "max_model_len",
    "gpu_memory_utilization",
    "vllm_args",
}


def load_registry(path: Path = DEFAULT_REGISTRY) -> Dict[str, Dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") != 1:
        raise ValueError(f"Unsupported registry schema in {path}")
    models = payload.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError(f"Registry has no models: {path}")
    for key, config in models.items():
        validate_model_config(key, config)
    return models


def validate_model_config(key: str, config: object) -> None:
    if not isinstance(config, dict):
        raise ValueError(f"Model {key!r} must be a JSON object")
    missing = REQUIRED_FIELDS.difference(config)
    if missing:
        raise ValueError(f"Model {key!r} is missing fields: {sorted(missing)}")
    if config["backend"] != "vllm":
        raise ValueError(f"Model {key!r} has unsupported backend {config['backend']!r}")
    if config["capacity_tier"] not in {"low", "medium", "high"}:
        raise ValueError(f"Model {key!r} has invalid capacity_tier")
    if not isinstance(config["vllm_args"], list):
        raise ValueError(f"Model {key!r} vllm_args must be a list")


def get_model(key: str, registry_path: Path = DEFAULT_REGISTRY) -> Dict[str, object]:
    models = load_registry(registry_path)
    try:
        return models[key]
    except KeyError as exc:
        available = ", ".join(sorted(models))
        raise ValueError(f"Unknown model {key!r}. Available: {available}") from exc


def build_vllm_command(
    config: Mapping[str, object],
    *,
    host: str = "0.0.0.0",
    port: Optional[int] = None,
    tensor_parallel_size: Optional[int] = None,
    max_model_len: Optional[int] = None,
    gpu_memory_utilization: Optional[float] = None,
) -> List[str]:
    command = [
        "vllm",
        "serve",
        str(config["model_id"]),
        "--served-model-name",
        str(config["served_model_name"]),
        "--host",
        host,
        "--port",
        str(port if port is not None else config["port"]),
        "--dtype",
        str(config["dtype"]),
        "--tensor-parallel-size",
        str(tensor_parallel_size if tensor_parallel_size is not None else config["tensor_parallel_size"]),
        "--max-model-len",
        str(max_model_len if max_model_len is not None else config["max_model_len"]),
        "--gpu-memory-utilization",
        str(
            gpu_memory_utilization
            if gpu_memory_utilization is not None
            else config["gpu_memory_utilization"]
        ),
    ]
    revision = config.get("revision")
    if revision:
        command.extend(["--revision", str(revision)])
    command.extend(str(arg) for arg in config["vllm_args"])
    return command


def shell_join(command: List[str]) -> str:
    return shlex.join(command)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect open-source benchmark model configurations.")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list")
    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("model_key")
    command_parser = subparsers.add_parser("command")
    command_parser.add_argument("model_key")
    args = parser.parse_args()

    models = load_registry(args.registry)
    if args.command == "list":
        for key, config in models.items():
            print(
                f"{key:26} {config['capacity_tier']:6} "
                f"{config['parameter_tier']:4} {config['model_id']}"
            )
        return 0
    config = get_model(args.model_key, args.registry)
    if args.command == "show":
        print(json.dumps(config, indent=2, sort_keys=True))
    else:
        print(shell_join(build_vllm_command(config)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
