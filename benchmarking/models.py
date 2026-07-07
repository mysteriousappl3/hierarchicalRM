from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_TIMEOUT_SECONDS = 120


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
    max_tokens: int
    reasoning_effort: Optional[str]
    prompt_char_count: int
    output_char_count: int
    usage: Dict[str, object]
    raw_usage: Dict[str, object]


class ModelClient:
    provider = "base"

    def __init__(self, model: str, reasoning_effort: Optional[str] = None):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.call_history: List[ModelCall] = []

    def generate(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        raise NotImplementedError

    def call_records_since(self, start_index: int) -> List[Dict[str, object]]:
        return [asdict(call) for call in self.call_history[start_index:]]

    def _record_call(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        output: str,
        usage: Optional[Dict[str, object]] = None,
        raw_usage: Optional[Dict[str, object]] = None,
    ) -> str:
        self.call_history.append(
            ModelCall(
                provider=self.provider,
                model=self.model,
                stage=infer_stage(system),
                system=system,
                max_tokens=max_tokens,
                reasoning_effort=self.reasoning_effort,
                prompt_char_count=len(prompt),
                output_char_count=len(output),
                usage=usage or empty_usage("missing"),
                raw_usage=raw_usage or {},
            )
        )
        return output


class MockHanoiClient(ModelClient):
    provider = "mock"

    def generate(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        stage = system.lower()
        if "outerbot" in stage:
            output = self._outerbot_response()
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
            usage=estimated_usage(system, prompt, output),
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

    def _decision_response(self, prompt: str) -> str:
        task = self._task_from_prompt(prompt)
        moves: List[str] = []
        self._solve_hanoi(
            n=len(task["rings"]),
            source=task["source_peg"],
            auxiliary=task["auxiliary_peg"],
            target=task["target_peg"],
            moves=moves,
        )
        function_block = "\n".join(self._hierarchy_calls_from_moves(moves))
        return f"""```start_subtask_1
Move all rings from {task["source_peg"]} to {task["target_peg"]}.
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
    ):
        super().__init__(model, reasoning_effort=reasoning_effort)
        self.base_url = base_url
        self.api_key = api_key
        self.token_limit_field = token_limit_field
        self.include_temperature = include_temperature
        self.include_reasoning_effort = include_reasoning_effort

    def generate(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            self.token_limit_field: max_tokens,
        }
        if self.include_temperature:
            payload["temperature"] = 0
        if self.reasoning_effort and self.include_reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        response = post_json(self.base_url, payload, self._headers())
        output = response["choices"][0]["message"]["content"]
        return self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            usage=normalize_openai_usage(response),
            raw_usage=response.get("usage", {}),
        )

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class AnthropicClient(ModelClient):
    provider = "anthropic"

    def __init__(self, model: str, api_key: str, base_url: str, reasoning_effort: Optional[str] = None):
        super().__init__(model, reasoning_effort=reasoning_effort)
        self.api_key = api_key
        self.base_url = base_url

    def generate(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        response = post_json(self.base_url, payload, headers)
        parts = response.get("content", [])
        output = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
        return self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            usage=normalize_anthropic_usage(response),
            raw_usage=response.get("usage", {}),
        )


class GeminiClient(ModelClient):
    provider = "gemini"

    def __init__(self, model: str, api_key: str, base_url: str, reasoning_effort: Optional[str] = None):
        super().__init__(model, reasoning_effort=reasoning_effort)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def generate(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": max_tokens,
            },
        }
        response = post_json(url, payload, {"Content-Type": "application/json"})
        candidates = response.get("candidates", [])
        if not candidates:
            output = ""
        else:
            parts = candidates[0].get("content", {}).get("parts", [])
            output = "".join(part.get("text", "") for part in parts)
        return self._record_call(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output=output,
            usage=normalize_gemini_usage(response),
            raw_usage=response.get("usageMetadata", {}),
        )


def infer_stage(system: str) -> str:
    value = system.lower()
    if "innerbot" in value and "state" in value:
        return "innerbot_state"
    if "innerbot" in value and "plan" in value:
        return "innerbot_plan"
    if "innerbot" in value:
        return "innerbot"
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
            "reasoning_tokens": int_value(raw.get("reasoning_tokens")),
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
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc


def create_client(
    provider: str,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
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
        )

    if provider in {"local", "openai-compatible"}:
        model = model or os.environ.get("DEFAULT_MODEL") or "local-model"
        return OpenAICompatibleClient(
            model=model,
            base_url=base_url or os.environ.get("LOCAL_OPENAI_BASE_URL", "http://localhost:8000/v1/chat/completions"),
            api_key=os.environ.get("LOCAL_OPENAI_API_KEY", ""),
            reasoning_effort=reasoning_effort,
            include_reasoning_effort=False,
        )

    if provider == "anthropic":
        model = model or os.environ.get("DEFAULT_MODEL") or "claude-sonnet-4-5"
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for provider=anthropic")
        return AnthropicClient(
            model=model,
            api_key=api_key,
            base_url=base_url or os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages"),
            reasoning_effort=reasoning_effort,
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
