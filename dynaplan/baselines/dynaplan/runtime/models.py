from __future__ import annotations

import datetime
import importlib
import json
import os
import re
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_TIMEOUT_SECONDS = 120
BENCHMARK_DIR = Path(__file__).resolve().parent


class TruncatedResponseError(RuntimeError):
    """Raised when a model call's response was cut off before completion.

    finish_reason == "length" (or the provider's equivalent) means the model
    hit max_tokens/context budget mid-response. The output is unusable for
    parsing, so callers should treat this as a distinct failure mode rather
    than feeding a truncated response into a parser and getting a misleading
    generic parse error.
    """

    def __init__(self, message: str, *, output: str = ""):
        super().__init__(message)
        # Preserve the incomplete response for experiment auditing.  Callers
        # must still reject it for parsing/planning.
        self.output = output


def live_log_path() -> Optional[Path]:
    """Opt-in live logging of each completed model call, as it happens.

    Set LIVE_LOG=true (or LIVE_LOG_PATH=<file>) in .env to append one JSON
    line per finished stage to a file you can `tail -f` during a long local
    run, instead of waiting for the run to finish and write steps.json.
    """
    explicit = os.environ.get("LIVE_LOG_PATH", "").strip()
    if explicit:
        return Path(explicit)
    if os.environ.get("LIVE_LOG", "").strip().lower() in {"1", "true", "yes", "on"}:
        return BENCHMARK_DIR / "results" / "live_log.jsonl"
    return None


def append_live_log(record: Dict[str, object]) -> None:
    path = live_log_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"logged_at": datetime.datetime.now().isoformat(timespec="seconds"), **record}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


@dataclass
class ModelCall:
    provider: str
    model: str
    stage: str
    system: str
    prompt: str
    max_tokens: int
    reasoning_effort: Optional[str]
    prompt_char_count: int
    output_char_count: int
    reasoning_char_count: int
    reasoning_content: Optional[str]
    response_schema_name: Optional[str]
    usage: Dict[str, object]
    raw_usage: Dict[str, object]
    thinking_budget_tokens: Optional[int] = None
    truncated: bool = False
    finish_reason: Optional[str] = None
    backend_metadata: Optional[Dict[str, object]] = None


