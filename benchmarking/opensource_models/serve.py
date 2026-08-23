from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from model_registry import DEFAULT_REGISTRY, build_vllm_command, get_model, shell_join


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start one registered model with vLLM.")
    parser.add_argument("model_key")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int)
    parser.add_argument("--tensor-parallel-size", type=int)
    parser.add_argument("--max-model-len", type=int)
    parser.add_argument("--gpu-memory-utilization", type=float)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = get_model(args.model_key, args.registry)
    command = build_vllm_command(
        config,
        host=args.host,
        port=args.port,
        tensor_parallel_size=args.tensor_parallel_size,
        max_model_len=args.max_model_len,
        gpu_memory_utilization=args.gpu_memory_utilization,
    )
    print(shell_join(command), flush=True)
    if args.dry_run:
        return 0
    if os.name == "posix":
        os.execvp(command[0], command)
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
