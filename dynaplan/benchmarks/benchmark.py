#!/usr/bin/env python3
"""Unified, provenance-preserving smoke runner for Dynaplan benchmarks.

The runner exposes the direct baseline plus six mechanism-preserving literature
ports on LexiCon Logistics, LexiCon Blocksworld, and paper-derived Flat-Hanoi.
The provider and model are explicit campaign parameters. Model inference
requires ``--execute``; otherwise the command performs validation only.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCRIPT_PATH = Path(__file__).resolve()
BENCHMARKS_ROOT = SCRIPT_PATH.parent
DYNAPLAN_ROOT = BENCHMARKS_ROOT.parent
LEXICON_ROOT = Path(
    os.environ.get("DYNAPLAN_LEXICON_ROOT", str(BENCHMARKS_ROOT / "LexiCon"))
).resolve()
FLAT_HANOI_ROOT = BENCHMARKS_ROOT / "Flat-Hanoi"
BASELINE_CLONES_ROOT = DYNAPLAN_ROOT / "baselines"
SHARED_ADAPTER_ROOT = DYNAPLAN_ROOT.parent / "simmer-style-libero" / "benchmarking"
DEFAULT_ENV_FILE = DYNAPLAN_ROOT / ".env"
DEFAULT_RESULTS_ROOT = BENCHMARKS_ROOT / "results"

PROVIDER = "openai"
MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "medium"
ANTHROPIC_THINKING_BUDGET_TOKENS: Optional[int] = None
BASE_URL_OVERRIDE: Optional[str] = None
MAX_OUTPUT_TOKENS = 8192
DEFAULT_TIMEOUT_SECONDS = 300
PINNED_LEXICON_COMMIT = "8dfb02ef0188e0c7fea55ca38d702c21d75f9691"
QWEN_MODEL_ID = "Qwen/Qwen3.5-4B"
QWEN_MODEL_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
DEFAULT_LOCAL_MODEL_PATH = DYNAPLAN_ROOT / "models" / "Qwen3.5-4B"
LOCAL_MODEL_PATH = DEFAULT_LOCAL_MODEL_PATH
LOCAL_MODEL_REVISION = QWEN_MODEL_REVISION
LOCAL_ENABLE_THINKING = True
LOCAL_SEED = 0

LITERATURE_BASELINES = (
    "adaplan-h",
    "tdp",
    "adapt",
    "reactree",
    "aot-plus",
    "llm-p",
)
DYNAPLAN_BASELINE = "dynaplan"
BASELINES = ("base", DYNAPLAN_BASELINE, *LITERATURE_BASELINES)
BASELINE_DISPLAY_NAMES = {
    "base": "Base model",
    "dynaplan": "DynaPlan",
    "adaplan-h": "AdaPlan-H",
    "tdp": "TDP",
    "adapt": "ADaPT",
    "reactree": "ReAcTree",
    "aot-plus": "AoT+",
    "llm-p": "LLM+P",
}
EXPECTED_ARCHITECTURES: Dict[str, Dict[str, str]] = {
    "logistics": {
        "adaplan-h": "baseline_adaplan_h_v1",
        "tdp": "baseline_tdp_v1",
        "adapt": "adapt_lexicon_v3_verified_subgoals",
        "reactree": "reactree_lexicon_v3",
        "aot-plus": "baseline_aot_plus_v1",
        "llm-p": "baseline_llm_p_v1",
    },
    "blocksworld": {
        "adaplan-h": "baseline_adaplan_h_blocksworld_v1",
        "tdp": "tdp_lexicon_blocksworld_v1",
        "adapt": "adapt_lexicon_blocksworld_v2_verified_subgoals",
        "reactree": "reactree_lexicon_blocksworld_v2",
        "aot-plus": "baseline_aot_plus_blocksworld_v1",
        "llm-p": "baseline_llm_p_blocksworld_v1",
    },
    "flat-hanoi": {
        baseline: (
            "reactree_flat_hanoi_v2"
            if baseline == "reactree"
            else "adapt_flat_hanoi_v2_verified_subgoals"
            if baseline == "adapt"
            else f"{baseline.replace('-', '_')}_flat_hanoi_v1"
        )
        for baseline in LITERATURE_BASELINES
    },
}
CORE_STAGE_REQUIREMENTS: Dict[str, Tuple[str, ...]] = {
    "adaplan-h": ("adaplan_h_metaplan", "adaplan_h_actor"),
    "tdp": ("tdp_supervisor_construct", "tdp_node_planner"),
    "adapt": ("adapt_executor",),
    "reactree": ("reactree_agent",),
    "aot-plus": ("aot_plus_search",),
    "llm-p": ("llm_p_formalize",),
}
BASELINE_CLONE_SPECS: Dict[str, Optional[Dict[str, str]]] = {
    "adaplan-h": {
        "directory": "AdaPlan-H",
        "repository": "https://github.com/import-myself/AHP.git",
        "commit": "da700dfa2695312275dc61d86fd5ba74805fe4f5",
    },
    "tdp": None,
    "adapt": {
        "directory": "ADaPT",
        "repository": "https://github.com/archiki/ADaPT.git",
        "commit": "ecdc4ab0030b4be9be122622d8ea78f8c59c44c4",
    },
    "reactree": {
        "directory": "ReAcTree",
        "repository": "https://github.com/Choi-JaeWoo/ReAcTree.git",
        "commit": "88b737f1eb8f2b68d3b01bdb7ad46e4c00b3ff3b",
    },
    "aot-plus": {
        "directory": "AoT-plus",
        "repository": "https://github.com/llmsresearch/aot-plus.git",
        "commit": "0e95940db127c7c35d6e8805a2f614b665ea6e37",
    },
    "llm-p": {
        "directory": "LLM-P",
        "repository": "https://github.com/Cranial-XIX/llm-pddl.git",
        "commit": "f5f897ccabfb19d5158e5a7ac4cb36517cd4c2e0",
    },
}
BENCHMARKS = ("logistics", "blocksworld", "flat-hanoi")
LEXICON_DOMAINS = ("logistics", "blocksworld")
LEXICON_CONSTRAINT_LEVELS = (1, 3, 5, 7, 10)
LEXICON_PACKED_IDS = tuple(range(1, 31))
REACTREE_UPSTREAM_DEFAULTS = {
    "max_depth": 20,
    "max_steps": 49,
    "max_decisions": 99,
}

_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ACTION_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class RunnerError(RuntimeError):
    """A configuration, source, API, or response error."""


@dataclasses.dataclass(frozen=True)
class PreparedCase:
    benchmark: str
    task_id: str
    display_coordinate: str
    system_prompt: str
    user_prompt: str
    optimum: int
    metadata: Dict[str, Any]
    scorer: Callable[[str], Dict[str, Any]]


@dataclasses.dataclass(frozen=True)
class ModelResponse:
    text: str
    finish_reason: Optional[str]
    response_id: Optional[str]
    request_id: Optional[str]
    returned_model: Optional[str]
    usage: Dict[str, int]
    raw_usage: Dict[str, Any]
    reasoning_char_count: int
    runtime_seconds: float
    backend_metadata: Optional[Dict[str, Any]] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(str(temporary), str(path))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(str(temporary), str(path))


def load_env_file(path: Path) -> None:
    """Load a basic dotenv file without printing values.

    The explicitly selected file is authoritative.  In particular, its key and
    endpoint travel as a pair instead of allowing an unrelated ambient
    ``OPENAI_BASE_URL`` to redirect the credential.
    """

    if not path.is_file():
        raise RunnerError(f"Environment file does not exist: {path}")
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise RunnerError(f"Malformed dotenv entry at {path}:{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not _ENV_KEY.fullmatch(key):
            raise RunnerError(f"Invalid dotenv key at {path}:{line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _chat_completions_endpoint(raw_url: str) -> str:
    """Accept either a full Chat Completions endpoint or an OpenAI ``/v1`` root."""

    value = raw_url.strip()
    if not value:
        return "https://api.openai.com/v1/chat/completions"
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RunnerError("OPENAI_BASE_URL must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RunnerError(
            "OPENAI_BASE_URL must use HTTPS (plain HTTP is allowed only on loopback)"
        )
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        return value
    if path.endswith("/v1"):
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, path + "/chat/completions", parsed.query, "")
        )
    raise RunnerError(
        "OPENAI_BASE_URL must end in /v1 or /v1/chat/completions for this runner"
    )


def _int_value(*values: Any) -> int:
    for value in values:
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _normalize_usage(raw: Any) -> Tuple[Dict[str, int], Dict[str, Any]]:
    raw_usage = dict(raw) if isinstance(raw, Mapping) else {}
    prompt_details = raw_usage.get("prompt_tokens_details") or raw_usage.get(
        "input_tokens_details"
    )
    completion_details = raw_usage.get("completion_tokens_details") or raw_usage.get(
        "output_tokens_details"
    )
    if not isinstance(prompt_details, Mapping):
        prompt_details = {}
    if not isinstance(completion_details, Mapping):
        completion_details = {}
    input_tokens = _int_value(
        raw_usage.get("prompt_tokens"), raw_usage.get("input_tokens")
    )
    output_tokens = _int_value(
        raw_usage.get("completion_tokens"), raw_usage.get("output_tokens")
    )
    cached_input_tokens = _int_value(
        prompt_details.get("cached_tokens"), prompt_details.get("cache_read_tokens")
    )
    usage = {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": max(0, input_tokens - cached_input_tokens),
        "output_tokens": output_tokens,
        "reasoning_tokens": _int_value(
            raw_usage.get("reasoning_tokens"),
            completion_details.get("reasoning_tokens"),
        ),
        "total_tokens": _int_value(
            raw_usage.get("total_tokens"), input_tokens + output_tokens
        ),
    }
    return usage, raw_usage


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: List[str] = []
        for item in content:
            if isinstance(item, str):
                pieces.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("text"), str):
                pieces.append(str(item["text"]))
        return "".join(pieces)
    return ""


def call_openai(
    *,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    timeout_seconds: int,
) -> ModelResponse:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RunnerError("OPENAI_API_KEY is missing or empty")
    endpoint = _chat_completions_endpoint(
        BASE_URL_OVERRIDE
        or os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"
        )
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_completion_tokens": max_output_tokens,
        "reasoning_effort": REASONING_EFFORT,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "dynaplan-benchmark/1.0",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
            request_id = response.headers.get("x-request-id")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")[:4000]
        body = body.replace(api_key, "[REDACTED]")
        raise RunnerError(f"OpenAI HTTP {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise RunnerError(f"OpenAI request failed: {error.reason}") from error
    except TimeoutError as error:
        raise RunnerError(f"OpenAI request timed out after {timeout_seconds}s") from error
    runtime_seconds = time.perf_counter() - started
    try:
        decoded = json.loads(response_body)
        choice = decoded["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise RunnerError("OpenAI returned a malformed Chat Completions response") from error
    usage, raw_usage = _normalize_usage(decoded.get("usage"))
    reasoning_content = message.get("reasoning_content") or message.get("reasoning")
    return ModelResponse(
        text=_message_text(message.get("content")),
        finish_reason=(
            str(choice.get("finish_reason"))
            if choice.get("finish_reason") is not None
            else None
        ),
        response_id=(str(decoded.get("id")) if decoded.get("id") else None),
        request_id=request_id,
        returned_model=(str(decoded.get("model")) if decoded.get("model") else None),
        usage=usage,
        raw_usage=raw_usage,
        reasoning_char_count=(
            len(reasoning_content) if isinstance(reasoning_content, str) else 0
        ),
        runtime_seconds=runtime_seconds,
    )


def _anthropic_messages_endpoint(raw_url: str) -> str:
    """Validate an Anthropic Messages endpoint without logging credentials."""

    value = raw_url.strip() or "https://api.anthropic.com/v1/messages"
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RunnerError("ANTHROPIC_BASE_URL must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RunnerError(
            "ANTHROPIC_BASE_URL must use HTTPS (plain HTTP is allowed only on loopback)"
        )
    path = parsed.path.rstrip("/")
    if path.endswith("/v1/messages"):
        return value
    if not path:
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, "/v1/messages", parsed.query, "")
        )
    raise RunnerError("ANTHROPIC_BASE_URL must end in /v1/messages")


def _normalize_anthropic_usage(raw: Any) -> Tuple[Dict[str, int], Dict[str, Any]]:
    raw_usage = dict(raw) if isinstance(raw, Mapping) else {}
    cache_creation = _int_value(raw_usage.get("cache_creation_input_tokens"))
    cache_read = _int_value(raw_usage.get("cache_read_input_tokens"))
    ordinary_input = _int_value(raw_usage.get("input_tokens"))
    input_tokens = ordinary_input + cache_creation + cache_read
    output_tokens = _int_value(raw_usage.get("output_tokens"))
    output_details = raw_usage.get("output_tokens_details")
    if not isinstance(output_details, Mapping):
        output_details = {}
    usage = {
        "input_tokens": input_tokens,
        "cached_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
        "uncached_input_tokens": ordinary_input,
        "output_tokens": output_tokens,
        "reasoning_tokens": _int_value(
            output_details.get("thinking_tokens"), raw_usage.get("reasoning_tokens")
        ),
        "total_tokens": input_tokens + output_tokens,
    }
    return usage, raw_usage


def _estimated_cost_usd(
    provider: str, model: str, raw_usage: Mapping[str, Any]
) -> Optional[float]:
    """Reconstruct standard API cost from a frozen pricing snapshot.

    Haiku 4.5 prices are USD per million tokens: $1 ordinary input,
    $1.25 5-minute cache creation, $0.10 cache read, and $5 output.
    Extended-thinking tokens are already included in Anthropic output tokens.
    """

    if provider == "local-transformers":
        return 0.0
    if provider != "anthropic" or not model.startswith("claude-haiku-4-5"):
        return None
    ordinary_input = _int_value(raw_usage.get("input_tokens"))
    cache_creation = _int_value(raw_usage.get("cache_creation_input_tokens"))
    cache_read = _int_value(raw_usage.get("cache_read_input_tokens"))
    output = _int_value(raw_usage.get("output_tokens"))
    cost = (
        ordinary_input * 1.00
        + cache_creation * 1.25
        + cache_read * 0.10
        + output * 5.00
    ) / 1_000_000
    return round(cost, 8)


def call_anthropic(
    *,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    timeout_seconds: int,
) -> ModelResponse:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RunnerError("ANTHROPIC_API_KEY is missing or empty")
    endpoint = _anthropic_messages_endpoint(
        BASE_URL_OVERRIDE
        or os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages")
    )
    payload: Dict[str, Any] = {
        "model": MODEL,
        "max_tokens": max_output_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    if ANTHROPIC_THINKING_BUDGET_TOKENS is not None:
        payload["thinking"] = {
            "type": "enabled",
            "budget_tokens": ANTHROPIC_THINKING_BUDGET_TOKENS,
        }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "User-Agent": "dynaplan-benchmark/1.0",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
            request_id = response.headers.get("request-id")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")[:4000]
        body = body.replace(api_key, "[REDACTED]")
        raise RunnerError(f"Anthropic HTTP {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise RunnerError(f"Anthropic request failed: {error.reason}") from error
    except TimeoutError as error:
        raise RunnerError(
            f"Anthropic request timed out after {timeout_seconds}s"
        ) from error
    runtime_seconds = time.perf_counter() - started
    try:
        decoded = json.loads(response_body)
        content = decoded["content"]
        if not isinstance(content, list):
            raise TypeError("content is not a list")
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RunnerError("Anthropic returned a malformed Messages response") from error
    text = "".join(
        str(part.get("text", ""))
        for part in content
        if isinstance(part, Mapping) and part.get("type") == "text"
    )
    reasoning_char_count = sum(
        len(str(part.get("thinking", "")))
        for part in content
        if isinstance(part, Mapping) and part.get("type") == "thinking"
    )
    usage, raw_usage = _normalize_anthropic_usage(decoded.get("usage"))
    return ModelResponse(
        text=text,
        finish_reason=(
            str(decoded.get("stop_reason"))
            if decoded.get("stop_reason") is not None
            else None
        ),
        response_id=(str(decoded.get("id")) if decoded.get("id") else None),
        request_id=request_id,
        returned_model=(str(decoded.get("model")) if decoded.get("model") else None),
        usage=usage,
        raw_usage=raw_usage,
        reasoning_char_count=reasoning_char_count,
        runtime_seconds=runtime_seconds,
    )


def call_model(
    *,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    timeout_seconds: int,
) -> ModelResponse:
    if PROVIDER == "openai":
        return call_openai(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
    if PROVIDER == "anthropic":
        return call_anthropic(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
    if PROVIDER == "local-transformers":
        client = _shared_model_client()
        started = time.perf_counter()
        truncated = False
        try:
            output = client.generate(
                system=system_prompt,
                prompt=user_prompt,
                max_tokens=max_output_tokens,
            )
        except Exception as error:
            # A completed local generation that hit its token ceiling is still
            # a model response, not a transport failure. Preserve it for the
            # same truncation accounting used by hosted providers.
            records = list(client.call_records_since(0))
            if not records or not bool(records[-1].get("truncated")):
                raise
            output = getattr(error, "output", "")
            if not isinstance(output, str):
                output = ""
            truncated = True
        runtime_seconds = time.perf_counter() - started
        records = list(client.call_records_since(0))
        if len(records) != 1:
            raise RunnerError(
                "Local direct baseline must record exactly one model call; "
                f"found {len(records)}"
            )
        record = records[0]
        usage_value = record.get("usage")
        raw_usage_value = record.get("raw_usage")
        usage = dict(usage_value) if isinstance(usage_value, Mapping) else {}
        raw_usage = (
            dict(raw_usage_value) if isinstance(raw_usage_value, Mapping) else {}
        )
        return ModelResponse(
            text=output,
            finish_reason="length" if truncated else "stop",
            response_id=None,
            request_id=None,
            returned_model=MODEL,
            usage={
                "input_tokens": _int_value(usage.get("input_tokens")),
                "cached_input_tokens": _int_value(
                    usage.get("cached_input_tokens")
                ),
                "uncached_input_tokens": _int_value(
                    usage.get("uncached_input_tokens"),
                    usage.get("input_tokens"),
                ),
                "output_tokens": _int_value(usage.get("output_tokens")),
                "reasoning_tokens": _int_value(usage.get("reasoning_tokens")),
                "total_tokens": _int_value(usage.get("total_tokens")),
            },
            raw_usage=raw_usage,
            reasoning_char_count=_int_value(record.get("reasoning_char_count")),
            runtime_seconds=runtime_seconds,
            backend_metadata=(
                dict(record["backend_metadata"])
                if isinstance(record.get("backend_metadata"), Mapping)
                else None
            ),
        )
    raise RunnerError(f"Unsupported provider: {PROVIDER}")


def _git(root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise RunnerError(f"git {' '.join(arguments)} failed for {root}: {detail}")
    return process.stdout.strip()


def _validate_lexicon_checkout() -> Dict[str, Any]:
    if not LEXICON_ROOT.is_dir():
        raise RunnerError(f"Official LexiCon checkout not found: {LEXICON_ROOT}")
    commit = _git(LEXICON_ROOT, "rev-parse", "HEAD")
    if commit != PINNED_LEXICON_COMMIT:
        raise RunnerError(
            "LexiCon checkout revision changed: "
            f"expected {PINNED_LEXICON_COMMIT}, found {commit}"
        )
    tracked_status = _git(
        LEXICON_ROOT, "status", "--porcelain", "--untracked-files=no"
    )
    status_lines = [line for line in tracked_status.splitlines() if line]
    ignored_generated_files: List[str] = []
    meaningful_changes: List[str] = []
    for status_line in status_lines:
        path = status_line[3:] if len(status_line) > 3 else status_line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.endswith(".pyc") and (
            path.startswith("__pycache__/") or "/__pycache__/" in path
        ):
            # The released repository tracks generated CPython bytecode. Merely
            # importing upstream modules can update those files. They are never
            # treated as source provenance; all executable source remains pinned.
            ignored_generated_files.append(path)
        else:
            meaningful_changes.append(status_line)
    if meaningful_changes:
        raise RunnerError(
            "LexiCon checkout contains modified tracked source/artifact files: "
            + "; ".join(meaningful_changes)
        )
    return {
        "repository": _git(LEXICON_ROOT, "config", "--get", "remote.origin.url"),
        "commit": commit,
        "tracked_checkout_dirty": bool(status_lines),
        "tracked_source_checkout_dirty": False,
        "ignored_tracked_generated_files": ignored_generated_files,
    }


def _require_unified_planning() -> Tuple[Any, Any, Any]:
    try:
        from unified_planning.io import PDDLReader
        from unified_planning.plans import ActionInstance
        from unified_planning.shortcuts import SequentialSimulator
    except ImportError as error:
        suggested = (
            DYNAPLAN_ROOT.parent
            / "simmer-style-libero"
            / ".venv"
            / "bin"
            / "python"
        )
        raise RunnerError(
            "LexiCon scoring requires unified-planning. Run this script with "
            f"{suggested} or install the LexiCon dependencies."
        ) from error
    return PDDLReader, ActionInstance, SequentialSimulator


def _load_mapper_class(domain: str) -> Any:
    class_names = {
        "logistics": "LogisticsMapper",
        "blocksworld": "BlocksworldMapper",
    }
    base_path = LEXICON_ROOT / "base_mapper.py"
    mapper_path = LEXICON_ROOT / "domains" / domain / "mapper.py"
    if not base_path.is_file() or not mapper_path.is_file():
        raise RunnerError(f"LexiCon mapper source is missing for {domain}")

    base_module = types.ModuleType("_dynaplan_lexicon_base_mapper")
    base_module.__file__ = str(base_path)
    exec(compile(base_path.read_bytes(), str(base_path), "exec"), base_module.__dict__)

    mapper_module = types.ModuleType(f"_dynaplan_lexicon_{domain}_mapper")
    mapper_module.__file__ = str(mapper_path)
    missing = object()
    prior = sys.modules.get("base_mapper", missing)
    sys.modules["base_mapper"] = base_module
    try:
        exec(
            compile(mapper_path.read_bytes(), str(mapper_path), "exec"),
            mapper_module.__dict__,
        )
    finally:
        if prior is missing:
            sys.modules.pop("base_mapper", None)
        else:
            sys.modules["base_mapper"] = prior
    mapper_class = getattr(mapper_module, class_names[domain], None)
    if mapper_class is None:
        raise RunnerError(f"LexiCon mapper class is missing for {domain}")
    return mapper_class


def _source_hashes(paths: Iterable[Path]) -> Dict[str, str]:
    return {path.name: _sha256_bytes(path.read_bytes()) for path in paths}


def _extract_official_lexicon_block(text: str) -> Tuple[str, Dict[str, Any]]:
    """Extract the first fenced block using LexiCon's released convention.

    The upstream parser ignores content before the first line containing a
    triple-backtick delimiter and stops at the next such line.  We preserve
    that semantic extraction rule while independently recording whether the
    response obeyed the prompt's stricter, bare-fence-only output contract.
    """

    if not isinstance(text, str) or not text.strip():
        raise RunnerError("Plan output is empty")
    lines = text.splitlines()
    opening_index = next(
        (index for index, line in enumerate(lines) if "```" in line), None
    )
    if opening_index is None:
        raise RunnerError("Plan output does not contain a fenced action block")
    closing_index = next(
        (
            index
            for index in range(opening_index + 1, len(lines))
            if "```" in lines[index]
        ),
        None,
    )
    # The released LexiCon parser consumes through EOF when the model omits the
    # closing delimiter.  Preserve that semantic behavior, but flag the missing
    # delimiter in the independent exact-format diagnostic below.
    body_end = closing_index if closing_index is not None else len(lines)
    body = "\n".join(lines[opening_index + 1 : body_end])
    delimiter_count = sum("```" in line for line in lines)
    format_issues: List[str] = []
    if any(line.strip() for line in lines[:opening_index]):
        format_issues.append("prose_before_plan")
    if closing_index is not None and any(
        line.strip() for line in lines[closing_index + 1 :]
    ):
        format_issues.append("prose_after_plan")
    if lines[opening_index] != "```":
        format_issues.append("opening_fence_not_bare")
    if closing_index is None:
        format_issues.append("missing_closing_fence")
    elif lines[closing_index] != "```":
        format_issues.append("closing_fence_not_bare")
    if delimiter_count != 2:
        format_issues.append("additional_fence_delimiters")
    format_adherent = not format_issues
    return body, {
        "format_adherent": format_adherent,
        "format_issues": [] if format_adherent else format_issues,
        "plan_extraction": "official_first_fenced_block",
        "opening_fence_line": opening_index + 1,
        "closing_fence_line": (
            closing_index + 1 if closing_index is not None else None
        ),
        "fence_delimiter_count": delimiter_count,
    }


def _parse_lexicon_action_body(body: str) -> List[Tuple[str, Tuple[str, ...]]]:
    lines = body.splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise RunnerError("Plan must contain non-empty action lines only")
    parsed: List[Tuple[str, Tuple[str, ...]]] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if line.startswith("(") and line.endswith(")"):
            line = line[1:-1].strip()
        tokens = line.split()
        if not tokens or any(_ACTION_TOKEN.fullmatch(token) is None for token in tokens):
            raise RunnerError(
                f"Line {line_number} is not a clean grounded action: {raw_line!r}"
            )
        parsed.append((tokens[0], tuple(tokens[1:])))
    return parsed


def _parse_lexicon_response_with_format(
    text: str,
) -> Tuple[List[Tuple[str, Tuple[str, ...]]], Dict[str, Any]]:
    body, format_metadata = _extract_official_lexicon_block(text)
    return _parse_lexicon_action_body(body), format_metadata


def _parse_lexicon_response(text: str) -> List[Tuple[str, Tuple[str, ...]]]:
    """Compatibility wrapper returning only the officially extracted actions."""

    actions, _format_metadata = _parse_lexicon_response_with_format(text)
    return actions


def _lexicon_invalid(
    *,
    optimum: int,
    submitted_length: int,
    failure_kind: str,
    failure_message: str,
    candidate_plan: Optional[Sequence[str]] = None,
    first_failed_action_index: Optional[int] = None,
    unsatisfied_preconditions: Optional[Sequence[str]] = None,
    unsatisfied_goals: Optional[Sequence[str]] = None,
    format_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "status": "INVALID",
        "success": False,
        "valid": False,
        "optimal": False,
        "submitted_length": submitted_length,
        "optimal_length": optimum,
        "cost_delta": None,
        "candidate_plan": list(candidate_plan or []),
        "failure_kind": failure_kind,
        "failure_message": failure_message,
        "first_failed_action_index": first_failed_action_index,
        "unsatisfied_preconditions": list(unsatisfied_preconditions or []),
        "unsatisfied_goals": list(unsatisfied_goals or []),
        **dict(format_metadata or {}),
    }


def _make_lexicon_scorer(
    compiled_domain: Path, compiled_problem: Path, optimum: int
) -> Callable[[str], Dict[str, Any]]:
    def score(response_text: str) -> Dict[str, Any]:
        format_metadata: Dict[str, Any] = {
            "format_adherent": False,
            "format_issues": ["unparseable_response_envelope"],
            "plan_extraction": "official_first_fenced_block",
        }
        try:
            body, format_metadata = _extract_official_lexicon_block(response_text)
        except RunnerError as error:
            return _lexicon_invalid(
                optimum=optimum,
                submitted_length=0,
                failure_kind="plan_format",
                failure_message=str(error),
                format_metadata=format_metadata,
            )
        try:
            actions = _parse_lexicon_action_body(body)
        except RunnerError as error:
            return _lexicon_invalid(
                optimum=optimum,
                submitted_length=0,
                failure_kind="plan_format",
                failure_message=str(error),
                format_metadata=format_metadata,
            )
        candidate_plan = ["(" + " ".join((name, *args)) + ")" for name, args in actions]
        PDDLReader, ActionInstance, SequentialSimulator = _require_unified_planning()
        reader = PDDLReader()
        try:
            problem = reader.parse_problem(str(compiled_domain), str(compiled_problem))
        except Exception as error:
            raise RunnerError(f"Could not parse the compiled LexiCon problem: {error}") from error

        bound_actions = []
        for index, (name, arguments) in enumerate(actions, start=1):
            try:
                declaration = problem.action(name)
                if len(arguments) != len(declaration.parameters):
                    raise ValueError(
                        f"{name} has {len(arguments)} arguments; "
                        f"expected {len(declaration.parameters)}"
                    )
                manager = problem.environment.expression_manager
                parameters = tuple(
                    manager.ObjectExp(problem.object(argument)) for argument in arguments
                )
                bound_actions.append(ActionInstance(declaration, parameters))
            except Exception as error:
                return _lexicon_invalid(
                    optimum=optimum,
                    submitted_length=len(actions),
                    failure_kind="action_binding",
                    failure_message=str(error),
                    candidate_plan=candidate_plan,
                    first_failed_action_index=index,
                    format_metadata=format_metadata,
                )

        with SequentialSimulator(problem) as simulator:
            state = simulator.get_initial_state()
            for index, ((name, arguments), action) in enumerate(
                zip(actions, bound_actions), start=1
            ):
                try:
                    if not simulator.is_applicable(state, action):
                        conditions, reason = simulator.get_unsatisfied_conditions(state, action)
                        unsatisfied = [str(condition) for condition in conditions]
                        message = (
                            "Action is inapplicable: "
                            + "(" + " ".join((name, *arguments)) + ")"
                        )
                        if unsatisfied:
                            message += f"; unsatisfied {unsatisfied}"
                        if reason is not None:
                            message += f" ({reason})"
                        return _lexicon_invalid(
                            optimum=optimum,
                            submitted_length=len(actions),
                            failure_kind="action_precondition",
                            failure_message=message,
                            candidate_plan=candidate_plan,
                            first_failed_action_index=index,
                            unsatisfied_preconditions=unsatisfied,
                            format_metadata=format_metadata,
                        )
                    next_state = simulator.apply(state, action)
                    if next_state is None:
                        raise RuntimeError("simulator returned no successor state")
                    state = next_state
                except Exception as error:
                    return _lexicon_invalid(
                        optimum=optimum,
                        submitted_length=len(actions),
                        failure_kind="simulation",
                        failure_message=str(error),
                        candidate_plan=candidate_plan,
                        first_failed_action_index=index,
                        format_metadata=format_metadata,
                    )
            unsatisfied_goals = [
                str(goal) for goal in simulator.get_unsatisfied_goals(state)
            ]
            if unsatisfied_goals:
                return _lexicon_invalid(
                    optimum=optimum,
                    submitted_length=len(actions),
                    failure_kind="unsatisfied_goals",
                    failure_message="Final state does not satisfy the compiled problem goals",
                    candidate_plan=candidate_plan,
                    unsatisfied_goals=unsatisfied_goals,
                    format_metadata=format_metadata,
                )

        optimal = len(actions) <= optimum
        return {
            "status": "OPTIMAL" if optimal else "SUBOPTIMAL",
            "success": True,
            "valid": True,
            "optimal": optimal,
            "submitted_length": len(actions),
            "optimal_length": optimum,
            "cost_delta": len(actions) - optimum,
            "candidate_plan": candidate_plan,
            "failure_kind": None,
            "failure_message": None,
            "first_failed_action_index": None,
            "unsatisfied_preconditions": [],
            "unsatisfied_goals": [],
            **format_metadata,
        }

    return score


def prepare_lexicon_case(domain: str, constraint_count: int, packed_id: int) -> PreparedCase:
    if domain not in LEXICON_DOMAINS:
        raise RunnerError(f"Unsupported LexiCon domain: {domain}")
    if constraint_count not in LEXICON_CONSTRAINT_LEVELS:
        raise RunnerError(
            f"LexiCon c must be one of {LEXICON_CONSTRAINT_LEVELS}, got {constraint_count}"
        )
    if packed_id not in LEXICON_PACKED_IDS:
        raise RunnerError("LexiCon packed ID must be between 1 and 30")
    checkout = _validate_lexicon_checkout()
    task_dir = (
        LEXICON_ROOT
        / "domains"
        / domain
        / "data"
        / f"data_{constraint_count}"
        / str(packed_id)
    )
    required_names = (
        "domain.pddl",
        "problem.pddl",
        "compiled_domain.pddl",
        "compiled_problem.pddl",
        "constrained_plan",
    )
    required = [task_dir / name for name in required_names]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise RunnerError(f"LexiCon task {domain} c={constraint_count}/{packed_id} is missing {missing}")

    PDDLReader, _ActionInstance, _SequentialSimulator = _require_unified_planning()
    reader = PDDLReader()
    try:
        original_problem = reader.parse_problem(
            str(task_dir / "domain.pddl"), str(task_dir / "problem.pddl")
        )
        compiled_problem = reader.parse_problem(
            str(task_dir / "compiled_domain.pddl"),
            str(task_dir / "compiled_problem.pddl"),
        )
        oracle_plan = reader.parse_plan(compiled_problem, str(task_dir / "constrained_plan"))
    except Exception as error:
        raise RunnerError(f"Could not load LexiCon task {domain} c={constraint_count}/{packed_id}: {error}") from error

    mapper = _load_mapper_class(domain)(original_problem)
    try:
        system_prompt, domain_nl, problem_nl = mapper.get_problem_nl()
    except Exception as error:
        raise RunnerError(f"Official LexiCon mapper failed for {domain}: {error}") from error
    _ensure_shared_adapter_root()
    from comparison_protocol import (
        COMPARISON_PROMPT_PROTOCOL_VERSION,
        MINIMUM_ACTION_OBJECTIVE,
        common_semantics_contract,
        with_comparison_contract,
    )

    user_prompt = with_comparison_contract(domain_nl + problem_nl, domain)
    if not all(isinstance(value, str) for value in (system_prompt, user_prompt)):
        raise RunnerError("Official LexiCon mapper returned non-text prompts")
    optimum = len(oracle_plan.actions)
    task_id = f"lexicon-{domain}-c{constraint_count}-id{packed_id}"
    metadata = {
        "suite": "LexiCon",
        "domain": domain,
        "nominal_constraint_count": constraint_count,
        "actual_constraint_count": len(original_problem.trajectory_constraints),
        "packed_id": packed_id,
        "prompt_source": "official-live-mapper-plus-shared-objective",
        "upstream_prompt_source": "official-live-mapper",
        "comparison_prompt_protocol": COMPARISON_PROMPT_PROTOCOL_VERSION,
        "comparison_semantics_sha256": _sha256_text(
            common_semantics_contract(domain)
        ),
        "minimum_action_objective": MINIMUM_ACTION_OBJECTIVE,
        "minimum_action_objective_location": "public user task suffix",
        "evaluation_protocol": "official-first-fence-strict-actions-compiled-pddl-v2",
        "upstream_fuzzy_action_repair_enabled": False,
        "evaluation_protocol_note": (
            "Uses a released-parser-compatible first-fenced-block extraction "
            "for ordinary response envelopes, compiled-PDDL "
            "semantics, and oracle-length rule. Exact prompt-format adherence "
            "is recorded separately. Malformed actions remain strict: the "
            "optional verification path's edit-distance grounded-action fallback "
            "is intentionally disabled, matching the released aggregate-metrics "
            "path's exact-action setting."
        ),
        "source": checkout,
        "source_files": _source_hashes(required),
    }
    return PreparedCase(
        benchmark=domain,
        task_id=task_id,
        display_coordinate=f"c={constraint_count}, id={packed_id}",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        optimum=optimum,
        metadata=metadata,
        scorer=_make_lexicon_scorer(
            task_dir / "compiled_domain.pddl",
            task_dir / "compiled_problem.pddl",
            optimum,
        ),
    )


def _load_flat_hanoi_modules() -> Tuple[Any, Any, Any, Any]:
    if not FLAT_HANOI_ROOT.is_dir():
        raise RunnerError(f"Flat-Hanoi benchmark not found: {FLAT_HANOI_ROOT}")
    root_text = str(FLAT_HANOI_ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        from flat_hanoi.evaluate import evaluate_response
        from flat_hanoi.io import read_instances, validate_dataset
        from flat_hanoi.oracle import shortest_path
        from flat_hanoi.prompt import render_messages
    except ImportError as error:
        raise RunnerError(f"Could not import the Flat-Hanoi benchmark: {error}") from error
    return read_instances, validate_dataset, render_messages, (evaluate_response, shortest_path)


def _resolve_hanoi_alias(requested: str) -> Tuple[str, int]:
    value = requested.strip()
    short = re.fullmatch(r"n(?P<n>[3-7])-(?P<index>\d{4})", value)
    reversed_short = re.fullmatch(
        r"(?P<n>[3-7])n-(?P<index>\d{4})", value
    )
    if short or reversed_short:
        match = short or reversed_short
        assert match is not None
        n = int(match.group("n"))
        index = int(match.group("index"))
        profile = "paper-baseline-v1" if n <= 5 else "paper-extension-v1"
        return f"{profile}-n{n}-{index:04d}", n
    alias = re.fullmatch(r"(?P<n>[3-7])_(?P<index>\d{2})", value)
    if alias:
        n = int(alias.group("n"))
        index = int(alias.group("index"))
        profile = "paper-baseline-v1" if n <= 5 else "paper-extension-v1"
        return f"{profile}-n{n}-{index:04d}", n
    canonical = re.fullmatch(
        r"paper-(?:baseline|extension)-v1-n(?P<n>[3-7])-(?P<index>\d{4})",
        value,
    )
    if canonical:
        return value, int(canonical.group("n"))
    raise RunnerError(
        "Flat-Hanoi task must be an alias like n3-0017, 3n-0017, 3_00, "
        "or a canonical paper-* instance ID"
    )


def _flat_task_from_instance(
    instance: Any, task_id: str, display_coordinate: str
) -> Any:
    """Build the shared named-action view of one frozen numeric instance."""

    _ensure_shared_adapter_root()
    try:
        from flat_hanoi_task_loader import FlatHanoiTask, validate_task
        from task_loader import Ring
    except ImportError as error:
        raise RunnerError(
            f"Could not import Flat-Hanoi baseline boundary: {error}"
        ) from error
    pegs = ["peg_0", "peg_1", "peg_2"]

    def stacks(state: Sequence[int]) -> Dict[str, List[str]]:
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
        name=f"Paper-derived Flat-Hanoi {display_coordinate}",
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


def prepare_flat_hanoi_case(requested_task: str) -> PreparedCase:
    instance_id, n = _resolve_hanoi_alias(requested_task)
    dataset_name = (
        "paper_baseline_v1.jsonl"
        if n <= 5
        else "paper_extension_n6_n7_v1.jsonl"
    )
    dataset = FLAT_HANOI_ROOT / "flat_hanoi" / "data" / dataset_name
    read_instances, validate_dataset, render_messages, evaluation_tools = _load_flat_hanoi_modules()
    evaluate_response, _shortest_path = evaluation_tools
    manifest = validate_dataset(dataset, check_oracle=True, require_manifest=True)
    instances = {instance.instance_id: instance for instance in read_instances(dataset)}
    instance = instances.get(instance_id)
    if instance is None:
        raise RunnerError(f"Flat-Hanoi instance is not present in {dataset.name}: {instance_id}")
    # Preserve the paper-derived numeric prompt as a reference, but use one
    # named-action comparison contract for every method. Otherwise prompt
    # demonstrations and output syntax are confounded with method.
    reference_messages = render_messages(instance)
    if (
        len(reference_messages) != 2
        or reference_messages[0].get("role") != "system"
        or reference_messages[1].get("role") != "user"
    ):
        raise RunnerError("Flat-Hanoi renderer did not return its required two-role prompt")
    _ensure_shared_adapter_root()
    from comparison_protocol import (
        COMPARISON_PROMPT_PROTOCOL_VERSION,
        FLAT_HANOI_ACTION_REPRESENTATION,
        FLAT_HANOI_DIRECT_SYSTEM_PROMPT,
        FLAT_HANOI_SHARED_SOLVED_EXAMPLE,
        MINIMUM_ACTION_OBJECTIVE,
        common_semantics_contract,
        flat_hanoi_direct_prompt,
    )
    from flat_hanoi_baseline_core import public_problem_text

    comparison_task = _flat_task_from_instance(
        instance, instance_id, requested_task
    )
    comparison_problem = public_problem_text(comparison_task)
    comparison_user_prompt = flat_hanoi_direct_prompt(comparison_problem)

    def score(response_text: str) -> Dict[str, Any]:
        evaluation = evaluate_response(instance, response_text)
        result = evaluation.to_dict()
        result["status"] = str(result["classification"]).upper()
        # In Flat-Hanoi, benchmark-native `valid` is an alias for move legality.
        # Goal-reaching, not legality alone, is the cross-benchmark success field.
        result["success"] = bool(result["goal_reached"])
        result["optimal_length"] = result.pop("optimal_distance")
        result["cost_delta"] = (
            result["submitted_length"] - result["optimal_length"]
            if result["goal_reached"] and result["submitted_length"] is not None
            else None
        )
        return result

    metadata = {
        "suite": "Flat-Hanoi",
        "requested_alias": requested_task,
        "canonical_instance_id": instance_id,
        "n": instance.n,
        "start": list(instance.start),
        "goal": list(instance.goal),
        "sampling_profile": instance.sampling_profile,
        "generator_seed": instance.generator_seed,
        "dataset": dataset.name,
        "dataset_sha256": _sha256_bytes(dataset.read_bytes()),
        "manifest_sha256": _sha256_bytes(dataset.with_suffix(".manifest.json").read_bytes()),
        "manifest": manifest,
        "implementation_sha256": dict(
            manifest.get("benchmark_artifact_hashes", {})
            if isinstance(manifest, Mapping)
            else {}
        ),
        "benchmark_kind": "paper-derived reimplementation; not an official code release",
        "comparison_prompt_protocol": COMPARISON_PROMPT_PROTOCOL_VERSION,
        "comparison_semantics_sha256": _sha256_text(
            common_semantics_contract("flat-hanoi")
        ),
        "minimum_action_objective": MINIMUM_ACTION_OBJECTIVE,
        "flat_hanoi_action_representation": FLAT_HANOI_ACTION_REPRESENTATION,
        "shared_solved_example_sha256": _sha256_text(
            FLAT_HANOI_SHARED_SOLVED_EXAMPLE
        ),
        "paper_derived_reference_prompt": {
            "system_sha256": _sha256_text(reference_messages[0]["content"]),
            "user_sha256": _sha256_text(reference_messages[1]["content"]),
            "system_char_count": len(reference_messages[0]["content"]),
            "user_char_count": len(reference_messages[1]["content"]),
            "role": (
                "frozen reconstruction reference only; the controlled method "
                "comparison uses the shared named-action prompt"
            ),
        },
        "action_adapter": (
            "deterministically infer the current top ring for each MoveHoop "
            "and convert it to [disk_id, source_peg, destination_peg] only for "
            "the frozen evaluator"
        ),
    }
    return PreparedCase(
        benchmark="flat-hanoi",
        task_id=instance_id,
        display_coordinate=requested_task,
        system_prompt=FLAT_HANOI_DIRECT_SYSTEM_PROMPT,
        user_prompt=comparison_user_prompt,
        optimum=instance.optimal_distance,
        metadata=metadata,
        scorer=score,
    )


def prepare_cases(args: argparse.Namespace) -> List[PreparedCase]:
    selected = list(BENCHMARKS) if args.benchmark == "all" else [args.benchmark]
    cases: List[PreparedCase] = []
    for benchmark in selected:
        if benchmark in LEXICON_DOMAINS:
            cases.append(
                prepare_lexicon_case(benchmark, args.constraints, args.lexicon_id)
            )
        elif benchmark == "flat-hanoi":
            cases.append(prepare_flat_hanoi_case(args.hanoi_task))
        else:  # pragma: no cover - argparse closes this branch.
            raise RunnerError(f"Unknown benchmark: {benchmark}")
    return cases


def _prompt_metadata(case: PreparedCase) -> Dict[str, Any]:
    return {
        "system_sha256": _sha256_text(case.system_prompt),
        "user_sha256": _sha256_text(case.user_prompt),
        "system_char_count": len(case.system_prompt),
        "user_char_count": len(case.user_prompt),
        "role_order": ["system", "user"],
    }


def _truncated_evaluation(case: PreparedCase, response: ModelResponse) -> Dict[str, Any]:
    result = {
        "status": "TRUNCATED",
        "success": False,
        "valid": False,
        "optimal": False,
        "submitted_length": None,
        "optimal_length": case.optimum,
        "cost_delta": None,
        "failure_kind": "model_output_truncated",
        "failure_message": (
            f"Provider finish_reason={response.finish_reason!r}; incomplete output was not scored"
        ),
    }
    if case.benchmark in LEXICON_DOMAINS:
        try:
            _body, format_metadata = _extract_official_lexicon_block(response.text)
        except RunnerError:
            format_metadata = {
                "format_adherent": False,
                "format_issues": ["unparseable_response_envelope"],
                "plan_extraction": "official_first_fenced_block",
            }
        result.update(format_metadata)
    return result


def _ensure_shared_adapter_root() -> None:
    if not SHARED_ADAPTER_ROOT.is_dir():
        raise RunnerError(
            "The mechanism-preserving baseline adapters are missing: "
            f"{SHARED_ADAPTER_ROOT}"
        )
    root = str(SHARED_ADAPTER_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _canonical_git_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.lower()


def _baseline_source_status(
    baseline: str, *, require_fast_downward: bool = True
) -> Dict[str, Any]:
    """Verify the reference checkout without claiming that it is run unchanged."""

    if baseline == "base":
        return {
            "baseline": baseline,
            "status": "NOT_APPLICABLE",
            "verified": True,
            "execution_kind": "single direct call implemented by benchmark.py",
        }
    if baseline == DYNAPLAN_BASELINE:
        method_root = BASELINE_CLONES_ROOT / "dynaplan"
        entrypoint = method_root / "benchmark.py"
        framework_path = method_root / "framework.json"
        runtime_files = sorted((method_root / "runtime").glob("*.py"))
        rules_schema = (
            method_root / "runtime" / "n_hirearchy_v5_5" / "rules.schema.json"
        )
        errors = []
        if not entrypoint.is_file():
            errors.append("missing benchmark.py")
        if not framework_path.is_file():
            errors.append("missing framework.json")
        if not runtime_files:
            errors.append("copied runtime is empty")
        if not rules_schema.is_file():
            errors.append("missing copied rule schema")
        framework: Dict[str, Any] = {}
        if framework_path.is_file():
            try:
                loaded = json.loads(framework_path.read_text(encoding="utf-8"))
                framework = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError as error:
                errors.append(f"invalid framework.json: {error}")
        if framework.get("framework_version") != (
            "dynaplan_final_nlevel_hierarchy_v1_1"
        ):
            errors.append("framework version mismatch")
        return {
            "baseline": baseline,
            "status": "VERIFIED" if not errors else "MISMATCH",
            "verified": not errors,
            "method_root": str(method_root),
            "entrypoint": str(entrypoint),
            "framework_manifest": str(framework_path),
            "runtime_file_count": len(runtime_files),
            "runtime_sha256": {
                path.name: _sha256_bytes(path.read_bytes())
                for path in runtime_files
            },
            "errors": errors,
            "execution_kind": (
                "self-contained copied DynaPlan architecture invoked in an "
                "isolated subprocess"
            ),
        }
    spec = BASELINE_CLONE_SPECS[baseline]
    if spec is None:
        placeholder = BASELINE_CLONES_ROOT / "TDP" / "README.md"
        present = placeholder.is_file()
        return {
            "baseline": baseline,
            "status": "PROMPTS_ONLY_NO_PUBLIC_REPOSITORY",
            "verified": present,
            "clone_present": False,
            "placeholder": str(placeholder),
            "placeholder_sha256": (
                _sha256_bytes(placeholder.read_bytes()) if present else None
            ),
            "execution_kind": (
                "authors' published prompts/Algorithm 1 implemented through a "
                "task-domain adapter; no official TDP code repository is public"
            ),
        }
    checkout = BASELINE_CLONES_ROOT / spec["directory"]
    if not (checkout / ".git").is_dir():
        return {
            "baseline": baseline,
            "status": "MISSING_CLONE",
            "verified": False,
            "checkout": str(checkout),
        }
    head = _git(checkout, "rev-parse", "HEAD")
    remote = _git(checkout, "config", "--get", "remote.origin.url")
    dirty = bool(
        _git(checkout, "status", "--porcelain", "--untracked-files=no")
    )
    verified = (
        head == spec["commit"]
        and _canonical_git_url(remote) == _canonical_git_url(spec["repository"])
        and not dirty
    )
    result: Dict[str, Any] = {
        "baseline": baseline,
        "status": "VERIFIED" if verified else "MISMATCH",
        "verified": verified,
        "clone_present": True,
        "checkout": str(checkout),
        "expected_repository": spec["repository"],
        "remote": remote,
        "expected_commit": spec["commit"],
        "commit": head,
        "tracked_checkout_dirty": dirty,
        "execution_kind": (
            "mechanism-preserving, untrained domain adapter; the upstream clone "
            "is pinned reference/provenance and is not executed unchanged"
        ),
    }
    if baseline == "reactree":
        upstream_config_path = checkout / "conf" / "llm_agent" / "default.yaml"
        parsed_defaults: Dict[str, int] = {}
        if upstream_config_path.is_file():
            config_text = upstream_config_path.read_text(encoding="utf-8")
            for name in REACTREE_UPSTREAM_DEFAULTS:
                match = re.search(
                    rf"(?m)^\s*{re.escape(name)}\s*:\s*([0-9]+)\s*$",
                    config_text,
                )
                if match:
                    parsed_defaults[name] = int(match.group(1))
        defaults_match = parsed_defaults == REACTREE_UPSTREAM_DEFAULTS
        result["upstream_default_config_path"] = str(upstream_config_path)
        result["upstream_default_config"] = parsed_defaults
        result["expected_upstream_default_config"] = dict(
            REACTREE_UPSTREAM_DEFAULTS
        )
        result["upstream_default_config_matches"] = defaults_match
        result["depth_semantics"] = (
            "root agent depth 1; expansion adds a control node at +1 and "
            "agent children at +2; pinned max_depth is checked by control nodes"
        )
        result["verified"] = bool(result["verified"] and defaults_match)
        if not result["verified"]:
            result["status"] = "MISMATCH"
    if baseline == "llm-p" and require_fast_downward:
        _ensure_shared_adapter_root()
        try:
            from baselines import llm_p as llm_p_adapter

            planner = llm_p_adapter._find_fast_downward({})
        except Exception as error:
            planner = None
            result["planner_preflight_error"] = f"{type(error).__name__}: {error}"
        result["fast_downward_path"] = str(planner) if planner else None
        result["fast_downward_available"] = bool(planner)
        result["verified"] = bool(result["verified"] and planner)
        if not planner:
            result["status"] = "PLANNER_UNAVAILABLE"
    return result


def _baseline_config(baseline: str) -> Dict[str, Any]:
    if baseline == DYNAPLAN_BASELINE:
        return {
            "fixed_goal": False,
            "max_replans": 15,
            "reuse_h1": True,
            "include_code_block": True,
            "online_semantic_verification": False,
            "official_final_evaluator_calls": 1,
            "decision_checkpoint_tag_normalization": True,
            "shared_hanoi_solved_example": True,
        }
    return {
        "max_depth": 3,
        "max_replans": 1 if baseline == "tdp" else 0,
        "format_retries": 0,
        "tdp_node_replans": 1,
        "outer_retries": 0,
        "max_steps": 64,
        "tdp_max_steps": 64,
        "max_model_calls": 160,
        "adapt_max_replans": 0,
        "adapt_max_nodes": 13,
        "adapt_max_model_calls": 17,
        "adapt_max_subtasks": 3,
        "reactree_max_replans": 0,
        # The pinned ReAcTree checkout uses max_depth=20. Its code applies that
        # limit to control-flow nodes; model calls, decisions, and actions stay
        # independently hard-bounded below.
        "reactree_max_depth": 20,
        "reactree_max_model_calls": 96,
        "reactree_max_decisions": 96,
        "reactree_max_actions": 64,
        "reactree_episodic_top_k": 1,
        "search_width": 3,
        "random_seed": 0,
        "trajectory_depth": 6,
        "memo_interval": 3,
        "planner_timeout": 120,
    }


def _selected_baselines(value: str) -> Tuple[str, ...]:
    if value == "all-literature":
        return LITERATURE_BASELINES
    if value == "all":
        return BASELINES
    if value not in BASELINES:
        raise RunnerError(f"Unknown baseline selection: {value}")
    return (value,)


def _dynaplan_entrypoint() -> Path:
    return BASELINE_CLONES_ROOT / "dynaplan" / "benchmark.py"


def _dynaplan_case_arguments(case: PreparedCase) -> List[str]:
    arguments = [
        "--domain",
        case.benchmark,
    ]
    if case.benchmark == "flat-hanoi":
        arguments.extend(("--task", case.task_id))
    else:
        arguments.extend(
            (
                "--constraints",
                str(case.metadata["nominal_constraint_count"]),
                "--lexicon-id",
                str(case.metadata["packed_id"]),
            )
        )
    return arguments


def _parse_subprocess_json(stdout: str, *, label: str) -> Dict[str, Any]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RunnerError(f"{label} returned no JSON output")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise RunnerError(f"{label} returned malformed JSON") from error
    if not isinstance(payload, dict):
        raise RunnerError(f"{label} returned a non-object JSON payload")
    return payload


def _preflight_baseline(
    baseline: str, cases: Sequence[PreparedCase]
) -> Dict[str, Any]:
    """Load every method/domain boundary without making a model call."""

    source = _baseline_source_status(
        baseline,
        require_fast_downward=any(case.benchmark in LEXICON_DOMAINS for case in cases),
    )
    checks: List[Dict[str, Any]] = []
    errors: List[str] = []
    if not source.get("verified"):
        errors.append(f"source preflight status={source.get('status')}")
    try:
        _ensure_shared_adapter_root()
        if baseline == "base":
            from comparison_protocol import (
                FLAT_HANOI_ACTION_REPRESENTATION,
                FLAT_HANOI_SHARED_SOLVED_EXAMPLE,
                MINIMUM_ACTION_OBJECTIVE,
            )

            for case in cases:
                combined = case.system_prompt + "\n" + case.user_prompt
                if combined.count(MINIMUM_ACTION_OBJECTIVE) != 1:
                    raise RunnerError(
                        f"{case.benchmark} direct prompt does not contain the "
                        "shared minimum-action objective exactly once"
                    )
                if case.benchmark == "flat-hanoi":
                    if case.user_prompt.count(FLAT_HANOI_SHARED_SOLVED_EXAMPLE) != 1:
                        raise RunnerError(
                            "Flat-Hanoi direct prompt does not contain exactly "
                            "one shared solved example"
                        )
                    if FLAT_HANOI_ACTION_REPRESENTATION not in case.user_prompt:
                        raise RunnerError(
                            "Flat-Hanoi direct prompt dropped the shared action "
                            "representation"
                        )
                checks.append(
                    {
                        "component": "direct prompt contract",
                        "benchmark": case.benchmark,
                        "task_id": case.task_id,
                        "status": "PASS",
                    }
                )
        elif baseline == DYNAPLAN_BASELINE:
            for case in cases:
                command = [
                    sys.executable,
                    str(_dynaplan_entrypoint()),
                    *_dynaplan_case_arguments(case),
                    "--preflight",
                ]
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    cwd=str(DYNAPLAN_ROOT),
                )
                if completed.returncode:
                    raise RunnerError(
                        "DynaPlan preflight subprocess failed for "
                        f"{case.benchmark}: {completed.stderr.strip()}"
                    )
                payload = _parse_subprocess_json(
                    completed.stdout, label="DynaPlan preflight"
                )
                if payload.get("status") != "PASS":
                    raise RunnerError(
                        f"DynaPlan preflight did not pass: {payload}"
                    )
                checks.append(
                    {
                        "benchmark": case.benchmark,
                        "task_id": payload.get("task_id"),
                        "strategy_module": "isolated copied runtime",
                        "strategy_function": "dynaplan_nlevel_pipeline",
                        "public_task_boundary": payload.get(
                            "public_task_boundary"
                        ),
                        "runtime_file_count": payload.get("runtime_file_count"),
                        "status": "PASS",
                    }
                )
        else:
            from flat_hanoi_baselines import METHODS, RUNNERS as FLAT_RUNNERS
            from lexicon_baseline_benchmark import (
                BASELINES as LOGISTICS_BASELINES,
                _load_strategy as load_logistics_strategy,
            )
            from lexicon_blocksworld_baseline_benchmark import (
                BASELINES as BLOCKSWORLD_BASELINES,
                _load_strategy as load_blocksworld_strategy,
            )

            registries = {
                "logistics": tuple(LOGISTICS_BASELINES),
                "blocksworld": tuple(BLOCKSWORLD_BASELINES),
                "flat-hanoi": tuple(METHODS),
            }
            for case in cases:
                if baseline not in registries[case.benchmark]:
                    raise RunnerError(
                        f"{baseline} is absent from the {case.benchmark} registry"
                    )
                if case.benchmark == "logistics":
                    strategy, _module = load_logistics_strategy(baseline)
                elif case.benchmark == "blocksworld":
                    strategy, _module = load_blocksworld_strategy(baseline)
                else:
                    strategy = FLAT_RUNNERS.get(baseline)
                if not callable(strategy):
                    raise RunnerError(
                        f"{baseline} did not resolve to a callable strategy for "
                        f"{case.benchmark}"
                    )
                task = (
                    _native_flat_task(case)
                    if case.benchmark == "flat-hanoi"
                    else _native_lexicon_task(case)
                )
                public_task_audit = _audit_public_strategy_task(case, task)
                checks.append(
                    {
                        "benchmark": case.benchmark,
                        "task_id": str(getattr(task, "id", "")),
                        "strategy_module": str(getattr(strategy, "__module__", "")),
                        "strategy_function": str(getattr(strategy, "__name__", "")),
                        "public_task_boundary": public_task_audit,
                        "status": "PASS",
                    }
                )
    except Exception as error:
        errors.append(f"{type(error).__name__}: {error}")
    return {
        "baseline": baseline,
        "display_name": BASELINE_DISPLAY_NAMES[baseline],
        "verified": not errors,
        "errors": errors,
        "source": source,
        "adapter_checks": checks,
    }


def _snapshot_implementation(campaign_dir: Path) -> Dict[str, Any]:
    """Freeze the non-Git adapter code and record runtime/planner identities."""

    source_names = (
        "comparison_protocol.py",
        "models.py",
        "task_loader.py",
        "scoring.py",
        "flat_prompts.py",
        "hanoi_solver.py",
        "hanoi_benchmark.py",
        "lexicon_logistics_benchmark.py",
        "lexicon_logistics_task.py",
        "lexicon_blocksworld_task.py",
        "lexicon_baseline_benchmark.py",
        "lexicon_blocksworld_baseline_benchmark.py",
        "flat_hanoi_task_loader.py",
        "flat_hanoi_baseline_core.py",
        "flat_hanoi_baselines.py",
        "flat_hanoi_baseline_benchmark.py",
        "prompts.py",
        "dynamic_scoring.py",
        "lexicon_logistics_prompts.py",
        "lexicon_logistics_structured.py",
        "lexicon_blocksworld_benchmark.py",
    )
    source_paths = [SHARED_ADAPTER_ROOT / name for name in source_names]
    source_paths.extend(
        path
        for path in sorted((SHARED_ADAPTER_ROOT / "baselines").glob("*.py"))
        if not path.name.startswith("test_")
    )
    missing = [str(path) for path in source_paths if not path.is_file()]
    if missing:
        raise RunnerError(f"Implementation snapshot sources are missing: {missing}")
    snapshot_root = campaign_dir / "implementation_snapshot"
    manifest: Dict[str, Any] = {}
    for source in source_paths:
        relative = source.relative_to(SHARED_ADAPTER_ROOT)
        payload = source.read_bytes()
        destination = snapshot_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(payload)
        os.replace(str(temporary), str(destination))
        manifest[str(relative)] = {
            "source": str(source),
            "snapshot": str(destination),
            "size_bytes": len(payload),
            "sha256": _sha256_bytes(payload),
        }
    dynaplan_method_root = BASELINE_CLONES_ROOT / "dynaplan"
    dynaplan_sources = sorted(
        path
        for path in dynaplan_method_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix in {".py", ".json", ".md"}
    )
    for source in dynaplan_sources:
        relative = Path("dynaplan") / source.relative_to(dynaplan_method_root)
        payload = source.read_bytes()
        destination = snapshot_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(payload)
        os.replace(str(temporary), str(destination))
        manifest[str(relative)] = {
            "source": str(source),
            "snapshot": str(destination),
            "size_bytes": len(payload),
            "sha256": _sha256_bytes(payload),
        }
    try:
        import importlib.metadata as package_metadata

        versions = {
            distribution: package_metadata.version(distribution)
            for distribution in ("unified-planning", "up-fast-downward")
        }
    except Exception as error:  # pragma: no cover - environment audit fallback.
        versions = {"error": f"{type(error).__name__}: {error}"}
    site_packages = (
        Path(sys.prefix)
        / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    planner_root = site_packages / "up_fast_downward/downward"
    planner_paths = [
        planner_root / "fast-downward.py",
        planner_root / "builds/release/bin/downward",
    ]
    planners = {
        str(path): {
            "present": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
            "sha256": _sha256_bytes(path.read_bytes()) if path.is_file() else None,
        }
        for path in planner_paths
    }
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "package_versions": versions,
        "adapter_sources": manifest,
        "planner_files": planners,
    }


def _validate_local_transformers_install() -> None:
    required = (
        "config.json",
        "model.safetensors.index.json",
        "model.safetensors-00001-of-00002.safetensors",
        "model.safetensors-00002-of-00002.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "chat_template.jinja",
    )
    missing = [name for name in required if not (LOCAL_MODEL_PATH / name).is_file()]
    if missing:
        raise RunnerError(
            f"Local Qwen snapshot is incomplete at {LOCAL_MODEL_PATH}: {missing}"
        )
    metadata_root = LOCAL_MODEL_PATH / ".cache" / "huggingface" / "download"
    revision_mismatches = []
    for name in required:
        metadata = metadata_root / f"{name}.metadata"
        try:
            recorded_revision = metadata.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError):
            recorded_revision = None
        if recorded_revision != LOCAL_MODEL_REVISION:
            revision_mismatches.append(
                {
                    "file": name,
                    "expected": LOCAL_MODEL_REVISION,
                    "found": recorded_revision,
                }
            )
    if revision_mismatches:
        raise RunnerError(
            "Local Qwen snapshot revision metadata is missing or mismatched: "
            f"{revision_mismatches}"
        )
    try:
        import bitsandbytes
        import torch
        import transformers
        from transformers import Qwen3_5ForCausalLM
    except ImportError as error:
        raise RunnerError(
            "Local Qwen dependencies are missing; run models/qwen3_5_4b/setup.sh"
        ) from error
    if not torch.cuda.is_available():
        raise RunnerError("Local Qwen 4-bit mode requires a CUDA GPU")
    if Qwen3_5ForCausalLM.__name__ != "Qwen3_5ForCausalLM":
        raise RunnerError("Transformers text-only Qwen3.5 class is unavailable")
    del bitsandbytes, transformers


def _local_transformers_config() -> Dict[str, Any]:
    _validate_local_transformers_install()
    import bitsandbytes
    import torch
    import transformers

    small_files = ("config.json", "model.safetensors.index.json")
    shards = sorted(LOCAL_MODEL_PATH.glob("model.safetensors-*.safetensors"))
    return {
        "model_id": QWEN_MODEL_ID,
        "model_revision": LOCAL_MODEL_REVISION,
        "snapshot_path": str(LOCAL_MODEL_PATH),
        "text_only_class": "Qwen3_5ForCausalLM",
        "vision_encoder_instantiated": False,
        "trust_remote_code": False,
        "quantization": {
            "load_in_4bit": True,
            "quant_type": "nf4",
            "double_quant": True,
            "compute_dtype": "bfloat16",
        },
        "enable_thinking": LOCAL_ENABLE_THINKING,
        "seed": LOCAL_SEED,
        "sampling_mode": os.environ.get(
            "LOCAL_TRANSFORMERS_SAMPLING_MODE", "recommended"
        ),
        "temperature": float(
            os.environ.get(
                "LOCAL_TRANSFORMERS_TEMPERATURE",
                "0.6" if LOCAL_ENABLE_THINKING else "0.7",
            )
        ),
        "top_p": float(
            os.environ.get(
                "LOCAL_TRANSFORMERS_TOP_P",
                "0.95" if LOCAL_ENABLE_THINKING else "0.8",
            )
        ),
        "top_k": int(os.environ.get("LOCAL_TRANSFORMERS_TOP_K", "20")),
        "min_p": (
            float(os.environ["LOCAL_TRANSFORMERS_MIN_P"])
            if os.environ.get("LOCAL_TRANSFORMERS_MIN_P", "").strip()
            else None
        ),
        "presence_penalty": (
            float(os.environ["LOCAL_TRANSFORMERS_PRESENCE_PENALTY"])
            if os.environ.get(
                "LOCAL_TRANSFORMERS_PRESENCE_PENALTY", ""
            ).strip()
            else None
        ),
        "packages": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "bitsandbytes": bitsandbytes.__version__,
        },
        "cuda": {
            "torch_cuda": torch.version.cuda,
            "device_name": torch.cuda.get_device_name(0),
            "device_capability": list(torch.cuda.get_device_capability(0)),
            "bf16_supported": bool(torch.cuda.is_bf16_supported()),
        },
        "snapshot_files": {
            name: {
                "size_bytes": (LOCAL_MODEL_PATH / name).stat().st_size,
                "sha256": _sha256_bytes((LOCAL_MODEL_PATH / name).read_bytes()),
            }
            for name in small_files
        },
        "weight_shards": {
            shard.name: {"size_bytes": shard.stat().st_size} for shard in shards
        },
        "weight_bytes": sum(shard.stat().st_size for shard in shards),
    }


def _shared_model_client() -> Any:
    _ensure_shared_adapter_root()
    try:
        from models import create_client
    except ImportError as error:  # pragma: no cover - guarded by preflight.
        raise RunnerError(f"Could not import shared model client: {error}") from error
    if PROVIDER == "openai":
        endpoint = _chat_completions_endpoint(
            BASE_URL_OVERRIDE or os.environ.get("OPENAI_BASE_URL", "")
        )
        client = create_client(
            provider=PROVIDER,
            model=MODEL,
            base_url=endpoint,
            reasoning_effort=REASONING_EFFORT,
        )
    elif PROVIDER == "anthropic":
        if ANTHROPIC_THINKING_BUDGET_TOKENS is None:
            raise RunnerError(
                "Anthropic literature runs require a manual thinking budget"
            )
        os.environ["ANTHROPIC_THINKING_BUDGET_TOKENS"] = str(
            ANTHROPIC_THINKING_BUDGET_TOKENS
        )
        endpoint = _anthropic_messages_endpoint(
            BASE_URL_OVERRIDE
            or os.environ.get(
                "ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages"
            )
        )
        client = create_client(
            provider=PROVIDER,
            model=MODEL,
            base_url=endpoint,
            reasoning_effort=REASONING_EFFORT,
        )
    elif PROVIDER == "local-transformers":
        # Keep the public model identity distinct from the local snapshot path.
        # The local client fails closed unless it can load the causal-LM-only
        # class with genuine bitsandbytes 4-bit modules on CUDA.
        os.environ["LOCAL_TRANSFORMERS_MODEL_PATH"] = str(LOCAL_MODEL_PATH)
        os.environ["LOCAL_TRANSFORMERS_REVISION"] = LOCAL_MODEL_REVISION
        os.environ["LOCAL_TRANSFORMERS_ENABLE_THINKING"] = (
            "true" if LOCAL_ENABLE_THINKING else "false"
        )
        os.environ["LOCAL_TRANSFORMERS_SEED"] = str(LOCAL_SEED)
        client = create_client(
            provider=PROVIDER,
            model=MODEL,
            reasoning_effort=REASONING_EFFORT,
        )
    else:
        raise RunnerError(
            f"Literature baselines do not support provider {PROVIDER!r}"
        )
    client.provider = PROVIDER
    return client


def _load_flat_instance(case: PreparedCase) -> Any:
    read_instances, _validate, _render, _tools = _load_flat_hanoi_modules()
    dataset = (
        FLAT_HANOI_ROOT
        / "flat_hanoi"
        / "data"
        / str(case.metadata["dataset"])
    )
    return next(
        instance
        for instance in read_instances(dataset)
        if instance.instance_id == case.task_id
    )


def _native_flat_task(case: PreparedCase) -> Any:
    """Bridge the new numeric Flat-Hanoi instance to the baseline port API."""

    instance = _load_flat_instance(case)
    return _flat_task_from_instance(
        instance, case.task_id, case.display_coordinate
    )


def _native_lexicon_task(case: PreparedCase) -> Any:
    _ensure_shared_adapter_root()
    constraint_count = int(case.metadata["nominal_constraint_count"])
    packed_id = int(case.metadata["packed_id"])
    if case.benchmark == "logistics":
        import lexicon_logistics_task as task_module

        # The older adapter predates an explicit checkout argument. Rebind only
        # its resolver so all parsing, prompt generation, and scoring use the
        # official clone colocated with this runner.
        task_module.checkout_root = lambda: LEXICON_ROOT
        return task_module.load_task(
            constraint_count, packed_id, prompt_source="official-mapper"
        )
    if case.benchmark == "blocksworld":
        import lexicon_blocksworld_task as task_module

        return task_module.load_task(
            constraint_count,
            packed_id,
            prompt_source="official-mapper",
            checkout=LEXICON_ROOT,
        )
    raise RunnerError(f"Not a LexiCon case: {case.benchmark}")


def _audit_public_strategy_task(case: PreparedCase, task: Any) -> Dict[str, Any]:
    """Construct the strategy view and prove oracle fields are absent."""

    _ensure_shared_adapter_root()
    if case.benchmark == "logistics":
        from lexicon_logistics_task import public_task_view

        forbidden = (
            "optimal_length",
            "oracle_actions",
            "task_dir",
            "source_files",
            "source_metadata",
        )
    elif case.benchmark == "blocksworld":
        from lexicon_blocksworld_task import public_task_view

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
    elif case.benchmark == "flat-hanoi":
        from flat_hanoi_task_loader import public_task_view

        forbidden = (
            "optimal_move_count",
            "source_peg",
            "auxiliary_peg",
            "target_peg",
        )
    else:  # pragma: no cover - callers validate benchmark names first.
        raise RunnerError(f"Unsupported public-task audit: {case.benchmark}")

    public_task = public_task_view(task)
    leaked = [name for name in forbidden if hasattr(public_task, name)]
    if leaked:
        raise RunnerError(
            f"Sanitized {case.benchmark} task exposes forbidden fields: {leaked}"
        )
    has_dynamic_fields = hasattr(public_task, "__dict__")
    if has_dynamic_fields:
        raise RunnerError(
            f"Sanitized {case.benchmark} task permits dynamic attributes"
        )
    return {
        "strategy_task_type": type(public_task).__name__,
        "oracle_fields_structurally_absent": True,
        "forbidden_fields": list(forbidden),
        "has_dynamic_attribute_dictionary": has_dynamic_fields,
    }


def _run_native_baseline(
    case: PreparedCase,
    baseline: str,
    *,
    client: Any,
    results_dir: Path,
    max_output_tokens: int,
) -> Dict[str, Any]:
    config = _baseline_config(baseline)
    if case.benchmark == "logistics":
        from lexicon_baseline_benchmark import run_baseline

        return dict(
            run_baseline(
                task=_native_lexicon_task(case),
                baseline=baseline,
                client=client,
                max_tokens=max_output_tokens,
                reasoning_effort=REASONING_EFFORT,
                config=config,
                results_dir=results_dir,
            )
        )
    if case.benchmark == "blocksworld":
        from lexicon_blocksworld_baseline_benchmark import run_baseline

        return dict(
            run_baseline(
                task=_native_lexicon_task(case),
                baseline=baseline,
                client=client,
                max_tokens=max_output_tokens,
                reasoning_effort=REASONING_EFFORT,
                config=config,
                results_dir=results_dir,
            )
        )
    if case.benchmark == "flat-hanoi":
        from flat_hanoi_baseline_benchmark import run_baseline

        return dict(
            run_baseline(
                task=_native_flat_task(case),
                method=baseline,
                client=client,
                max_tokens=max_output_tokens,
                reasoning_effort=REASONING_EFFORT,
                config=config,
                results_dir=results_dir,
            )
        )
    raise RunnerError(f"Unsupported benchmark for baseline adapter: {case.benchmark}")


_MOVE_HOOP = re.compile(
    r"^MoveHoop\(\s*(peg_[012])\s*,\s*(peg_[012])\s*\)$"
)


def _flat_candidate_as_numeric(case: PreparedCase, text: str) -> Tuple[str, Optional[str]]:
    """Convert source/target primitives to the new benchmark's disk triples."""

    instance = _load_flat_instance(case)
    peg_index = {"peg_0": 0, "peg_1": 1, "peg_2": 2}
    current = list(instance.start)
    moves: List[List[int]] = []
    failed = False
    error: Optional[str] = None
    for index, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        match = _MOVE_HOOP.fullmatch(line)
        if match is None:
            return "moves = []", f"candidate line {index} is malformed: {line!r}"
        source = peg_index[match.group(1)]
        target = peg_index[match.group(2)]
        source_disks = [
            disk for disk in range(1, instance.n + 1) if current[disk - 1] == source
        ]
        disk = min(source_disks) if source_disks and not failed else 0
        moves.append([disk, source, target])
        if disk == 0:
            failed = True
            error = error or f"move {index} selects an empty source peg"
            continue
        target_disks = [
            candidate
            for candidate in range(1, instance.n + 1)
            if current[candidate - 1] == target
        ]
        if source == target or (target_disks and disk > min(target_disks)):
            failed = True
            error = error or f"move {index} is illegal under Hanoi ordering"
            continue
        current[disk - 1] = target
    return "moves = " + json.dumps(moves), error