class ModelClient:
    provider = "base"

    def __init__(self, model: str, reasoning_effort: Optional[str] = None):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.call_history: List[ModelCall] = []
        # Provider-specific, JSON-serializable facts about the runtime.  Local
        # clients populate this after their lazy backend is loaded; keeping it
        # on every client gives benchmark launchers a common inspection point.
        self.backend_metadata: Dict[str, object] = {}

    def generate(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        response_schema: Optional[Dict[str, object]] = None,
        schema_name: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> str:
        raise NotImplementedError

    def call_records_since(self, start_index: int) -> List[Dict[str, object]]:
        return [asdict(call) for call in self.call_history[start_index:]]

    def _record_call(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        output: str,
        reasoning_content: Optional[str] = None,
        response_schema_name: Optional[str] = None,
        usage: Optional[Dict[str, object]] = None,
        raw_usage: Optional[Dict[str, object]] = None,
        reasoning_effort: Optional[str] = None,
        thinking_budget_tokens: Optional[int] = None,
        truncated: bool = False,
        finish_reason: Optional[str] = None,
        backend_metadata: Optional[Dict[str, object]] = None,
    ) -> str:
        call = ModelCall(
            provider=self.provider,
            model=self.model,
            stage=infer_stage(system),
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort if reasoning_effort is not None else self.reasoning_effort,
            prompt_char_count=len(prompt),
            output_char_count=len(output),
            reasoning_char_count=len(reasoning_content or ""),
            reasoning_content=reasoning_content,
            response_schema_name=response_schema_name,
            usage=usage or empty_usage("missing"),
            raw_usage=raw_usage or {},
            thinking_budget_tokens=thinking_budget_tokens,
            truncated=truncated,
            finish_reason=finish_reason,
            backend_metadata=(
                dict(backend_metadata)
                if backend_metadata is not None
                else (dict(self.backend_metadata) if self.backend_metadata else None)
            ),
        )
        self.call_history.append(call)
        append_live_log(
            {
                "call_index": len(self.call_history) - 1,
                "provider": call.provider,
                "model": call.model,
                "stage": call.stage,
                "system": call.system,
                "prompt": call.prompt,
                "output": output,
                "reasoning_content": call.reasoning_content,
                "prompt_char_count": call.prompt_char_count,
                "output_char_count": call.output_char_count,
                "reasoning_char_count": call.reasoning_char_count,
                "response_schema_name": call.response_schema_name,
                "usage": call.usage,
                "raw_usage": call.raw_usage,
                "thinking_budget_tokens": call.thinking_budget_tokens,
                "truncated": call.truncated,
                "finish_reason": call.finish_reason,
                "backend_metadata": call.backend_metadata,
                "output_preview": output[:500],
            }
        )
        return output


class MockHanoiClient(ModelClient):
    provider = "mock"

    def generate(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        response_schema: Optional[Dict[str, object]] = None,
        schema_name: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> str:
        stage = system.lower()
        if "outerbot" in stage:
            output = self._outerbot_response()
        # Dynamic (n-level) pipeline stages. Checked before the two-level stages
        # because their system strings also contain "innerbot", "h2", and
        # "planner".
        elif "router" in stage:
            output = self._router_response()
        elif "hierarchyplanner" in stage:
            output = self._dynamic_hierarchy_response(prompt)
        elif "plan only" in stage:
            output = self._plan_only_response(prompt)
        elif "innerbot" in stage:
            output = self._innerbot_response()
        elif "direct" in stage:
            output = self._direct_response(prompt)
        elif "state" in stage:
            output = self._state_response(prompt)
        elif "h2" in stage:
            output = self._h2_response()
        elif "h1" in stage:
            output = self._h1_response()
        elif "planner" in stage or "decision" in stage:
            output = self._decision_response(prompt)
        else:
            output = "```start_flag\n{}\n```end_flag"
        return self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            response_schema_name=schema_name if response_schema else None,
            usage=estimated_usage(system, prompt, output),
            reasoning_effort=reasoning_effort if reasoning_effort is not None else self.reasoning_effort,
        )

    def _task_from_prompt(self, prompt: str) -> Dict[str, object]:
        marker = "TASK_SPEC_JSON:"
        idx = prompt.rfind(marker)
        if idx < 0:
            raise ValueError("Mock model expected TASK_SPEC_JSON in prompt")
        payload = prompt[idx + len(marker):].strip()
        # Extract the first complete JSON object after the marker.
        decoder = json.JSONDecoder()
        task, _ = decoder.raw_decode(payload)
        return task

    def _is_flat_task(self, task: Dict[str, object]) -> bool:
        """A flat (flat-to-flat) task has no privileged source/auxiliary/target
        peg -- flat_prompts.py omits those keys entirely from TASK_SPEC_JSON so
        that tower framing cannot leak into a flat prompt. Their absence is
        therefore the detection signal here.
        """
        return "source_peg" not in task

    def _solve_flat_hanoi(self, task: Dict[str, object]) -> List[tuple[str, str]]:
        """BFS-based legal move sequence for a flat (arbitrary endpoint) task.

        _solve_hanoi below assumes a single source/auxiliary/target peg and
        would emit illegal moves against a flat task's scattered initial and
        goal states, so flat tasks are routed through hanoi_solver's BFS
        instead, which works against any pair of legal states.
        """
        from hanoi_solver import shortest_hanoi_path

        ring_sizes = {ring["name"]: ring["size"] for ring in task["rings"]}
        path = shortest_hanoi_path(task["initial"], task["goal"], ring_sizes)
        if path is None:
            raise ValueError(f"Mock flat solver found no path for task {task.get('id')}")
        return path

    def _state_response(self, prompt: str) -> str:
        task = self._task_from_prompt(prompt)
        goal_relations: Dict[str, List[str]] = {}
        for peg, stack in task["goal"].items():
            for idx, ring in enumerate(stack):
                relations = [f"in(<{peg}>)"]
                if idx > 0:
                    relations.append(f"above(<{stack[idx - 1]}>)")
                goal_relations[f"<{ring}>"] = relations
        state = {
            "goal_spatial_relations": goal_relations,
            "constraint_spatial_relations": {
                "<all_rings>": [
                    "Move one ring at a time",
                    "Only move the top ring of a peg",
                    "Never place a larger ring on top of a smaller ring",
                ]
            },
        }
        return "```start_flag\n" + json.dumps(state, indent=2, sort_keys=True) + "\n```end_flag"

    def _h1_response(self) -> str:
        return """```start_flag
void MoveSingleRing(string source_peg, string target_peg)
{
    MoveCoroutine(source_peg);
    GrabCoroutine();
    MoveCoroutine(target_peg);
    DropCoroutine();
}
```end_flag

```start_mapping
MoveSingleRing(source_peg, target_peg) = [MoveCoroutine(source_peg), GrabCoroutine(), MoveCoroutine(target_peg), DropCoroutine()]
```end_mapping"""

    def _h2_response(self) -> str:
        return """```start_flag
void MoveTwoRingTower(string source_peg, string auxiliary_peg, string target_peg)
{
    MoveSingleRing(source_peg, auxiliary_peg);
    MoveSingleRing(source_peg, target_peg);
    MoveSingleRing(auxiliary_peg, target_peg);
}
```end_flag

```start_mapping
MoveTwoRingTower(source_peg, auxiliary_peg, target_peg) = [MoveSingleRing(source_peg, auxiliary_peg), MoveSingleRing(source_peg, target_peg), MoveSingleRing(auxiliary_peg, target_peg)]
```end_mapping"""

    def _innerbot_response(self) -> str:
        return """```start_result
RESULT: YES
REASON: N/A
```end_result"""

    def _outerbot_response(self) -> str:
        return """```start_error_type
Error : TASK SUCCESS
Reason : N/A
```end_error_type"""

    def _router_response(self) -> str:
        return """```start_result
RESULT: YES
OWNER: NA
REASON: N/A
```end_result"""

    def _plan_only_response(self, prompt: str) -> str:
        task = self._task_from_prompt(prompt)
        if self._is_flat_task(task):
            description = "Rearrange the rings so the scene matches the goal configuration."
        else:
            description = (
                f'Move every ring from {task["source_peg"]} to {task["target_peg"]} '
                f'using {task["auxiliary_peg"]} as the auxiliary peg.'
            )
        return f"""```start_subtask_1
{description}
```end_subtask_1
```start_subtask_goalstate_1
{json.dumps(task["goal"], indent=2, sort_keys=True)}
```end_subtask_goalstate_1"""

    def _dynamic_hierarchy_response(self, prompt: str) -> str:
        """Unrolled tower hierarchy: MoveTowerK is written in terms of MoveTower(K-1).

        Flat tasks have no privileged source/auxiliary/target peg, so there is
        no MoveTowerK template to unroll -- the memorized tower-to-tower
        recursion simply does not apply to an arbitrary (initial, goal) pair.
        The mock instead emits one flat mapping enumerating the BFS-found
        moves directly, mirroring what a model without a memorized template
        would have to produce.
        """
        task = self._task_from_prompt(prompt)
        if self._is_flat_task(task):
            moves = self._solve_flat_hanoi(task)
            calls = ", ".join(f"MoveSingleRing({source}, {target})" for source, target in moves)
            return f"""```start_mapping
SolveFlatHanoi() = [{calls}]
```end_mapping

```start_subtask_funcs_1
SolveFlatHanoi()
```end_subtask_funcs_1"""

        level = len(task["rings"])
        lines = ["MoveTower1(src, aux, dst) = [MoveSingleRing(src, dst)]"]
        for current in range(2, level + 1):
            below = current - 1
            lines.append(
                f"MoveTower{current}(src, aux, dst) = ["
                f"MoveTower{below}(src, dst, aux), "
                f"MoveSingleRing(src, dst), "
                f"MoveTower{below}(aux, src, dst)]"
            )
        mapping_block = ",\n".join(lines)
        call = (
            f"MoveTower{level}({task['source_peg']}, "
            f"{task['auxiliary_peg']}, {task['target_peg']})"
        )
        return f"""```start_mapping
{mapping_block}
```end_mapping

```start_subtask_funcs_1
{call}
```end_subtask_funcs_1"""

    def _decision_response(self, prompt: str) -> str:
        task = self._task_from_prompt(prompt)
        if self._is_flat_task(task):
            moves = self._solve_flat_hanoi(task)
            description = "Rearrange the rings so the scene matches the goal configuration."
        else:
            moves = []
            self._solve_hanoi(
                n=len(task["rings"]),
                source=task["source_peg"],
                auxiliary=task["auxiliary_peg"],
                target=task["target_peg"],
                moves=moves,
            )
            description = f'Move all rings from {task["source_peg"]} to {task["target_peg"]}.'
        function_block = "\n".join(self._hierarchy_calls_from_moves(moves))
        return f"""```start_subtask_1
{description}
```start_subtask_goalstate_1
{json.dumps(task["goal"], indent=2)}
```end_subtask_goalstate_1
```start_subtask_funcs_1
{function_block}
```end_subtask_funcs_1
```end_subtask_1

```start_all_functions
{function_block}
```end_all_functions"""

    def _direct_response(self, prompt: str) -> str:
        task = self._task_from_prompt(prompt)
        if self._is_flat_task(task):
            moves = self._solve_flat_hanoi(task)
            function_block = "\n".join(f"MoveHoop({source}, {target})" for source, target in moves)
            return f"""```start_all_functions
{function_block}
```end_all_functions"""
        moves: List[str] = []
        self._solve_hanoi(
            n=len(task["rings"]),
            source=task["source_peg"],
            auxiliary=task["auxiliary_peg"],
            target=task["target_peg"],
            moves=moves,
        )
        function_block = "\n".join(f"MoveHoop({source}, {target})" for source, target in moves)
        return f"""```start_all_functions
{function_block}
```end_all_functions"""

    def _solve_hanoi(
        self,
        n: int,
        source: str,
        auxiliary: str,
        target: str,
        moves: List[tuple[str, str]],
    ) -> None:
        if n == 0:
            return
        self._solve_hanoi(n - 1, source, target, auxiliary, moves)
        moves.append((source, target))
        self._solve_hanoi(n - 1, auxiliary, source, target, moves)

    def _hierarchy_calls_from_moves(self, moves: List[tuple[str, str]]) -> List[str]:
        calls: List[str] = []
        idx = 0
        while idx < len(moves):
            if idx + 2 < len(moves):
                first_source, first_target = moves[idx]
                second_source, second_target = moves[idx + 1]
                third_source, third_target = moves[idx + 2]
                is_two_ring_tower = (
                    first_source == second_source
                    and first_target == third_source
                    and second_target == third_target
                    and len({first_source, first_target, second_target}) == 3
                )
                if is_two_ring_tower:
                    calls.append(f"MoveTwoRingTower({first_source}, {first_target}, {second_target})")
                    idx += 3
                    continue
            source, target = moves[idx]
            calls.append(f"MoveSingleRing({source}, {target})")
            idx += 1
        return calls


@dataclass(frozen=True)
class _LocalTransformersBackendSpec:
    """Everything that can change the process-global set of loaded weights."""

    source: str
    revision: Optional[str]
    local_files_only: bool


@dataclass
class _LocalTransformersGeneration:
    text: str
    input_tokens: int
    output_tokens: int
    finish_reason: str
    truncated: bool


@dataclass
class _LocalTransformersBackend:
    """Loaded text-only Qwen backend.

    Heavy modules are deliberately stored as opaque objects.  Merely importing
    ``benchmarking.models`` therefore never imports torch, transformers, or
    bitsandbytes and never initializes CUDA.
    """

    torch: Any
    transformers: Any
    tokenizer: Any
    model: Any
    metadata: Dict[str, object]
    inference_lock: threading.Lock = field(default_factory=threading.Lock)

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        token_ids = self.tokenizer.encode(text, add_special_tokens=False)
        return len(token_ids)

    def generate(
        self,
        messages: List[Dict[str, str]],
        *,
        max_new_tokens: int,
        enable_thinking: bool,
        generation_options: Dict[str, object],
        seed: int,
    ) -> _LocalTransformersGeneration:
        try:
            encoded = self.tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                enable_thinking=enable_thinking,
                return_tensors="pt",
                return_dict=True,
            )
        except TypeError as error:
            raise RuntimeError(
                "The installed Qwen3.5 tokenizer/chat template does not accept "
                "enable_thinking; refusing to silently change the prompt contract"
            ) from error

        device = self.model.device
        if hasattr(encoded, "to"):
            encoded = encoded.to(device)
        else:
            encoded = {
                key: value.to(device) if hasattr(value, "to") else value
                for key, value in encoded.items()
            }
        input_ids = encoded["input_ids"]
        # This client submits exactly one conversation at a time.
        input_tokens = int(input_ids.shape[-1])

        options = dict(generation_options)
        presence_penalty = float(options.pop("presence_penalty", 0.0))
        if presence_penalty:
            processor = _GeneratedPresencePenalty(
                torch_module=self.torch,
                prompt_length=input_tokens,
                penalty=presence_penalty,
            )
            options["logits_processor"] = self.transformers.LogitsProcessorList(
                [processor]
            )

        # Generation is serialized per loaded model.  Besides avoiding unsafe
        # concurrent access to one CUDA module, fork_rng makes sampled mode
        # reproducible without leaking its seed into the rest of the process.
        with self.inference_lock:
            with self.torch.random.fork_rng(devices=[0]):
                self.torch.manual_seed(seed)
                self.torch.cuda.manual_seed_all(seed)
                with self.torch.inference_mode():
                    sequences = self.model.generate(
                        **encoded,
                        max_new_tokens=max_new_tokens,
                        **options,
                    )

        generated_ids = sequences[0, input_tokens:]
        generated_token_ids = generated_ids.tolist()
        output_tokens = len(generated_token_ids)
        eos_ids = _local_eos_token_ids(self.tokenizer, self.model)
        ended_with_eos = bool(
            generated_token_ids and int(generated_token_ids[-1]) in eos_ids
        )
        truncated = output_tokens >= max_new_tokens and not ended_with_eos
        finish_reason = "length" if truncated else ("eos_token" if ended_with_eos else "stop")
        text = self.tokenizer.decode(
            generated_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
        return _LocalTransformersGeneration(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish_reason,
            truncated=truncated,
        )


class _GeneratedPresencePenalty:
    """Transformers-compatible presence penalty over generated tokens only."""

    def __init__(self, *, torch_module: Any, prompt_length: int, penalty: float):
        self._torch = torch_module
        self._prompt_length = prompt_length
        self._penalty = penalty

    def __call__(self, input_ids: Any, scores: Any) -> Any:
        generated = input_ids[:, self._prompt_length :]
        if generated.shape[-1] == 0:
            return scores
        for row_index in range(generated.shape[0]):
            appeared = self._torch.unique(generated[row_index])
            scores[row_index, appeared] -= self._penalty
        return scores


_LOCAL_TRANSFORMERS_BACKEND_CACHE: Dict[
    _LocalTransformersBackendSpec, _LocalTransformersBackend
] = {}
_LOCAL_TRANSFORMERS_BACKEND_CACHE_LOCK = threading.Lock()


def _clear_local_transformers_backend_cache() -> None:
    """Test hook. Production code should retain the cache for the whole process."""

    with _LOCAL_TRANSFORMERS_BACKEND_CACHE_LOCK:
        _LOCAL_TRANSFORMERS_BACKEND_CACHE.clear()


def _get_local_transformers_backend(
    spec: _LocalTransformersBackendSpec,
) -> _LocalTransformersBackend:
    with _LOCAL_TRANSFORMERS_BACKEND_CACHE_LOCK:
        backend = _LOCAL_TRANSFORMERS_BACKEND_CACHE.get(spec)
        if backend is None:
            backend = _load_local_transformers_backend(spec)
            _LOCAL_TRANSFORMERS_BACKEND_CACHE[spec] = backend
        return backend


def _load_local_transformers_backend(
    spec: _LocalTransformersBackendSpec,
) -> _LocalTransformersBackend:
    """Load an official Qwen3.5 causal-LM checkpoint as strict NF4 4-bit."""

    try:
        torch = importlib.import_module("torch")
    except (ImportError, OSError) as error:
        raise RuntimeError("provider=local-transformers requires PyTorch") from error
    if not torch.cuda.is_available():
        raise RuntimeError(
            "provider=local-transformers requires CUDA; CPU/full-precision fallback is disabled"
        )
    is_bf16_supported = getattr(torch.cuda, "is_bf16_supported", None)
    if not callable(is_bf16_supported) or not is_bf16_supported():
        raise RuntimeError(
            "provider=local-transformers requires a CUDA GPU with BF16 support"
        )

    try:
        transformers = importlib.import_module("transformers")
        bitsandbytes = importlib.import_module("bitsandbytes")
        accelerate = importlib.import_module("accelerate")
    except (ImportError, OSError) as error:
        raise RuntimeError(
            "provider=local-transformers requires transformers, accelerate, and bitsandbytes"
        ) from error

    qwen_class = getattr(transformers, "Qwen3_5ForCausalLM", None)
    quantization_class = getattr(transformers, "BitsAndBytesConfig", None)
    tokenizer_class = getattr(transformers, "AutoTokenizer", None)
    if qwen_class is None:
        raise RuntimeError(
            "Installed transformers lacks Qwen3_5ForCausalLM; refusing the multimodal "
            "AutoModel fallback"
        )
    if quantization_class is None or tokenizer_class is None:
        raise RuntimeError(
            "Installed transformers lacks BitsAndBytesConfig or AutoTokenizer"
        )

    quantization_config = quantization_class(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    load_kwargs: Dict[str, object] = {
        "trust_remote_code": False,
        "local_files_only": spec.local_files_only,
        "quantization_config": quantization_config,
        "device_map": {"": 0},
        "dtype": torch.bfloat16,
        "low_cpu_mem_usage": True,
    }
    tokenizer_kwargs: Dict[str, object] = {
        "trust_remote_code": False,
        "local_files_only": spec.local_files_only,
        "use_fast": True,
    }
    if spec.revision is not None:
        load_kwargs["revision"] = spec.revision
        tokenizer_kwargs["revision"] = spec.revision

    try:
        tokenizer = tokenizer_class.from_pretrained(spec.source, **tokenizer_kwargs)
        model = qwen_class.from_pretrained(spec.source, **load_kwargs)
    except Exception as error:
        raise RuntimeError(
            f"Failed to load text-only NF4 Qwen3.5 backend from {spec.source!r}: {error}"
        ) from error

    if not isinstance(model, qwen_class):
        raise RuntimeError(
            "Loaded checkpoint did not produce Qwen3_5ForCausalLM; refusing fallback"
        )
    if not bool(getattr(model, "is_loaded_in_4bit", False)):
        raise RuntimeError(
            "Qwen3.5 checkpoint is not marked is_loaded_in_4bit; refusing to run"
        )
    model_device = getattr(model, "device", None)
    if model_device is None or getattr(model_device, "type", str(model_device).split(":")[0]) != "cuda":
        raise RuntimeError("Qwen3.5 model was not placed entirely on CUDA")
    device_map = getattr(model, "hf_device_map", {}) or {}
    for placement in device_map.values():
        normalized = str(placement).lower()
        if normalized == "cpu" or normalized == "disk":
            raise RuntimeError(
                "Qwen3.5 model contains CPU/disk-offloaded modules; refusing mixed-device run"
            )

    model.eval()
    config = getattr(model, "config", None)
    resolved_revision = getattr(config, "_commit_hash", None) or spec.revision
    metadata: Dict[str, object] = {
        "loaded": True,
        "backend": "transformers_in_process",
        "model_source": spec.source,
        "source_kind": "local_snapshot" if spec.local_files_only else "huggingface_hub",
        "requested_revision": spec.revision,
        "resolved_revision": resolved_revision,
        "model_class": type(model).__name__,
        "text_only": True,
        "trust_remote_code": False,
        "quantization": "bitsandbytes_nf4",
        "load_in_4bit": True,
        "double_quant": True,
        "compute_dtype": "bfloat16",
        "device": str(model_device),
        "cuda_device_name": str(torch.cuda.get_device_name(0)),
        "transformers_version": str(getattr(transformers, "__version__", "unknown")),
        "torch_version": str(getattr(torch, "__version__", "unknown")),
        "bitsandbytes_version": str(getattr(bitsandbytes, "__version__", "unknown")),
        "accelerate_version": str(getattr(accelerate, "__version__", "unknown")),
        "usage_source": "local_exact",
    }
    memory_footprint = getattr(model, "get_memory_footprint", None)
    if callable(memory_footprint):
        metadata["model_memory_footprint_bytes"] = int(memory_footprint())
    return _LocalTransformersBackend(
        torch=torch,
        transformers=transformers,
        tokenizer=tokenizer,
        model=model,
        metadata=metadata,
    )


def _local_eos_token_ids(tokenizer: Any, model: Any) -> set[int]:
    values: List[object] = [getattr(tokenizer, "eos_token_id", None)]
    generation_config = getattr(model, "generation_config", None)
    values.append(getattr(generation_config, "eos_token_id", None))
    result: set[int] = set()
    for value in values:
        if isinstance(value, (list, tuple, set)):
            result.update(int(item) for item in value if item is not None)
        elif value is not None:
            result.add(int(value))
    return result


def _split_qwen_reasoning(
    text: str, *, enable_thinking: bool
) -> tuple[str, Optional[str], bool]:
    """Return (usable answer, reasoning, unclosed-thinking-truncation)."""

    closing = "</think>"
    opening = "<think>"
    if closing in text:
        reasoning_region, answer = text.split(closing, 1)
        if opening in reasoning_region:
            reasoning_region = reasoning_region.rsplit(opening, 1)[1]
        return answer.lstrip("\r\n"), reasoning_region.strip() or None, False
    if opening in text:
        reasoning_region = text.rsplit(opening, 1)[1]
        return "", reasoning_region.strip() or None, True
    if enable_thinking:
        # Qwen's thinking template opens <think> in the assistant generation
        # prefix, so that opening marker normally is not part of decoded new
        # tokens.  Absence of the required closing marker means the model never
        # reached a usable answer, even if it happened to emit EOS early.
        return "", text.strip() or None, True
    return text, None, False


def _schema_prompt_suffix(
    response_schema: Dict[str, object], schema_name: Optional[str]
) -> str:
    name = schema_name or "benchmark_output"
    return (
        "\n\nYour response must conform to the following JSON Schema. This is a "
        "prompt instruction only; the local provider does not use constrained decoding.\n"
        f"Schema name: {name}\n"
        f"JSON Schema: {json.dumps(response_schema, sort_keys=True, separators=(',', ':'))}"
    )


def _strict_env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _optional_env_float(name: str) -> Optional[float]:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else None


def _optional_env_int(name: str) -> Optional[int]:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else None


class LocalTransformersQwenClient(ModelClient):
    """In-process, text-only, true-4-bit Qwen3.5 benchmark client."""

    provider = "local-transformers"
    OFFICIAL_MODEL = "Qwen/Qwen3.5-4B"

    def __init__(
        self,
        model: str = OFFICIAL_MODEL,
        *,
        model_path: Optional[str] = None,
        revision: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        enable_thinking: bool = True,
        sampling_mode: str = "recommended",
        seed: int = 0,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        min_p: Optional[float] = None,
        presence_penalty: Optional[float] = None,
    ):
        super().__init__(model=model, reasoning_effort=reasoning_effort)
        if model != self.OFFICIAL_MODEL:
            raise ValueError(
                f"provider=local-transformers is pinned to {self.OFFICIAL_MODEL!r}; "
                f"received {model!r}"
            )
        source_value = (model_path or model).strip()
        if not source_value:
            raise ValueError("model_path must not be empty")
        normalized_revision = revision.strip() if revision and revision.strip() else None
        source_path = Path(source_value).expanduser()
        explicit_local_path = source_path.is_absolute() or source_value.startswith(("./", "../", "~"))
        if source_path.exists():
            if not source_path.is_dir():
                raise ValueError("LOCAL_TRANSFORMERS_MODEL_PATH must name a directory")
            source = str(source_path.resolve())
            local_files_only = True
        else:
            if explicit_local_path:
                raise ValueError(
                    f"LOCAL_TRANSFORMERS_MODEL_PATH does not exist: {source_path}"
                )
            source = source_value
            local_files_only = False
            if source != self.OFFICIAL_MODEL:
                raise ValueError(
                    "Remote LOCAL_TRANSFORMERS_MODEL_PATH must be the official "
                    f"repository {self.OFFICIAL_MODEL!r}"
                )
            if not normalized_revision or re.fullmatch(
                r"[0-9a-fA-F]{40}", normalized_revision
            ) is None:
                raise ValueError(
                    "A pinned 40-hex LOCAL_TRANSFORMERS_REVISION is required when "
                    "loading Qwen3.5 from the Hub"
                )
        self.backend_spec = _LocalTransformersBackendSpec(
            source=source,
            revision=normalized_revision,
            local_files_only=local_files_only,
        )
        mode = sampling_mode.strip().lower()
        if mode not in {"deterministic", "recommended"}:
            raise ValueError(
                "LOCAL_TRANSFORMERS_SAMPLING_MODE must be deterministic or recommended"
            )
        self.enable_thinking = bool(enable_thinking)
        self.sampling_mode = mode
        self.seed = int(seed)
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.min_p = min_p
        self.presence_penalty = presence_penalty
        if self.temperature is not None and self.temperature <= 0:
            raise ValueError("LOCAL_TRANSFORMERS_TEMPERATURE must be greater than zero")
        if self.top_p is not None and not 0 < self.top_p <= 1:
            raise ValueError("LOCAL_TRANSFORMERS_TOP_P must be in (0, 1]")
        if self.top_k is not None and self.top_k <= 0:
            raise ValueError("LOCAL_TRANSFORMERS_TOP_K must be positive")
        if self.min_p is not None and not 0 <= self.min_p <= 1:
            raise ValueError("LOCAL_TRANSFORMERS_MIN_P must be in [0, 1]")
        self.backend_metadata = {
            "loaded": False,
            "backend": "transformers_in_process",
            "canonical_model": model,
            "model_source": source,
            "source_kind": "local_snapshot" if local_files_only else "huggingface_hub",
            "requested_revision": self.backend_spec.revision,
            "model_class": "Qwen3_5ForCausalLM",
            "text_only": True,
            "trust_remote_code": False,
            "quantization": "bitsandbytes_nf4",
            "load_in_4bit": True,
            "double_quant": True,
            "compute_dtype": "bfloat16",
            "enable_thinking": self.enable_thinking,
            "sampling_mode": self.sampling_mode,
            "seed": self.seed,
            "response_schema_mode": "prompt_only",
            "usage_source": "local_exact",
        }
        self.last_generation_metadata: Dict[str, object] = {}

    def _backend(self) -> _LocalTransformersBackend:
        backend = _get_local_transformers_backend(self.backend_spec)
        configured = {
            "enable_thinking": self.enable_thinking,
            "sampling_mode": self.sampling_mode,
            "seed": self.seed,
            "response_schema_mode": "prompt_only",
        }
        self.backend_metadata = {**backend.metadata, **configured, "canonical_model": self.model}
        return backend

    def _generation_options(self) -> Dict[str, object]:
        if self.sampling_mode == "deterministic":
            if any(
                value is not None
                for value in (self.temperature, self.top_p, self.top_k, self.min_p)
            ):
                raise ValueError(
                    "Sampling parameters cannot be set in deterministic mode"
                )
            options: Dict[str, object] = {"do_sample": False}
        else:
            # Qwen's published recommendations differ slightly between
            # thinking and non-thinking mode.
            options = {
                "do_sample": True,
                "temperature": self.temperature
                if self.temperature is not None
                else (0.6 if self.enable_thinking else 0.7),
                "top_p": self.top_p
                if self.top_p is not None
                else (0.95 if self.enable_thinking else 0.8),
                "top_k": self.top_k if self.top_k is not None else 20,
            }
            if self.min_p is not None:
                options["min_p"] = self.min_p
        if self.presence_penalty is not None:
            options["presence_penalty"] = self.presence_penalty
        return options

    def generate(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        response_schema: Optional[Dict[str, object]] = None,
        schema_name: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> str:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        effective_prompt = prompt
        if response_schema is not None:
            effective_prompt += _schema_prompt_suffix(response_schema, schema_name)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": effective_prompt},
        ]
        backend = self._backend()
        generation_options = self._generation_options()
        generated = backend.generate(
            messages,
            max_new_tokens=max_tokens,
            enable_thinking=self.enable_thinking,
            generation_options=generation_options,
            seed=self.seed,
        )
        output, reasoning_content, unclosed_thinking = _split_qwen_reasoning(
            generated.text,
            enable_thinking=self.enable_thinking,
        )
        truncated = generated.truncated or unclosed_thinking
        finish_reason = "unclosed_think" if unclosed_thinking and not generated.truncated else generated.finish_reason
        reasoning_tokens = backend.count_tokens(reasoning_content or "")
        usage = empty_usage("local_exact")
        usage.update(
            {
                "input_tokens": generated.input_tokens,
                "output_tokens": generated.output_tokens,
                "total_tokens": generated.input_tokens + generated.output_tokens,
                "reasoning_tokens": reasoning_tokens,
            }
        )
        raw_usage: Dict[str, object] = {
            "input_tokens": generated.input_tokens,
            "generated_tokens": generated.output_tokens,
            "visible_output_tokens": backend.count_tokens(output),
            "reasoning_tokens": reasoning_tokens,
            "reasoning_token_count_method": "retokenized_visible_reasoning",
            "finish_reason": finish_reason,
        }
        call_backend_metadata = {
            **self.backend_metadata,
            "generation_options": generation_options,
            "response_schema_mode": "prompt_only" if response_schema is not None else "none",
        }
        effective_reasoning_effort = (
            reasoning_effort if reasoning_effort is not None else self.reasoning_effort
        )
        self.last_generation_metadata = {
            "finish_reason": finish_reason,
            "truncated": truncated,
            "input_tokens": generated.input_tokens,
            "output_tokens": generated.output_tokens,
            "generation_options": dict(generation_options),
        }
        self._record_call(
            system=system,
            prompt=effective_prompt,
            max_tokens=max_tokens,
            output=output,
            reasoning_content=reasoning_content,
            response_schema_name=(schema_name or "benchmark_output")
            if response_schema is not None
            else None,
            usage=usage,
            raw_usage=raw_usage,
            reasoning_effort=effective_reasoning_effort,
            truncated=truncated,
            finish_reason=finish_reason,
            backend_metadata=call_backend_metadata,
        )
        if truncated:
            raise TruncatedResponseError(
                f"Local Qwen response truncated (finish_reason={finish_reason!r}) at "
                f"stage {infer_stage(system)!r}; output is incomplete and unusable",
                output=output,
            )
        return output


class OpenAICompatibleClient(ModelClient):
    provider = "openai-compatible"

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "",
        token_limit_field: str = "max_tokens",
        include_temperature: bool = True,
        reasoning_effort: Optional[str] = None,
        include_reasoning_effort: bool = False,
        include_response_schema: bool = False,
        extra_options: Optional[Dict[str, object]] = None,
        temperature: Optional[float] = None,
    ):
        super().__init__(model, reasoning_effort=reasoning_effort)
        self.base_url = base_url
        self.api_key = api_key
        self.token_limit_field = token_limit_field
        self.include_temperature = include_temperature
        self.include_reasoning_effort = include_reasoning_effort
        self.include_response_schema = include_response_schema
        self.extra_options = extra_options
        self.temperature = temperature

    def generate(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        response_schema: Optional[Dict[str, object]] = None,
        schema_name: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> str:
        effective_reasoning_effort = (
            reasoning_effort if reasoning_effort is not None else self.reasoning_effort
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            self.token_limit_field: max_tokens,
        }
        if self.include_temperature:
            payload["temperature"] = self.temperature if self.temperature is not None else 0
        if effective_reasoning_effort and (self.include_reasoning_effort or reasoning_effort is not None):
            payload["reasoning_effort"] = effective_reasoning_effort
        if response_schema is not None and self.include_response_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name or "benchmark_output",
                    "strict": True,
                    "schema": response_schema,
                },
            }
        if self.extra_options:
            payload["options"] = self.extra_options
        response = post_json(self.base_url, payload, self._headers())
        choice = response["choices"][0]
        message = choice["message"]
        output = message.get("content") or ""
        # OpenAI-style servers use "reasoning_content"; Ollama uses "reasoning".
        reasoning_content = message.get("reasoning_content") or message.get("reasoning")
        finish_reason = choice.get("finish_reason")
        truncated = finish_reason in {"length", "max_tokens"}
        self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            reasoning_content=reasoning_content if isinstance(reasoning_content, str) else None,
            response_schema_name=(schema_name or "benchmark_output")
            if response_schema is not None and self.include_response_schema
            else None,
            usage=normalize_openai_usage(response),
            raw_usage=response.get("usage", {}),
            reasoning_effort=effective_reasoning_effort,
            truncated=truncated,
        )
        if truncated:
            raise TruncatedResponseError(
                f"Response truncated (finish_reason={finish_reason!r}) at stage "
                f"{infer_stage(system)!r} — output is incomplete and unusable for parsing.",
                output=output,
            )
        return output

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


