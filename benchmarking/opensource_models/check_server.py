from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

from model_registry import DEFAULT_REGISTRY, get_model


def get_json(url: str, timeout: int) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: object, timeout: int) -> object:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a registered vLLM server.")
    parser.add_argument("model_key")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Also make a one-token chat request. This performs inference.",
    )
    args = parser.parse_args()
    config = get_model(args.model_key, args.registry)
    port = args.port if args.port is not None else int(config["port"])
    base_url = f"http://{args.host}:{port}/v1"

    try:
        response = get_json(f"{base_url}/models", args.timeout)
        if not isinstance(response, dict):
            print("Server returned an invalid model-list response")
            return 2
        served_ids = [item.get("id") for item in response.get("data", [])]
        expected = str(config["served_model_name"])
        if expected not in served_ids:
            print(f"Server responded, but {expected!r} was not advertised: {served_ids}")
            return 2
        print(f"Ready: {expected} at {base_url}")
        if args.generate:
            completion = post_json(
                f"{base_url}/chat/completions",
                {
                    "model": expected,
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "max_tokens": 1,
                    "temperature": 0,
                },
                args.timeout,
            )
            print(json.dumps(completion, indent=2))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Server check failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