def _candidate_response(
    case: PreparedCase, native_result_dir: Path
) -> Tuple[str, Optional[str]]:
    if case.benchmark in LEXICON_DOMAINS:
        candidate = native_result_dir / "candidate_plan.pddl"
        if not candidate.is_file():
            return "", f"native candidate artifact is missing: {candidate}"
        body = candidate.read_text(encoding="utf-8").strip()
        return f"```\n{body}\n```", None
    candidate = native_result_dir / "candidate_moves.txt"
    if not candidate.is_file():
        return "moves = []", f"native candidate artifact is missing: {candidate}"
    return _flat_candidate_as_numeric(case, candidate.read_text(encoding="utf-8"))


def _normalized_native_usage(metrics: Mapping[str, Any]) -> Dict[str, int]:
    raw = metrics.get("token_usage")
    usage = raw if isinstance(raw, Mapping) else {}
    input_tokens = _int_value(usage.get("input_tokens"))
    cached = _int_value(usage.get("cached_input_tokens"))
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "uncached_input_tokens": max(0, input_tokens - cached),
        "output_tokens": _int_value(usage.get("output_tokens")),
        "reasoning_tokens": _int_value(usage.get("reasoning_tokens")),
        "total_tokens": _int_value(usage.get("total_tokens")),
    }