_ANTHROPIC_MANUAL_THINKING_PREFIXES = (
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-opus-4-5",
)
_ANTHROPIC_ADAPTIVE_THINKING_PREFIXES = (
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-fable-5",
    "claude-mythos-5",
)
_ANTHROPIC_MANUAL_BUDGETS = {
    "minimal": 1024,
    "low": 1024,
    "medium": 4096,
    "high": 8192,
    "xhigh": 16384,
    "max": 32768,
}

_ANTHROPIC_UNSUPPORTED_SCHEMA_ANNOTATIONS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minProperties",
        "maxProperties",
    }
)


def _anthropic_compatible_schema(value: object) -> object:
    """Adapt a strict schema without weakening its model-visible contract.

    Anthropic structured outputs reject the validation annotations below and
    reject ``type`` arrays combined with mixed-type enums.  Keep the former as
    plain-language schema descriptions, normalize the latter to ``anyOf``, and
    leave the unchanged local parser as the final authority.
    """

    if isinstance(value, dict):
        adapted = {
            key: _anthropic_compatible_schema(item)
            for key, item in value.items()
            if key not in _ANTHROPIC_UNSUPPORTED_SCHEMA_ANNOTATIONS
        }
        constraints = [
            f"{key}={value[key]!r}"
            for key in sorted(_ANTHROPIC_UNSUPPORTED_SCHEMA_ANNOTATIONS)
            if key in value
        ]
        if constraints:
            suffix = (
                "Post-generation validation requirement(s): "
                + ", ".join(constraints)
                + "."
            )
            existing = adapted.get("description")
            adapted["description"] = (
                f"{existing.rstrip()} {suffix}" if isinstance(existing, str) else suffix
            )

        declared_types = value.get("type")
        enum_values = value.get("enum")
        if isinstance(declared_types, list) and isinstance(enum_values, list):
            branches = []
            for declared_type in declared_types:
                matching = [
                    item
                    for item in enum_values
                    if _json_value_has_type(item, declared_type)
                ]
                if matching:
                    branches.append({"type": declared_type, "enum": matching})
            if branches:
                adapted.pop("type", None)
                adapted.pop("enum", None)
                adapted["anyOf"] = branches
        return adapted
    if isinstance(value, list):
        return [_anthropic_compatible_schema(item) for item in value]
    return value


def _json_value_has_type(value: object, declared_type: object) -> bool:
    """Return whether a JSON value belongs to one JSON-Schema primitive type."""

    if declared_type == "null":
        return value is None
    if declared_type == "boolean":
        return isinstance(value, bool)
    if declared_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared_type == "string":
        return isinstance(value, str)
    if declared_type == "array":
        return isinstance(value, list)
    if declared_type == "object":
        return isinstance(value, dict)
    return False


class AnthropicClient(ModelClient):
    provider = "anthropic"

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        reasoning_effort: Optional[str] = None,
        thinking_budget_tokens: Optional[int] = None,
    ):
        super().__init__(model, reasoning_effort=reasoning_effort)
        self.api_key = api_key
        self.base_url = base_url
        self.thinking_budget_tokens = thinking_budget_tokens
        self.backend_metadata.update(
            {
                "structured_output_schema_adapter": (
                    "preserve-validation-contract-and-normalize-nullable-enums-v3"
                ),
                "schema_semantic_validation_retained_in_parser": True,
            }
        )

    def _thinking_configuration(
        self, effective_effort: Optional[str], max_tokens: int
    ) -> tuple[Optional[Dict[str, object]], Optional[str], Optional[int]]:
        effort = (effective_effort or "").strip().lower()
        explicit_budget = self.thinking_budget_tokens
        wants_reasoning = bool(effort and effort not in {"none", "off"}) or explicit_budget is not None
        if not wants_reasoning:
            return None, None, None

        if self.model.startswith(_ANTHROPIC_MANUAL_THINKING_PREFIXES):
            budget = explicit_budget
            if budget is None:
                try:
                    budget = _ANTHROPIC_MANUAL_BUDGETS[effort]
                except KeyError as error:
                    raise ValueError(
                        "Claude 4.5 manual thinking requires a supported reasoning "
                        "label or ANTHROPIC_THINKING_BUDGET_TOKENS"
                    ) from error
            if budget < 1024:
                raise ValueError("Anthropic thinking budget must be at least 1024 tokens")
            if budget >= max_tokens:
                raise ValueError(
                    "Anthropic thinking budget must be smaller than max_tokens "
                    f"({budget} >= {max_tokens})"
                )
            return {"type": "enabled", "budget_tokens": budget}, None, budget

        if self.model.startswith(_ANTHROPIC_ADAPTIVE_THINKING_PREFIXES):
            if explicit_budget is not None:
                raise ValueError(
                    f"{self.model} uses adaptive thinking and does not accept a manual budget"
                )
            if effort not in {"low", "medium", "high", "xhigh", "max"}:
                raise ValueError(f"Unsupported Anthropic adaptive-thinking effort: {effort!r}")
            return {"type": "adaptive"}, effort, None

        raise ValueError(
            f"Reasoning was requested for unsupported or unrecognized Anthropic model {self.model!r}"
        )

    def generate(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        response_schema: Optional[Dict[str, object]] = None,
        schema_name: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> str:
        effective_reasoning_effort = (
            reasoning_effort if reasoning_effort is not None else self.reasoning_effort
        )
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        thinking, adaptive_effort, thinking_budget = self._thinking_configuration(
            effective_reasoning_effort, max_tokens
        )
        if thinking is not None:
            payload["thinking"] = thinking
        if response_schema is not None:
            payload["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": _anthropic_compatible_schema(response_schema),
                }
            }
        if adaptive_effort is not None:
            output_config = payload.setdefault("output_config", {})
            assert isinstance(output_config, dict)
            output_config["effort"] = adaptive_effort
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        response = post_json(self.base_url, payload, headers)
        parts = response.get("content", [])
        output = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
        reasoning_content = "\n".join(
            str(part.get("thinking", ""))
            for part in parts
            if part.get("type") == "thinking" and part.get("thinking")
        )
        stop_reason = response.get("stop_reason")
        truncated = stop_reason in {"max_tokens", "model_context_window_exceeded"}
        self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            reasoning_content=reasoning_content or None,
            response_schema_name=(schema_name or "benchmark_output")
            if response_schema is not None
            else None,
            usage=normalize_anthropic_usage(response),
            raw_usage=response.get("usage", {}),
            reasoning_effort=effective_reasoning_effort,
            thinking_budget_tokens=thinking_budget,
            truncated=truncated,
        )
        if truncated:
            raise TruncatedResponseError(
                f"Response truncated (stop_reason={stop_reason!r}) at stage "
                f"{infer_stage(system)!r} — output is incomplete and unusable for parsing.",
                output=output,
            )
        return output