def _usage_from_client(client: Any) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    try:
        records = list(client.call_records_since(0))
    except Exception:
        records = []
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    )
    totals = {
        field: sum(
            _int_value((record.get("usage") or {}).get(field))
            for record in records
            if isinstance(record, Mapping)
        )
        for field in fields
    }
    totals["uncached_input_tokens"] = max(
        0, totals["input_tokens"] - totals["cached_input_tokens"]
    )
    return totals, [dict(record) for record in records if isinstance(record, Mapping)]


def _native_provenance(
    metrics: Mapping[str, Any], native_result_dir: Path
) -> Mapping[str, Any]:
    provenance = metrics.get("baseline_provenance")
    if isinstance(provenance, Mapping):
        return dict(provenance)
    artifact_path = native_result_dir / "baseline_artifacts.json"
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        artifact = {}
    if isinstance(artifact, Mapping) and isinstance(artifact.get("provenance"), Mapping):
        return dict(artifact["provenance"])
    category = metrics.get("method_category") or metrics.get("baseline_category")
    return {"declared_category": str(category)} if category else {}


def _expected_native_prompt_sha(case: PreparedCase) -> str:
    if case.benchmark in LEXICON_DOMAINS:
        return _sha256_text(case.user_prompt)
    _ensure_shared_adapter_root()
    from flat_hanoi_baseline_core import public_problem_text

    return _sha256_text(public_problem_text(_native_flat_task(case)))