class GeminiClient(ModelClient):
    provider = "gemini"

    def __init__(self, model: str, api_key: str, base_url: str, reasoning_effort: Optional[str] = None):
        super().__init__(model, reasoning_effort=reasoning_effort)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def generate(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        response_schema: Optional[Dict[str, object]] = None,
        schema_name: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": max_tokens,
            },
        }
        if response_schema is not None:
            generation_config = payload["generationConfig"]
            assert isinstance(generation_config, dict)
            if self.model.lower().startswith("gemini-3"):
                generation_config["responseFormat"] = {
                    "text": {
                        "mimeType": "application/json",
                        "schema": response_schema,
                    }
                }
            else:
                generation_config["responseMimeType"] = "application/json"
                generation_config["responseSchema"] = response_schema
        response = post_json(url, payload, {"Content-Type": "application/json"})
        candidates = response.get("candidates", [])
        finish_reason = None
        if not candidates:
            output = ""
        else:
            parts = candidates[0].get("content", {}).get("parts", [])
            output = "".join(part.get("text", "") for part in parts)
            finish_reason = candidates[0].get("finishReason")
        truncated = finish_reason == "MAX_TOKENS"
        self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            response_schema_name=(schema_name or "benchmark_output")
            if response_schema is not None
            else None,
            usage=normalize_gemini_usage(response),
            raw_usage=response.get("usageMetadata", {}),
            truncated=truncated,
        )
        if truncated:
            raise TruncatedResponseError(
                f"Response truncated (finishReason={finish_reason!r}) at stage "
                f"{infer_stage(system)!r} — output is incomplete and unusable for parsing.",
                output=output,
            )
        return output


def infer_stage(system: str) -> str:
    value = system.lower()
    if "rulesbot" in value:
        return "rulesbot"
    if "router" in value:
        return "innerbot_router"
    if "hierarchyplanner" in value:
        return "hierarchy_planner"
    if "innerbot" in value and "state" in value:
        return "innerbot_state"
    if "innerbot" in value and "plan" in value:
        return "innerbot_plan"
    if "innerbot" in value:
        return "innerbot"
    if "statedescriptor" in value:
        return "state_descriptor"
    if "outerbot" in value:
        return "outerbot"
    if "direct" in value:
        return "direct"
    if "h2" in value:
        return "h2"
    if "h1" in value:
        return "h1"
    if "decision" in value or "planner" in value:
        return "decision"
    if "state" in value:
        return "state"
    return "unknown"


def empty_usage(source: str) -> Dict[str, object]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cached_input_tokens": 0,
        "usage_source": source,
    }


def estimated_usage(system: str, prompt: str, output: str) -> Dict[str, object]:
    # Mock calls have no provider usage object. This estimate is only to keep
    # the benchmark output shape exercised in tests.
    input_tokens = rough_token_count(system) + rough_token_count(prompt)
    output_tokens = rough_token_count(output)
    usage = empty_usage("estimated")
    usage.update(
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
    )
    return usage