def _read_native_artifacts(
    native_result_dir: Path, case: PreparedCase
) -> Dict[str, Any]:
    candidate_name = (
        "candidate_plan.pddl"
        if case.benchmark in LEXICON_DOMAINS
        else "candidate_moves.txt"
    )
    required_names = (
        "metrics.json",
        "steps.json",
        "baseline_artifacts.json",
        "raw_log.jsonl",
        candidate_name,
    )
    missing = [name for name in required_names if not (native_result_dir / name).is_file()]
    parsed: Dict[str, Any] = {}
    parse_errors: List[str] = []
    for name in ("metrics.json", "steps.json", "baseline_artifacts.json"):
        path = native_result_dir / name
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, Mapping):
                raise ValueError("top-level value is not an object")
            parsed[name] = dict(value)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            parse_errors.append(f"{name}: {type(error).__name__}: {error}")
    raw_events: List[Dict[str, Any]] = []
    raw_path = native_result_dir / "raw_log.jsonl"
    if raw_path.is_file():
        for line_number, raw_line in enumerate(
            raw_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line)
                if not isinstance(event, Mapping):
                    raise ValueError("event is not an object")
                raw_events.append(dict(event))
            except (ValueError, json.JSONDecodeError) as error:
                parse_errors.append(
                    f"raw_log.jsonl:{line_number}: {type(error).__name__}: {error}"
                )
    candidate_lines: List[str] = []
    candidate_path = native_result_dir / candidate_name
    if candidate_path.is_file():
        candidate_lines = [
            line.strip()
            for line in candidate_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    steps_candidate = (parsed.get("steps.json") or {}).get("candidate_plan")
    candidate_matches_steps = bool(
        isinstance(steps_candidate, list)
        and [str(item).strip() for item in steps_candidate] == candidate_lines
    )
    raw_model_call_failures = [
        event
        for event in raw_events
        if event.get("event") == "model_call_failure"
        or event.get("response_recorded") is False
    ]
    raw_model_calls = [
        event for event in raw_events if event.get("event") == "model_call"
    ]
    hashes = {
        name: _sha256_bytes((native_result_dir / name).read_bytes())
        for name in required_names
        if (native_result_dir / name).is_file()
    }
    return {
        "required_names": list(required_names),
        "missing": missing,
        "parse_errors": parse_errors,
        "hashes": hashes,
        "raw_event_count": len(raw_events),
        "raw_model_call_count": len(raw_model_calls),
        "raw_model_call_failure_count": len(raw_model_call_failures),
        "candidate_matches_steps": candidate_matches_steps,
        "parsed": parsed,
    }


def _normalized_native_status(
    case: PreparedCase, native_metrics: Mapping[str, Any]
) -> str:
    if case.benchmark in LEXICON_DOMAINS:
        return str(native_metrics.get("status") or "")
    if bool(native_metrics.get("optimal")):
        return "OPTIMAL"
    if bool(native_metrics.get("valid", native_metrics.get("solved", False))):
        return "SUBOPTIMAL"
    status = str(native_metrics.get("status") or "INVALID").upper()
    if status == "INCOMPLETE":
        return "INCORRECT"
    return "ILLEGAL"


def _run_literature_case_impl(
    case: PreparedCase,
    baseline: str,
    *,
    client: Any,
    campaign_dir: Path,
    max_output_tokens: int,
) -> Dict[str, Any]:
    case_dir = campaign_dir / baseline / case.benchmark
    case_dir.mkdir(parents=True, exist_ok=False)
    _write_text(case_dir / "benchmark_system_prompt.txt", case.system_prompt)
    _write_text(case_dir / "benchmark_user_prompt.txt", case.user_prompt)
    source_status = _baseline_source_status(
        baseline, require_fast_downward=case.benchmark in LEXICON_DOMAINS
    )
    request_record = {
        "provider": PROVIDER,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "max_completion_tokens": max_output_tokens,
        "baseline": baseline,
        "baseline_display_name": BASELINE_DISPLAY_NAMES[baseline],
        "benchmark": case.benchmark,
        "task_id": case.task_id,
        "benchmark_reference_prompt": _prompt_metadata(case),
        "model_prompt_provenance": (
            "The mechanism-specific public task and every exact stage prompt are "
            "persisted in native/ raw_log.jsonl; the benchmark reference prompt "
            "above is not asserted to be sent unchanged."
        ),
        "started_at": _utc_now(),
        "baseline_source": source_status,
    }
    _write_json(case_dir / "request.json", request_record)
    timer = time.perf_counter()
    try:
        native_metrics = _run_native_baseline(
            case,
            baseline,
            client=client,
            results_dir=case_dir / "native",
            max_output_tokens=max_output_tokens,
        )
    except Exception as error:
        recovered_usage, recovered_calls = _usage_from_client(client)
        _write_json(
            case_dir / "recovered_call_ledger.json",
            {"calls": recovered_calls, "usage": recovered_usage},
        )
        result = {
            **request_record,
            "completed_at": _utc_now(),
            "runtime_seconds": round(time.perf_counter() - timer, 6),
            "status": "SETUP_ERROR",
            "success": False,
            "valid": False,
            "optimal": False,
            "setup_verified": False,
            "setup_status": "FAIL",
            "setup_failure_reasons": [
                f"baseline runtime raised {type(error).__name__}: {error}"
            ],
            "evaluation": {
                "status": "SETUP_ERROR",
                "success": False,
                "valid": False,
                "optimal": False,
                "submitted_length": None,
                "optimal_length": case.optimum,
                "failure_kind": "baseline_runtime",
                "failure_message": f"{type(error).__name__}: {error}",
            },
            "usage": recovered_usage,
            "model_call_count": len(recovered_calls),
            "model_call_attempt_count": None,
            "source": case.metadata,
            "artifact_dir": str(case_dir),
        }
        _write_json(case_dir / "result.json", result)
        return result

    native_result_dir = Path(str(native_metrics["result_dir"]))
    candidate_response, conversion_warning = _candidate_response(
        case, native_result_dir
    )
    _write_text(case_dir / "normalized_candidate.txt", candidate_response)
    evaluation = case.scorer(candidate_response)
    if case.benchmark in LEXICON_DOMAINS:
        evaluation["format_measurement_scope"] = "harness_normalized_candidate"
    native_success = bool(
        native_metrics.get("valid", native_metrics.get("solved", False))
    )
    native_optimal = bool(native_metrics.get("optimal", False))
    score_agreement = (
        native_success == bool(evaluation.get("success"))
        and native_optimal == bool(evaluation.get("optimal"))
    )
    token_usage = native_metrics.get("token_usage")
    token_usage_map = token_usage if isinstance(token_usage, Mapping) else {}
    call_count = _int_value(native_metrics.get("model_call_count"))
    attempt_count = _int_value(native_metrics.get("model_call_attempt_count"))
    strategy_error = native_metrics.get("strategy_error")
    artifact_audit = _read_native_artifacts(native_result_dir, case)
    persisted_metrics = (artifact_audit.get("parsed") or {}).get("metrics.json") or {}
    expected_native_task = (
        _native_flat_task(case)
        if case.benchmark == "flat-hanoi"
        else _native_lexicon_task(case)
    )
    expected_public_boundary = _audit_public_strategy_task(
        case, expected_native_task
    )
    recorded_public_boundary = native_metrics.get("strategy_task_boundary")
    public_boundary_agreement = bool(
        isinstance(recorded_public_boundary, Mapping)
        and recorded_public_boundary.get("sanitized_public_task") is True
        and recorded_public_boundary.get("oracle_fields_structurally_absent")
        is True
        and recorded_public_boundary.get("strategy_task_type")
        == expected_public_boundary["strategy_task_type"]
        and list(recorded_public_boundary.get("forbidden_fields", ()))
        == expected_public_boundary["forbidden_fields"]
    )
    expected_task_id = str(expected_native_task.id)
    recorded_method = native_metrics.get("baseline", native_metrics.get("method"))
    expected_benchmark = {
        "logistics": "lexicon_logistics",
        "blocksworld": "lexicon_blocksworld",
        "flat-hanoi": "flat_hanoi_baselines",
    }[case.benchmark]
    expected_architecture = EXPECTED_ARCHITECTURES[case.benchmark][baseline]
    expected_config = _baseline_config(baseline)
    recorded_config = native_metrics.get("config")
    config_agreement = bool(
        isinstance(recorded_config, Mapping)
        and dict(recorded_config) == expected_config
    )
    source_hash_agreement = True
    if case.benchmark in LEXICON_DOMAINS:
        native_source = native_metrics.get("source")
        native_hashes = (
            native_source.get("sha256") if isinstance(native_source, Mapping) else None
        )
        central_hashes = case.metadata.get("source_files")
        source_hash_agreement = bool(
            isinstance(native_hashes, Mapping)
            and isinstance(central_hashes, Mapping)
            and all(native_hashes.get(name) == digest for name, digest in central_hashes.items())
            and native_source.get("commit") == PINNED_LEXICON_COMMIT
        )
    prompt_hash_agreement = (
        native_metrics.get("prompt_sha256") == _expected_native_prompt_sha(case)
    )
    native_optimum = _int_value(
        native_metrics.get("optimal_length"),
        native_metrics.get("optimal_move_count"),
    )
    invocation_agreement = bool(
        native_metrics.get("benchmark") == expected_benchmark
        and recorded_method == baseline
        and native_metrics.get("task_id") == expected_task_id
        and native_metrics.get("provider") == PROVIDER
        and native_metrics.get("model") == MODEL
        and native_metrics.get("reasoning_effort") == REASONING_EFFORT
        and native_metrics.get("architecture_version") == expected_architecture
        and native_metrics.get("comparison_prompt_protocol")
        == case.metadata.get("comparison_prompt_protocol")
        and native_metrics.get("comparison_semantics_sha256")
        == case.metadata.get("comparison_semantics_sha256")
        and native_optimum == case.optimum
        and config_agreement
        and prompt_hash_agreement
        and source_hash_agreement
        and public_boundary_agreement
        and (
            case.benchmark == "flat-hanoi"
            or native_metrics.get("prompt_source") == "official-mapper"
        )
    )
    returned_persisted_view = _jsonable(dict(native_metrics))
    if case.benchmark in LEXICON_DOMAINS:
        # The two LexiCon runners append this convenience field only after
        # writing metrics.json. The Flat runner persists it in both places.
        returned_persisted_view.pop("result_dir", None)
    persisted_metrics_agree = bool(
        persisted_metrics and persisted_metrics == returned_persisted_view
    )
    artifacts_complete = bool(
        not artifact_audit.get("missing")
        and not artifact_audit.get("parse_errors")
        and artifact_audit.get("candidate_matches_steps")
        and persisted_metrics_agree
    )
    normalized_native_status = _normalized_native_status(case, native_metrics)
    submitted_agreement = (
        _int_value(native_metrics.get("submitted_length"))
        == _int_value(evaluation.get("submitted_length"))
    )
    status_agreement = normalized_native_status == str(evaluation.get("status") or "")
    raw_log_clean = bool(
        artifact_audit.get("raw_model_call_failure_count") == 0
        and _int_value(artifact_audit.get("raw_model_call_count")) == call_count
    )
    calls_by_stage = native_metrics.get("model_calls_by_stage")
    required_core_stages = CORE_STAGE_REQUIREMENTS[baseline]
    missing_core_stages = [
        stage
        for stage in required_core_stages
        if not isinstance(calls_by_stage, Mapping)
        or _int_value(calls_by_stage.get(stage)) < 1
    ]
    mechanism_exercised = not missing_core_stages
    exact_usage_call_count = (
        _int_value(token_usage_map.get("local_exact_usage_call_count"))
        if PROVIDER == "local-transformers"
        else _int_value(token_usage_map.get("api_usage_call_count"))
    )
    setup_verified = bool(
        source_status.get("verified")
        and strategy_error in {None, ""}
        and not native_metrics.get("model_call_budget_exhausted", False)
        and call_count >= 1
        and attempt_count == call_count
        and _int_value(token_usage_map.get("call_count")) == call_count
        and exact_usage_call_count == call_count
        and artifacts_complete
        and score_agreement
        and submitted_agreement
        and status_agreement
        and raw_log_clean
        and invocation_agreement
        and mechanism_exercised
    )
    setup_reasons = []
    if not source_status.get("verified"):
        setup_reasons.append("reference source or required planner failed preflight")
    if strategy_error not in {None, ""}:
        setup_reasons.append(f"strategy_error={strategy_error}")
    if native_metrics.get("model_call_budget_exhausted", False):
        setup_reasons.append("model-call budget exhausted")
    if call_count < 1:
        setup_reasons.append("no recorded model call")
    if attempt_count != call_count:
        setup_reasons.append(
            f"attempted/recorded model calls differ ({attempt_count}/{call_count})"
        )
    if _int_value(token_usage_map.get("call_count")) != call_count:
        setup_reasons.append("token ledger call count disagrees with metrics")
    if exact_usage_call_count != call_count:
        setup_reasons.append(
            "not every recorded model call has exact provider usage"
        )
    if not artifacts_complete:
        setup_reasons.append("native artifact set is incomplete or internally inconsistent")
    if not score_agreement:
        setup_reasons.append("native and central authoritative scores disagree")
    if not submitted_agreement:
        setup_reasons.append("native and central submitted lengths disagree")
    if not status_agreement:
        setup_reasons.append("native and central normalized statuses disagree")
    if not raw_log_clean:
        setup_reasons.append("native raw log contains a model-call infrastructure failure")
    if not invocation_agreement:
        setup_reasons.append("native metrics do not match the registered invocation")
    if not public_boundary_agreement:
        setup_reasons.append(
            "native run did not attest the registered oracle-free task boundary"
        )
    if not mechanism_exercised:
        setup_reasons.append(
            "core method stages were not all exercised: "
            + ", ".join(missing_core_stages)
        )
    result = {
        **request_record,
        "completed_at": _utc_now(),
        "runtime_seconds": round(time.perf_counter() - timer, 6),
        "status": evaluation["status"],
        "success": bool(evaluation.get("success")),
        "valid": bool(evaluation.get("valid")),
        "optimal": bool(evaluation.get("optimal")),
        "setup_verified": setup_verified,
        "setup_status": "PASS" if setup_verified else "FAIL",
        "setup_failure_reasons": setup_reasons,
        "evaluation": evaluation,
        # Literature ports persist an internal PDDL plan, which the harness
        # wraps for central semantic rescoring. That synthetic envelope cannot
        # measure whether a model followed the public response-format request.
        "format_adherent": None,
        "format_adherence_scope": "not_applicable_harness_normalized_candidate",
        "usage": _normalized_native_usage(native_metrics),
        "model_call_count": call_count,
        "model_call_attempt_count": attempt_count,
        "model_calls_by_stage": calls_by_stage or {},
        "mechanism_exercised": mechanism_exercised,
        "required_core_stages": list(required_core_stages),
        "missing_core_stages": missing_core_stages,
        "native_score": {
            "status": native_metrics.get("status"),
            "success": native_success,
            "optimal": native_optimal,
            "submitted_length": native_metrics.get("submitted_length"),
            "optimal_length": native_metrics.get(
                "optimal_length", native_metrics.get("optimal_move_count")
            ),
        },
        "cross_score_agreement": score_agreement,
        "submitted_length_agreement": submitted_agreement,
        "status_agreement": status_agreement,
        "normalized_native_status": normalized_native_status,
        "invocation_agreement": invocation_agreement,
        "invocation_checks": {
            "expected_benchmark": expected_benchmark,
            "expected_task_id": expected_task_id,
            "expected_architecture_version": expected_architecture,
            "expected_native_prompt_sha256": _expected_native_prompt_sha(case),
            "config_agreement": config_agreement,
            "prompt_hash_agreement": prompt_hash_agreement,
            "source_hash_agreement": source_hash_agreement,
            "public_task_boundary_agreement": public_boundary_agreement,
            "expected_public_task_boundary": expected_public_boundary,
            "native_optimum": native_optimum,
        },
        "native_artifact_audit": {
            key: value
            for key, value in artifact_audit.items()
            if key != "parsed"
        },
        "candidate_conversion_warning": conversion_warning,
        "action_adapter": (
            "source/target MoveHoop converted by deterministic top-disk "
            "reconstruction into the frozen benchmark's [disk, source, target] "
            "schema"
            if case.benchmark == "flat-hanoi"
            else "identity primitive-action text"
        ),
        "architecture_version": native_metrics.get("architecture_version"),
        "method_metrics": native_metrics.get("method_metrics", {}),
        "baseline_provenance": _native_provenance(
            native_metrics, native_result_dir
        ),
        "native_result_dir": str(native_result_dir),
        "native_metrics_sha256": _sha256_bytes(
            (native_result_dir / "metrics.json").read_bytes()
        ),
        "source": case.metadata,
        "artifact_dir": str(case_dir),
    }
    _write_json(case_dir / "result.json", result)
    return result


def _run_literature_case(
    case: PreparedCase,
    baseline: str,
    *,
    campaign_dir: Path,
    max_output_tokens: int,
) -> Dict[str, Any]:
    """Isolate every model condition so one audit failure cannot end a campaign."""

    client: Any = None
    timer = time.perf_counter()
    try:
        client = _shared_model_client()
        return _run_literature_case_impl(
            case,
            baseline,
            client=client,
            campaign_dir=campaign_dir,
            max_output_tokens=max_output_tokens,
        )
    except Exception as error:
        case_dir = campaign_dir / baseline / case.benchmark
        case_dir.mkdir(parents=True, exist_ok=True)
        usage, calls = (
            _usage_from_client(client)
            if client is not None
            else (
                {
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "uncached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                },
                [],
            )
        )
        _write_json(
            case_dir / "recovered_call_ledger.json",
            {"calls": calls, "usage": usage},
        )
        _write_json(
            case_dir / "postprocessing_error.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "completed_at": _utc_now(),
            },
        )
        result = {
            "provider": PROVIDER,
            "model": MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "max_completion_tokens": max_output_tokens,
            "baseline": baseline,
            "baseline_display_name": BASELINE_DISPLAY_NAMES[baseline],
            "benchmark": case.benchmark,
            "task_id": case.task_id,
            "started_at": _utc_now(),
            "completed_at": _utc_now(),
            "runtime_seconds": round(time.perf_counter() - timer, 6),
            "status": "SETUP_ERROR",
            "success": False,
            "valid": False,
            "optimal": False,
            "setup_verified": False,
            "setup_status": "FAIL",
            "setup_failure_reasons": [
                f"condition audit raised {type(error).__name__}: {error}"
            ],
            "evaluation": {
                "status": "SETUP_ERROR",
                "success": False,
                "valid": False,
                "optimal": False,
                "submitted_length": None,
                "optimal_length": case.optimum,
                "failure_kind": "condition_audit",
                "failure_message": f"{type(error).__name__}: {error}",
            },
            "usage": usage,
            "model_call_count": len(calls),
            "model_call_attempt_count": None,
            "source": case.metadata,
            "artifact_dir": str(case_dir),
        }
        _write_json(case_dir / "result.json", result)
        return result


def _run_dynaplan_case(
    case: PreparedCase,
    *,
    campaign_dir: Path,
    max_output_tokens: int,
    env_file: Path,
) -> Dict[str, Any]:
    """Run the copied architecture in isolation and independently rescore it."""

    baseline = DYNAPLAN_BASELINE
    case_dir = campaign_dir / baseline / case.benchmark
    case_dir.mkdir(parents=True, exist_ok=False)
    request_record = {
        "provider": PROVIDER,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "anthropic_thinking_budget_tokens": ANTHROPIC_THINKING_BUDGET_TOKENS,
        "max_completion_tokens": max_output_tokens,
        "baseline": baseline,
        "baseline_display_name": BASELINE_DISPLAY_NAMES[baseline],
        "benchmark": case.benchmark,
        "task_id": case.task_id,
        "benchmark_reference_prompt": _prompt_metadata(case),
        "started_at": _utc_now(),
        "baseline_source": _baseline_source_status(baseline),
    }
    _write_json(case_dir / "request.json", request_record)
    native_root = case_dir / "native"
    native_output = case_dir / "native_metrics.json"
    config = _baseline_config(baseline)
    command = [
        sys.executable,
        str(_dynaplan_entrypoint()),
        *_dynaplan_case_arguments(case),
        "--provider",
        PROVIDER,
        "--model",
        MODEL,
        "--reasoning",
        REASONING_EFFORT,
        "--max-output-tokens",
        str(max_output_tokens),
        "--max-replans",
        str(config["max_replans"]),
        "--env-file",
        str(env_file),
        "--results-dir",
        str(native_root),
        "--output-json",
        str(native_output),
        "--execute",
    ]
    if BASE_URL_OVERRIDE:
        command.extend(("--base-url", BASE_URL_OVERRIDE))
    if PROVIDER == "anthropic" and ANTHROPIC_THINKING_BUDGET_TOKENS is not None:
        command.extend(
            (
                "--anthropic-thinking-budget",
                str(ANTHROPIC_THINKING_BUDGET_TOKENS),
            )
        )
    timer = time.perf_counter()
    live_call_log = case_dir / "live_model_calls.jsonl"
    child_environment = dict(os.environ)
    child_environment["LIVE_LOG_PATH"] = str(live_call_log)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(DYNAPLAN_ROOT),
        env=child_environment,
    )
    _write_text(case_dir / "launcher_stdout.txt", completed.stdout)
    _write_text(case_dir / "launcher_stderr.txt", completed.stderr)
    if completed.returncode or not native_output.is_file():
        message = completed.stderr.strip() or "DynaPlan did not write native metrics"
        recovered_calls: List[Dict[str, Any]] = []
        if live_call_log.is_file():
            for line in live_call_log.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    if isinstance(record, dict):
                        recovered_calls.append(record)
        recovered_usage = {
            key: sum(
                _int_value((record.get("usage") or {}).get(key))
                for record in recovered_calls
                if isinstance(record.get("usage"), Mapping)
            )
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "uncached_input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "total_tokens",
            )
        }
        result = {
            **request_record,
            "completed_at": _utc_now(),
            "runtime_seconds": round(time.perf_counter() - timer, 6),
            "status": "SETUP_ERROR",
            "success": False,
            "valid": False,
            "optimal": False,
            "setup_verified": False,
            "setup_status": "FAIL",
            "setup_failure_reasons": [message],
            "evaluation": {
                "status": "SETUP_ERROR",
                "success": False,
                "valid": False,
                "optimal": False,
                "submitted_length": None,
                "optimal_length": case.optimum,
                "failure_kind": "dynaplan_runtime",
                "failure_message": message,
            },
            "usage": recovered_usage,
            "model_call_count": len(recovered_calls),
            "model_call_attempt_count": len(recovered_calls),
            "recovered_completed_call_ledger": str(live_call_log),
            "source": case.metadata,
            "artifact_dir": str(case_dir),
        }
        _write_json(case_dir / "result.json", result)
        return result

    native_metrics = json.loads(native_output.read_text(encoding="utf-8"))
    if not isinstance(native_metrics, dict):
        raise RunnerError("DynaPlan native metrics must be one JSON object")
    native_result_dir = Path(str(native_metrics.get("result_dir", "")))
    required = (
        native_result_dir / "metrics.json",
        native_result_dir / "steps.json",
        native_result_dir / "raw_log.jsonl",
    )
    artifacts_complete = bool(native_result_dir.is_dir() and all(p.is_file() for p in required))
    steps: Dict[str, Any] = {}
    raw_events: List[Dict[str, Any]] = []
    if artifacts_complete:
        loaded_steps = json.loads(required[1].read_text(encoding="utf-8"))
        steps = loaded_steps if isinstance(loaded_steps, dict) else {}
        for line in required[2].read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = json.loads(line)
                if isinstance(event, dict):
                    raw_events.append(event)
    actions = [str(action) for action in steps.get("candidate_plan", [])]
    submission_actions = list(actions)
    if case.benchmark == "flat-hanoi":
        # DynaPlan's internal semantic-action label is MoveSingleRing; the
        # controlled benchmark's common submission label is MoveHoop. This is
        # a name-only boundary conversion, not search or repair.
        submission_actions = [
            re.sub(r"^MoveSingleRing\s*\(", "MoveHoop(", action)
            for action in actions
        ]
    action_conversion_warning: Optional[str] = None
    if case.benchmark == "flat-hanoi":
        normalized, action_conversion_warning = _flat_candidate_as_numeric(
            case, "\n".join(submission_actions)
        )
        _write_text(case_dir / "normalized_candidate.txt", normalized)
        evaluation = case.scorer(normalized)
    else:
        normalized = "```\n" + "\n".join(submission_actions) + "\n```"
        _write_text(case_dir / "normalized_candidate.txt", normalized)
        evaluation = case.scorer(normalized)
        evaluation["format_measurement_scope"] = "harness_normalized_candidate"

    native_score = native_metrics.get("score")
    native_score = native_score if isinstance(native_score, Mapping) else {}
    native_success = bool(native_metrics.get("success"))
    native_optimal = bool(native_score.get("optimal"))
    native_length = _int_value(
        native_score.get("submitted_length"),
        native_score.get("move_count"),
    )
    cross_score_agreement = bool(
        native_success == bool(evaluation.get("success"))
        and native_optimal == bool(evaluation.get("optimal"))
        and native_length == _int_value(evaluation.get("submitted_length"))
    )
    call_count = _int_value(native_metrics.get("model_call_count"))
    recorded_count = _int_value(native_metrics.get("recorded_model_call_count"))
    model_events = [event for event in raw_events if event.get("event") == "model_call"]
    exact_api_usage_count = sum(
        isinstance(event.get("usage"), Mapping)
        and (event.get("usage") or {}).get("usage_source") == "api"
        for event in model_events
    )
    objective = str(case.metadata.get("minimum_action_objective", ""))
    _ensure_shared_adapter_root()
    from comparison_protocol import common_semantics_contract

    common_semantics = common_semantics_contract(case.benchmark)
    hanoi_example = None
    if case.benchmark == "flat-hanoi":
        _ensure_shared_adapter_root()
        from comparison_protocol import FLAT_HANOI_SHARED_SOLVED_EXAMPLE

        hanoi_example = FLAT_HANOI_SHARED_SOLVED_EXAMPLE
    prompt_contract = []
    for event in model_events:
        combined = str(event.get("system", "")) + "\n" + str(event.get("prompt", ""))
        prompt_contract.append(
            {
                "call_index": event.get("call_index"),
                "minimum_objective_count": combined.count(objective) if objective else 0,
                "common_semantics_count": combined.count(common_semantics),
                "shared_hanoi_example_count": (
                    combined.count(hanoi_example) if hanoi_example else None
                ),
            }
        )
    prompt_contract_ok = bool(
        prompt_contract
        and all(item["minimum_objective_count"] == 1 for item in prompt_contract)
        and all(item["common_semantics_count"] == 1 for item in prompt_contract)
        and (
            hanoi_example is None
            or all(item["shared_hanoi_example_count"] == 1 for item in prompt_contract)
        )
    )
    integration = native_metrics.get("official_integration")
    integration = integration if isinstance(integration, Mapping) else {}
    boundary = integration.get("public_task_boundary")
    boundary = boundary if isinstance(boundary, Mapping) else {}
    final_evaluator_once = (
        _int_value(integration.get("official_final_evaluator_call_count")) == 1
    )
    source_status = _baseline_source_status(baseline)
    invocation_agreement = bool(
        native_metrics.get("architecture_version")
        == "dynaplan_final_nlevel_hierarchy_v1_1"
        and native_metrics.get("provider") == PROVIDER
        and native_metrics.get("model") == MODEL
        and native_metrics.get("reasoning_effort") == REASONING_EFFORT
        and native_metrics.get("task_id") == case.task_id
        and native_metrics.get("comparison_prompt_protocol_version")
        == case.metadata.get("comparison_prompt_protocol")
        and native_metrics.get("comparison_semantics_sha256")
        == case.metadata.get("comparison_semantics_sha256")
    )
    setup_verified = bool(
        source_status.get("verified")
        and artifacts_complete
        and call_count >= 1
        and call_count == recorded_count == len(model_events)
        and exact_api_usage_count == call_count
        and native_metrics.get("model_call_accounting_consistent") is True
        and final_evaluator_once
        and cross_score_agreement
        and invocation_agreement
        and prompt_contract_ok
        and boundary.get("oracle_fields_structurally_absent") is True
        and boundary.get("slot_only") is True
    )
    reasons = []
    if not source_status.get("verified"):
        reasons.append("copied DynaPlan source failed provenance preflight")
    if not artifacts_complete:
        reasons.append("native DynaPlan artifacts are incomplete")
    if call_count < 1 or call_count != recorded_count or call_count != len(model_events):
        reasons.append("DynaPlan model-call accounting disagrees")
    if exact_api_usage_count != call_count:
        reasons.append("not every DynaPlan call has exact provider usage")
    if not final_evaluator_once:
        reasons.append("DynaPlan did not attest exactly one internal final evaluation")
    if not cross_score_agreement:
        reasons.append("DynaPlan native score and independent central rescore disagree")
    if not invocation_agreement:
        reasons.append("DynaPlan native invocation metadata disagrees")
    if not prompt_contract_ok:
        reasons.append("shared prompt contract is absent or duplicated")
    if boundary.get("oracle_fields_structurally_absent") is not True or boundary.get("slot_only") is not True:
        reasons.append("DynaPlan public task boundary is not oracle-free and slot-only")
    result = {
        **request_record,
        "completed_at": _utc_now(),
        "runtime_seconds": round(time.perf_counter() - timer, 6),
        "status": evaluation.get("status", "INVALID"),
        "success": bool(evaluation.get("success")),
        "valid": bool(evaluation.get("valid", evaluation.get("success"))),
        "optimal": bool(evaluation.get("optimal")),
        "setup_verified": setup_verified,
        "setup_status": "PASS" if setup_verified else "FAIL",
        "setup_failure_reasons": reasons,
        "evaluation": evaluation,
        "format_adherent": None,
        "format_adherence_scope": "not_applicable_harness_normalized_candidate",
        "usage": _normalized_native_usage(native_metrics),
        "model_call_count": call_count,
        "model_call_attempt_count": recorded_count,
        "exact_api_usage_call_count": exact_api_usage_count,
        "model_calls_by_stage": native_metrics.get("model_calls_by_stage", {}),
        "cross_score_agreement": cross_score_agreement,
        "invocation_agreement": invocation_agreement,
        "final_evaluator_once": final_evaluator_once,
        "prompt_contract_verified": prompt_contract_ok,
        "prompt_contract": prompt_contract,
        "action_conversion_warning": action_conversion_warning,
        "internal_candidate_actions": actions,
        "submitted_candidate_actions": submission_actions,
        "architecture_version": native_metrics.get("architecture_version"),
        "method_metrics": native_metrics.get("extra_metrics", {}),
        "native_score": dict(native_score),
        "native_result_dir": str(native_result_dir),
        "native_metrics_sha256": _sha256_bytes(required[0].read_bytes()) if artifacts_complete else None,
        "source": case.metadata,
        "artifact_dir": str(case_dir),
    }
    _write_json(case_dir / "result.json", result)
    return result