def rough_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def normalize_openai_usage(response: Dict[str, object]) -> Dict[str, object]:
    raw = response.get("usage") or {}
    if not isinstance(raw, dict) or not raw:
        return empty_usage("missing")

    prompt_details = raw.get("prompt_tokens_details") or raw.get("input_tokens_details") or {}
    completion_details = raw.get("completion_tokens_details") or raw.get("output_tokens_details") or {}
    input_tokens = int_value(raw.get("prompt_tokens"), raw.get("input_tokens"))
    output_tokens = int_value(raw.get("completion_tokens"), raw.get("output_tokens"))
    total_tokens = int_value(raw.get("total_tokens"), input_tokens + output_tokens)
    usage = empty_usage("api")
    usage.update(
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "reasoning_tokens": int_value(
                raw.get("reasoning_tokens"),
                completion_details.get("reasoning_tokens") if isinstance(completion_details, dict) else None,
            ),
            "cached_input_tokens": int_value(
                prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None,
                prompt_details.get("cache_read_tokens") if isinstance(prompt_details, dict) else None,
            ),
        }
    )
    return usage


def normalize_anthropic_usage(response: Dict[str, object]) -> Dict[str, object]:
    raw = response.get("usage") or {}
    if not isinstance(raw, dict) or not raw:
        return empty_usage("missing")

    output_details = raw.get("output_tokens_details") or {}
    cache_creation = int_value(raw.get("cache_creation_input_tokens"))
    cache_read = int_value(raw.get("cache_read_input_tokens"))
    input_tokens = int_value(raw.get("input_tokens")) + cache_creation + cache_read
    output_tokens = int_value(raw.get("output_tokens"))
    usage = empty_usage("api")
    usage.update(
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "reasoning_tokens": int_value(
                raw.get("reasoning_tokens"),
                output_details.get("thinking_tokens")
                if isinstance(output_details, dict)
                else None,
            ),
            "cached_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_creation,
        }
    )
    return usage