def _run_case(
    case: PreparedCase,
    *,
    campaign_dir: Path,
    max_output_tokens: int,
    timeout_seconds: int,
) -> Dict[str, Any]:
    case_dir = campaign_dir / case.benchmark
    case_dir.mkdir(parents=True, exist_ok=False)
    _write_text(case_dir / "system_prompt.txt", case.system_prompt)
    _write_text(case_dir / "user_prompt.txt", case.user_prompt)
    request_record = {
        "provider": PROVIDER,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "anthropic_thinking_budget_tokens": ANTHROPIC_THINKING_BUDGET_TOKENS,
        "max_completion_tokens": max_output_tokens,
        "tools_allowed": False,
        "baseline": "base",
        "baseline_display_name": BASELINE_DISPLAY_NAMES["base"],
        "benchmark": case.benchmark,
        "task_id": case.task_id,
        "prompt": _prompt_metadata(case),
        "started_at": _utc_now(),
    }
    _write_json(case_dir / "request.json", request_record)
    try:
        response = call_model(
            system_prompt=case.system_prompt,
            user_prompt=case.user_prompt,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
    except Exception as error:
        result = {
            **request_record,
            "completed_at": _utc_now(),
            "status": "MODEL_ERROR",
            "success": False,
            "valid": False,
            "optimal": False,
            "setup_verified": False,
            "setup_status": "FAIL",
            "setup_failure_reasons": ["model inference failed"],
            "evaluation": {
                "status": "MODEL_ERROR",
                "success": False,
                "valid": False,
                "optimal": False,
                "submitted_length": None,
                "optimal_length": case.optimum,
                "failure_kind": "model_error",
                "failure_message": f"{type(error).__name__}: {error}",
            },
            "usage": {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "uncached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
            },
            "model_call_count": 0,
            "model_call_attempt_count": 1,
            "source": case.metadata,
            "artifact_dir": str(case_dir),
        }
        _write_json(case_dir / "result.json", result)
        return result

    _write_text(case_dir / "response.txt", response.text)
    response_record = {
        "finish_reason": response.finish_reason,
        "response_id": response.response_id,
        "request_id": response.request_id,
        "returned_model": response.returned_model,
        "usage": response.usage,
        "estimated_cost_usd": _estimated_cost_usd(
            PROVIDER, MODEL, response.raw_usage
        ),
        "raw_usage": response.raw_usage,
        "reasoning_char_count": response.reasoning_char_count,
        "backend_metadata": response.backend_metadata,
        "runtime_seconds": round(response.runtime_seconds, 6),
        "response_sha256": _sha256_text(response.text),
        "response_char_count": len(response.text),
    }
    _write_json(case_dir / "response_metadata.json", response_record)
    truncated = response.finish_reason in {
        "length",
        "max_tokens",
        "model_context_window_exceeded",
    }
    action_conversion_warning: Optional[str] = None
    if truncated:
        evaluation = _truncated_evaluation(case, response)
    elif case.benchmark == "flat-hanoi":
        normalized_response, action_conversion_warning = _flat_candidate_as_numeric(
            case, response.text
        )
        _write_text(case_dir / "normalized_candidate.txt", normalized_response)
        evaluation = case.scorer(normalized_response)
        evaluation["model_action_representation"] = (
            "MoveHoop(source_peg, target_peg)"
        )
        evaluation["evaluator_action_representation"] = (
            "[disk_id, source_peg, destination_peg]"
        )
        evaluation["action_conversion_warning"] = action_conversion_warning
    else:
        evaluation = case.scorer(response.text)
    result = {
        **request_record,
        "completed_at": _utc_now(),
        "status": evaluation["status"],
        "success": bool(evaluation.get("success")),
        "valid": bool(evaluation.get("valid")),
        "optimal": bool(evaluation.get("optimal")),
        "setup_verified": True,
        "setup_status": "PASS",
        "setup_failure_reasons": [],
        "evaluation": evaluation,
        "format_adherent": evaluation.get("format_adherent"),
        "format_adherence_scope": (
            "direct_model_response"
            if case.benchmark in LEXICON_DOMAINS
            else "not_applicable"
        ),
        "action_adapter": (
            case.metadata.get("action_adapter")
            if case.benchmark == "flat-hanoi"
            else "identity primitive-action text"
        ),
        "action_conversion_warning": action_conversion_warning,
        "usage": response.usage,
        "runtime_seconds": round(response.runtime_seconds, 6),
        "estimated_cost_usd": response_record["estimated_cost_usd"],
        "model_call_count": 1,
        "model_call_attempt_count": 1,
        "api": response_record,
        "source": case.metadata,
        "artifact_dir": str(case_dir),
    }
    _write_json(case_dir / "result.json", result)
    return result


def _summary_markdown(results: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Dynaplan benchmark smoke summary",
        "",
        f"Provider: `{PROVIDER}`  ",
        f"Model: `{MODEL}`  ",
        f"Reasoning effort: `{REASONING_EFFORT}`  ",
        (
            f"Anthropic extended-thinking budget: "
            f"`{ANTHROPIC_THINKING_BUDGET_TOKENS}` tokens  "
            if ANTHROPIC_THINKING_BUDGET_TOKENS is not None
            else ""
        ),
        "Protocol: one independent smoke run per selected method and task coordinate.",
        "",
        "| Baseline | Benchmark | Task | Setup | Status | Success | Optimal | Exact format | Submitted / optimum | Calls | Tokens | Est. cost |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        evaluation = result.get("evaluation") or {}
        submitted = evaluation.get("submitted_length")
        optimum = evaluation.get("optimal_length")
        length_cell = f"{submitted if submitted is not None else '—'} / {optimum if optimum is not None else '—'}"
        usage = result.get("usage") or {}
        lines.append(
            "| {baseline} | {benchmark} | {task} | {setup} | {status} | {success} | {optimal} | {format} | {lengths} | {calls} | {tokens} | {cost} |".format(
                baseline=result.get("baseline_display_name", result.get("baseline", "—")),
                benchmark=result.get("benchmark", "—"),
                task=result.get("task_id", "—"),
                setup=result.get("setup_status", "—"),
                status=result.get("status", "—"),
                success="yes" if result.get("success") else "no",
                optimal="yes" if result.get("optimal") else "no",
                format=(
                    "yes"
                    if result.get("format_adherent") is True
                    else "no"
                    if result.get("format_adherent") is False
                    else "—"
                ),
                lengths=length_cell,
                calls=int(result.get("model_call_count", 0) or 0),
                tokens=f"{int(usage.get('total_tokens', 0) or 0):,}",
                cost=(
                    f"${float(result['estimated_cost_usd']):.6f}"
                    if result.get("estimated_cost_usd") is not None
                    else "—"
                ),
            )
        )
    totals = {
        key: sum(int((result.get("usage") or {}).get(key, 0) or 0) for result in results)
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    }
    lines.extend(
        [
            "",
            f"Setup verified: **{sum(bool(result.get('setup_verified')) for result in results)}/{len(results)}**  ",
            f"Successful: **{sum(bool(result.get('success')) for result in results)}/{len(results)}**  ",
            f"Optimal: **{sum(bool(result.get('optimal')) for result in results)}/{len(results)}**  ",
            (
                "Exact-format adherence: **{}/{}**  ".format(
                    sum(result.get("format_adherent") is True for result in results),
                    sum(result.get("format_adherent") is not None for result in results),
                )
                if any(result.get("format_adherent") is not None for result in results)
                else ""
            ),
            f"Model calls: **{sum(int(result.get('model_call_count', 0) or 0) for result in results):,}**  ",
            f"Total tokens: **{totals['total_tokens']:,}**",
            (
                "Estimated cost: **${:.6f}**".format(
                    sum(
                        float(result.get("estimated_cost_usd") or 0.0)
                        for result in results
                    )
                )
                if any(result.get("estimated_cost_usd") is not None for result in results)
                else ""
            ),
            "",
            "Setup PASS means the pinned reference/declared TDP specification loaded, the mechanism-preserving adapter completed without strategy or call-accounting errors, its audit artifacts were written, and its native score agreed with independent central rescoring. It does not mean the proposed plan solved the task.",
            "",
            "The cloned repositories are provenance references. These cross-domain experiments execute untrained, mechanism-preserving adapters because the upstream systems do not natively expose all three benchmark domains. TDP has no public official repository and is implemented from its published prompts/algorithm.",
            "",
            "LexiCon uses a released-parser-compatible first-fenced-block extraction, strict grounded-action parsing, and exact sequential simulation of its compiled PDDL. Exact response-format adherence is reported separately for direct model responses and never gates semantic success; harness-normalized literature-baseline plans are marked not applicable. The optional verification path's edit-distance grounded-action repair remains disabled, matching the released aggregate-metrics path's exact-action setting. Flat-Hanoi is rescored by its frozen parser, simulator, and BFS optimum.",
            "",
        ]
    )
    return "\n".join(lines)


def execute(args: argparse.Namespace, cases: Sequence[PreparedCase]) -> Tuple[Path, bool]:
    load_env_file(args.env_file)
    credential_name = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "local-transformers": None,
    }[PROVIDER]
    if credential_name and not os.environ.get(credential_name, "").strip():
        raise RunnerError(f"{credential_name} is not configured in {args.env_file}")
    if PROVIDER == "local-transformers":
        _validate_local_transformers_install()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    methods = _selected_baselines(args.baseline)
    campaign_id = args.run_id or f"baseline_setup_smoke_{timestamp}"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", campaign_id):
        raise RunnerError("--run-id may contain only letters, digits, dot, underscore, and hyphen")
    campaign_dir = args.results_dir / campaign_id
    campaign_dir.mkdir(parents=True, exist_ok=False)
    os.environ["MODEL_REQUEST_TIMEOUT_SECONDS"] = str(args.timeout_seconds)
    implementation = _snapshot_implementation(campaign_dir)
    preflight = {
        method: _preflight_baseline(method, cases) for method in methods
    }
    failed_preflight = [
        method for method, audit in preflight.items() if not audit.get("verified")
    ]
    config = {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "created_at": _utc_now(),
        "provider": PROVIDER,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "anthropic_thinking_budget_tokens": ANTHROPIC_THINKING_BUDGET_TOKENS,
        "local_transformers": (
            _local_transformers_config() if PROVIDER == "local-transformers" else None
        ),
        "max_completion_tokens": args.max_output_tokens,
        "baseline_selection": args.baseline,
        "baselines": list(methods),
        "benchmarks": [case.benchmark for case in cases],
        "tasks": [case.task_id for case in cases],
        "condition_count": len(methods) * len(cases),
        "one_call_per_case": methods == ("base",),
        "tools_allowed": False,
        "baseline_config": {
            method: _baseline_config(method)
            for method in methods
            if method != "base"
        },
        "preflight": preflight,
        "implementation": implementation,
        "runner_sha256": _sha256_bytes(SCRIPT_PATH.read_bytes()),
        "dotenv_precedence": "explicit --env-file overrides ambient values",
        "temperature_parameter_sent": False,
        "smoke_protocol_note": (
            "Each selected method runs once on Logistics c=1/id=1, Blocksworld "
            "c=1/id=1, and the selected paper-derived Flat-Hanoi task unless "
            "narrower flags "
            "are supplied. Literature ports may make multiple calls according to "
            "their mechanisms. Calls use the configured per-call token ceiling. "
            "Hosted calls do not send temperature; local Qwen uses its explicitly "
            "recorded generation configuration."
        ),
    }
    _write_json(campaign_dir / "config.json", config)
    _write_text(campaign_dir / "runner_snapshot.py", SCRIPT_PATH.read_text(encoding="utf-8"))
    if failed_preflight:
        _write_json(
            campaign_dir / "preflight_failure.json",
            {"failed_baselines": failed_preflight, "preflight": preflight},
        )
        raise RunnerError(
            "Baseline preflight failed before model inference: "
            + ", ".join(failed_preflight)
        )

    results: List[Dict[str, Any]] = []
    condition_count = len(methods) * len(cases)
    condition_index = 0
    for method in methods:
        for case in cases:
            condition_index += 1
            print(
                f"[{condition_index}/{condition_count}] {BASELINE_DISPLAY_NAMES[method]} | "
                f"{case.benchmark} {case.display_coordinate}: calling {PROVIDER}/{MODEL} "
                f"({REASONING_EFFORT})...",
                flush=True,
            )
            if method == "base":
                result = _run_case(
                    case,
                    campaign_dir=campaign_dir / method,
                    max_output_tokens=args.max_output_tokens,
                    timeout_seconds=args.timeout_seconds,
                )
            elif method == DYNAPLAN_BASELINE:
                result = _run_dynaplan_case(
                    case,
                    campaign_dir=campaign_dir,
                    max_output_tokens=args.max_output_tokens,
                    env_file=args.env_file,
                )
            else:
                result = _run_literature_case(
                    case,
                    method,
                    campaign_dir=campaign_dir,
                    max_output_tokens=args.max_output_tokens,
                )
            evaluation = result.get("evaluation") or {}
            print(
                f"  setup={result.get('setup_status', '—')} | {result['status']} | "
                f"{evaluation.get('submitted_length', '—')} / {evaluation.get('optimal_length', '—')} "
                f"| {int(result.get('model_call_count', 0) or 0)} calls | "
                f"{int((result.get('usage') or {}).get('total_tokens', 0) or 0):,} tokens",
                flush=True,
            )
            results.append(result)

    totals = {
        key: sum(int((result.get("usage") or {}).get(key, 0) or 0) for result in results)
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    }
    summary = {
        **config,
        "completed_at": _utc_now(),
        "attempted": len(results),
        "setup_verified": sum(bool(result.get("setup_verified")) for result in results),
        "successful": sum(bool(result.get("success")) for result in results),
        "optimal": sum(bool(result.get("optimal")) for result in results),
        "format_adherence": {
            "applicable": sum(
                result.get("format_adherent") is not None for result in results
            ),
            "adherent": sum(
                result.get("format_adherent") is True for result in results
            ),
        },
        "model_call_count": sum(
            int(result.get("model_call_count", 0) or 0) for result in results
        ),
        "usage": totals,
        "estimated_cost_usd": round(
            sum(float(result.get("estimated_cost_usd") or 0.0) for result in results),
            8,
        ),
        "results": results,
    }
    _write_json(campaign_dir / "summary.json", summary)
    _write_text(campaign_dir / "summary.md", _summary_markdown(results))
    print(f"Results: {campaign_dir}", flush=True)
    infrastructure_ok = all(bool(result.get("setup_verified")) for result in results)
    return campaign_dir, infrastructure_ok


def self_test() -> None:
    """Exercise task loading, adapters, and exact scorers without API calls."""

    for domain in LEXICON_DOMAINS:
        case = prepare_lexicon_case(domain, 1, 1)
        task_dir = LEXICON_ROOT / "domains" / domain / "data" / "data_1" / "1"
        actions = []
        for line in (task_dir / "constrained_plan").read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                actions.append(stripped[1:-1] if stripped.startswith("(") else stripped)
        result = case.scorer("```\n" + "\n".join(actions) + "\n```")
        if result.get("status") != "OPTIMAL" or result.get("submitted_length") != case.optimum:
            raise RunnerError(f"LexiCon self-test failed for {domain}: {result}")

    case = prepare_flat_hanoi_case("3_00")
    _read, _validate, _render, evaluation_tools = _load_flat_hanoi_modules()
    _evaluate, shortest_path = evaluation_tools
    dataset = FLAT_HANOI_ROOT / "flat_hanoi" / "data" / "paper_baseline_v1.jsonl"
    read_instances, _validate_dataset, _render_messages, _tools = _load_flat_hanoi_modules()
    instance = next(item for item in read_instances(dataset) if item.instance_id == case.task_id)
    moves = shortest_path(instance.start, instance.goal)
    result = case.scorer("moves = " + json.dumps(moves))
    if result.get("status") != "OPTIMAL" or result.get("submitted_length") != case.optimum:
        raise RunnerError(f"Flat-Hanoi self-test failed: {result}")
    native_task = _native_flat_task(case)
    source_target_plan = "\n".join(
        f"MoveHoop(peg_{source}, peg_{target})"
        for _disk, source, target in moves
    )
    numeric_plan, warning = _flat_candidate_as_numeric(case, source_target_plan)
    converted = case.scorer(numeric_plan)
    if warning is not None or converted.get("status") != "OPTIMAL":
        raise RunnerError(
            f"Flat-Hanoi adapter conversion self-test failed: {warning}; {converted}"
        )
    if native_task.optimal_move_count != case.optimum:
        raise RunnerError("Flat-Hanoi adapter optimum disagrees with frozen benchmark")

    smoke_cases = [
        prepare_lexicon_case("logistics", 1, 1),
        prepare_lexicon_case("blocksworld", 1, 1),
        case,
    ]
    audits = {
        baseline: _preflight_baseline(baseline, smoke_cases)
        for baseline in (DYNAPLAN_BASELINE, *LITERATURE_BASELINES)
    }
    failed = [name for name, audit in audits.items() if not audit.get("verified")]
    if failed:
        raise RunnerError(f"Baseline adapter self-test failed: {failed}; {audits}")
    print(
        "Self-test passed: both exact scorers, DynaPlan's three copied-runtime "
        "boundaries, all six reference sources, all 18 literature-baseline/domain "
        "adapter boundaries, and Flat-Hanoi conversion"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the direct method or a mechanism-preserving literature baseline "
            "on a selected Dynaplan benchmark with an explicitly selected model."
        )
    )
    parser.add_argument(
        "--provider",
        choices=("openai", "anthropic", "local-transformers"),
        default="openai",
        help=(
            "Model provider: hosted OpenAI/Anthropic or the in-process local "
            "Transformers backend (default: openai)"
        ),
    )
    parser.add_argument(
        "--model",
        help="Exact provider model ID (provider-specific default if omitted)",
    )
    parser.add_argument(
        "--reasoning",
        default="medium",
        help="Reasoning label recorded for the campaign (default: medium)",
    )
    parser.add_argument(
        "--anthropic-thinking-budget",
        type=int,
        help=(
            "Manual extended-thinking token budget for supported Claude models; "
            "must be at least 1024 and below --max-output-tokens"
        ),
    )
    parser.add_argument(
        "--base-url",
        help="Optional provider endpoint override",
    )
    parser.add_argument(
        "--local-model-path",
        type=Path,
        default=DEFAULT_LOCAL_MODEL_PATH,
        help=(
            "Pinned local Qwen snapshot used by --provider local-transformers "
            f"(default: {DEFAULT_LOCAL_MODEL_PATH})"
        ),
    )
    parser.add_argument(
        "--local-model-revision",
        default=QWEN_MODEL_REVISION,
        help="Recorded Hugging Face revision for the local snapshot",
    )
    parser.add_argument(
        "--local-thinking",
        choices=("on", "off"),
        default="on",
        help="Enable Qwen3.5 thinking in its chat template (default: on)",
    )
    parser.add_argument(
        "--local-seed",
        type=int,
        default=0,
        help="Local generation seed recorded per campaign (default: 0)",
    )
    parser.add_argument(
        "--baseline",
        choices=(*BASELINES, "all-literature", "all"),
        default="base",
        help=(
            "Planning method; all-literature selects AdaPlan-H, TDP, ADaPT, "
            "ReAcTree, AoT+, and LLM+P; all additionally includes base and DynaPlan"
        ),
    )
    parser.add_argument(
        "--benchmark",
        choices=(*BENCHMARKS, "all"),
        default="all",
        help="Benchmark/domain to run; all runs the three smoke cases",
    )
    parser.add_argument(
        "--constraints",
        "--c",
        type=int,
        default=1,
        help="Nominal LexiCon constraint level (default: 1)",
    )
    parser.add_argument(
        "--lexicon-id",
        type=int,
        default=1,
        help="Official LexiCon packed instance ID (default: 1)",
    )
    parser.add_argument(
        "--hanoi-task",
        default="3_00",
        help="Flat-Hanoi alias or canonical instance ID (default: 3_00)",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=MAX_OUTPUT_TOKENS,
        help=f"Maximum completion tokens per call (default: {MAX_OUTPUT_TOKENS})",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout per call (default: {DEFAULT_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"Dotenv file (default: {DEFAULT_ENV_FILE})",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_ROOT,
        help=f"Result root (default: {DEFAULT_RESULTS_ROOT})",
    )
    parser.add_argument("--run-id", help="Optional unique output directory name")
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Run model inference (paid for hosted providers, local for "
            "local-transformers); omitted means validation-only dry run"
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Score frozen oracle plans locally; never contacts an API",
    )
    return parser


def _configure_runtime(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    global PROVIDER, MODEL, REASONING_EFFORT
    global ANTHROPIC_THINKING_BUDGET_TOKENS, BASE_URL_OVERRIDE
    global LOCAL_MODEL_PATH, LOCAL_MODEL_REVISION, LOCAL_ENABLE_THINKING, LOCAL_SEED

    PROVIDER = args.provider
    MODEL = args.model or (
        "claude-haiku-4-5-20251001"
        if PROVIDER == "anthropic"
        else QWEN_MODEL_ID
        if PROVIDER == "local-transformers"
        else "gpt-5.6-luna"
    )
    REASONING_EFFORT = args.reasoning
    ANTHROPIC_THINKING_BUDGET_TOKENS = args.anthropic_thinking_budget
    BASE_URL_OVERRIDE = args.base_url
    LOCAL_MODEL_PATH = args.local_model_path.resolve()
    LOCAL_MODEL_REVISION = args.local_model_revision
    LOCAL_ENABLE_THINKING = args.local_thinking == "on"
    LOCAL_SEED = args.local_seed

    if PROVIDER != "anthropic" and ANTHROPIC_THINKING_BUDGET_TOKENS is not None:
        parser.error("--anthropic-thinking-budget requires --provider anthropic")
    if PROVIDER == "local-transformers":
        if MODEL != QWEN_MODEL_ID:
            parser.error(
                f"local-transformers is pinned to --model {QWEN_MODEL_ID}"
            )
        if LOCAL_MODEL_REVISION != QWEN_MODEL_REVISION:
            parser.error(
                "local-transformers revision must match the registered Qwen "
                f"revision {QWEN_MODEL_REVISION}"
            )
        if BASE_URL_OVERRIDE is not None:
            parser.error("--base-url is not used by local-transformers")
    if PROVIDER == "anthropic":
        if ANTHROPIC_THINKING_BUDGET_TOKENS is None:
            parser.error(
                "A Claude reasoning run requires --anthropic-thinking-budget"
            )
        if ANTHROPIC_THINKING_BUDGET_TOKENS < 1024:
            parser.error("--anthropic-thinking-budget must be at least 1024")
        if ANTHROPIC_THINKING_BUDGET_TOKENS >= args.max_output_tokens:
            parser.error(
                "--anthropic-thinking-budget must be below --max-output-tokens"
            )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_output_tokens < 1:
        parser.error("--max-output-tokens must be positive")
    if args.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")
    _configure_runtime(args, parser)
    try:
        if args.self_test:
            if args.execute:
                raise RunnerError("--self-test and --execute are mutually exclusive")
            self_test()
            return 0
        cases = prepare_cases(args)
        if not args.execute:
            methods = _selected_baselines(args.baseline)
            preflight = {
                method: _preflight_baseline(method, cases) for method in methods
            }
            print(
                f"Dry run: baselines={','.join(methods)}, provider={PROVIDER}, model={MODEL}, "
                f"reasoning={REASONING_EFFORT}"
            )
            for case in cases:
                hashes = _prompt_metadata(case)
                print(
                    f"- {case.benchmark}: {case.display_coordinate}; "
                    f"task={case.task_id}; optimum={case.optimum}; "
                    f"prompt_sha256={hashes['user_sha256']}"
                )
            for method, audit in preflight.items():
                print(
                    f"- setup {method}: "
                    f"{'PASS' if audit.get('verified') else 'FAIL'}"
                )
            failed = [
                method for method, audit in preflight.items() if not audit.get("verified")
            ]
            if failed:
                raise RunnerError("Baseline preflight failed: " + ", ".join(failed))
            print("No model inference performed. Add --execute to run the selected case(s).")
            return 0
        _campaign_dir, infrastructure_ok = execute(args, cases)
        return 0 if infrastructure_ok else 3
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