def normalize_gemini_usage(response: Dict[str, object]) -> Dict[str, object]:
    raw = response.get("usageMetadata") or {}
    if not isinstance(raw, dict) or not raw:
        return empty_usage("missing")

    input_tokens = int_value(raw.get("promptTokenCount"))
    output_tokens = int_value(raw.get("candidatesTokenCount"))
    total_tokens = int_value(raw.get("totalTokenCount"), input_tokens + output_tokens)
    usage = empty_usage("api")
    usage.update(
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "reasoning_tokens": int_value(raw.get("thoughtsTokenCount")),
            "cached_input_tokens": int_value(raw.get("cachedContentTokenCount")),
        }
    )
    return usage


def int_value(*values: object) -> int:
    for value in values:
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def post_json(url: str, payload: Dict[str, object], headers: Dict[str, str]) -> Dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        timeout = int(os.environ.get("MODEL_REQUEST_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc


def build_local_extra_options() -> Optional[Dict[str, object]]:
    """Merge LOCAL_NUM_CTX, LOCAL_THINK, and LOCAL_MODEL_OPTIONS into one Ollama
    `options` dict. LOCAL_MODEL_OPTIONS takes precedence on overlapping keys."""
    options: Dict[str, object] = {}

    num_ctx = os.environ.get("LOCAL_NUM_CTX", "").strip()
    if num_ctx:
        options["num_ctx"] = int(num_ctx)

    think = os.environ.get("LOCAL_THINK", "").strip()
    if think:
        lowered = think.lower()
        if lowered in {"true", "false"}:
            options["think"] = lowered == "true"
        else:
            options["think"] = think

    raw_options = os.environ.get("LOCAL_MODEL_OPTIONS", "").strip()
    if raw_options:
        parsed = json.loads(raw_options)
        if not isinstance(parsed, dict):
            raise ValueError("LOCAL_MODEL_OPTIONS must be a JSON object")
        options.update(parsed)

    return options or None


def create_client(
    provider: str,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    temperature: Optional[float] = None,
    model_path: Optional[str] = None,
    revision: Optional[str] = None,
    enable_thinking: Optional[bool] = None,
    sampling_mode: Optional[str] = None,
    seed: Optional[int] = None,
) -> ModelClient:
    provider = provider.lower()
    if provider == "mock":
        return MockHanoiClient(model or "mock-hanoi", reasoning_effort=reasoning_effort)

    if provider == "openai":
        model = model or os.environ.get("DEFAULT_MODEL") or "gpt-5.1"
        return OpenAICompatibleClient(
            model=model,
            base_url=base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            token_limit_field="max_completion_tokens",
            include_temperature=False,
            reasoning_effort=reasoning_effort,
            include_reasoning_effort=bool(reasoning_effort),
            include_response_schema=True,
        )

    if provider in {"local-transformers", "local_transformers"}:
        canonical_model = (
            model
            or os.environ.get("LOCAL_TRANSFORMERS_MODEL", "").strip()
            or LocalTransformersQwenClient.OFFICIAL_MODEL
        )
        resolved_model_path = (
            model_path
            or os.environ.get("LOCAL_TRANSFORMERS_MODEL_PATH", "").strip()
            or canonical_model
        )
        resolved_revision = (
            revision
            or os.environ.get("LOCAL_TRANSFORMERS_REVISION", "").strip()
            or None
        )
        resolved_thinking = (
            enable_thinking
            if enable_thinking is not None
            else _strict_env_bool("LOCAL_TRANSFORMERS_ENABLE_THINKING", True)
        )
        resolved_seed = (
            int(seed)
            if seed is not None
            else (_optional_env_int("LOCAL_TRANSFORMERS_SEED") or 0)
        )
        return LocalTransformersQwenClient(
            model=canonical_model,
            model_path=resolved_model_path,
            revision=resolved_revision,
            reasoning_effort=reasoning_effort,
            enable_thinking=resolved_thinking,
            sampling_mode=(
                sampling_mode
                or os.environ.get("LOCAL_TRANSFORMERS_SAMPLING_MODE", "").strip()
                or "recommended"
            ),
            seed=resolved_seed,
            temperature=(
                temperature
                if temperature is not None
                else _optional_env_float("LOCAL_TRANSFORMERS_TEMPERATURE")
            ),
            top_p=_optional_env_float("LOCAL_TRANSFORMERS_TOP_P"),
            top_k=_optional_env_int("LOCAL_TRANSFORMERS_TOP_K"),
            min_p=_optional_env_float("LOCAL_TRANSFORMERS_MIN_P"),
            presence_penalty=_optional_env_float(
                "LOCAL_TRANSFORMERS_PRESENCE_PENALTY"
            ),
        )

    if provider in {"local", "openai-compatible"}:
        model = model or os.environ.get("DEFAULT_MODEL") or "local-model"
        local_temperature = temperature
        if local_temperature is None:
            env_temperature = os.environ.get("LOCAL_TEMPERATURE", "").strip()
            if env_temperature:
                local_temperature = float(env_temperature)
        return OpenAICompatibleClient(
            model=model,
            base_url=base_url or os.environ.get("LOCAL_OPENAI_BASE_URL", "http://localhost:8000/v1/chat/completions"),
            api_key=os.environ.get("LOCAL_OPENAI_API_KEY", ""),
            reasoning_effort=reasoning_effort,
            include_reasoning_effort=bool(reasoning_effort),
            include_response_schema=os.environ.get("LOCAL_STRUCTURED_OUTPUTS", "").lower()
            in {"1", "true", "yes", "on"},
            extra_options=build_local_extra_options(),
            temperature=local_temperature,
        )

    if provider == "anthropic":
        model = model or os.environ.get("DEFAULT_MODEL") or "claude-sonnet-4-5"
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for provider=anthropic")
        raw_thinking_budget = os.environ.get(
            "ANTHROPIC_THINKING_BUDGET_TOKENS", ""
        ).strip()
        thinking_budget_tokens = None
        if raw_thinking_budget:
            try:
                thinking_budget_tokens = int(raw_thinking_budget)
            except ValueError as error:
                raise ValueError(
                    "ANTHROPIC_THINKING_BUDGET_TOKENS must be an integer"
                ) from error
            if thinking_budget_tokens < 1024:
                raise ValueError(
                    "ANTHROPIC_THINKING_BUDGET_TOKENS must be at least 1024"
                )
        return AnthropicClient(
            model=model,
            api_key=api_key,
            base_url=base_url or os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages"),
            reasoning_effort=reasoning_effort,
            thinking_budget_tokens=thinking_budget_tokens,
        )

    if provider == "gemini":
        model = model or os.environ.get("DEFAULT_MODEL") or "gemini-2.5-pro"
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for provider=gemini")
        return GeminiClient(
            model=model,
            api_key=api_key,
            base_url=base_url or os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
            reasoning_effort=reasoning_effort,
        )

    raise ValueError(f"Unsupported provider: {provider}")
