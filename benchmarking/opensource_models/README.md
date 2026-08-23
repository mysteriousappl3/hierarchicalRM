# Open-Source Model Runner

This folder configures the six open-source checkpoints used by the Hanoi
benchmark. It does not contain model weights. Models are downloaded by vLLM
to the VM's Hugging Face cache when a server is started.

## Registered Models

| Key | Capacity tier | Official checkpoint |
| --- | --- | --- |
| `qwen35-2b` | low | `Qwen/Qwen3.5-2B` |
| `qwen35-4b` | medium | `Qwen/Qwen3.5-4B` |
| `qwen35-9b` | high | `Qwen/Qwen3.5-9B` |
| `ministral3-reasoning-3b` | low | `mistralai/Ministral-3-3B-Reasoning-2512` |
| `ministral3-reasoning-8b` | medium | `mistralai/Ministral-3-8B-Reasoning-2512` |
| `ministral3-reasoning-14b` | high | `mistralai/Ministral-3-14B-Reasoning-2512` |

Low, medium, and high are parameter-capacity tiers. They are not
inference-time reasoning-effort controls.

## VM Requirements

- Linux VM with an NVIDIA GPU and a current NVIDIA driver.
- Python 3.10 or newer.
- Enough GPU memory for the selected checkpoint, context length, and dtype.
- Outbound access to Hugging Face on the first launch.
- A Hugging Face token in `HF_TOKEN` if a checkpoint requires authentication.

Use an attached VM disk for the cache:

```bash
export HF_HOME=/mnt/models/huggingface
export MODEL_REQUEST_TIMEOUT_SECONDS=1800
```

Do not place downloaded weights inside this repository.

## Install

Qwen3.5 currently benefits from the latest vLLM build, while Ministral 3
requires vLLM 0.12.0 or newer. The setup script defaults to the nightly vLLM
wheel:

```bash
cd benchmarking/opensource_models
bash scripts/setup_vm.sh
```

To request the stable channel:

```bash
VLLM_CHANNEL=stable bash scripts/setup_vm.sh
```

## Inspect Before Starting

List configurations:

```bash
python model_registry.py list
```

Print the exact launch command without loading a model:

```bash
python serve.py qwen35-4b --dry-run
```

The registry uses a 32,768-token context by default to reduce KV-cache
memory. Override it based on the VM:

```bash
python serve.py qwen35-9b --max-model-len 65536 --dry-run
```

For multi-GPU tensor parallelism:

```bash
python serve.py ministral3-reasoning-14b --tensor-parallel-size 2 --dry-run
```

## Start and Check a Model

Run one model server at a time:

```bash
bash scripts/start_model.sh qwen35-2b
```

In a second terminal, verify that the endpoint advertises the expected model.
The basic check does not perform generation:

```bash
bash scripts/check_model.sh qwen35-2b
```

Add `--generate` only when a one-token inference smoke test is wanted.

## Run the Hanoi Benchmark

Full hierarchy:

```bash
bash scripts/run_benchmark.sh qwen35-2b --task all --mode hierarchy
```

Direct model:

```bash
bash scripts/run_benchmark.sh qwen35-2b --task all --mode direct
```

Direct model with InnerBot and OuterBot:

```bash
bash scripts/run_benchmark.sh qwen35-2b --task all --mode inner-outer
```

Repeated trials:

```bash
bash scripts/run_benchmark.sh qwen35-2b \
  --task all \
  --mode hierarchy \
  --repetitions 25
```

The wrapper uses the existing `provider=local` adapter and writes normal
benchmark results. It also writes a batch manifest under
`benchmarking/results/_batch_manifests/` containing the registry metadata,
command, durations, and return codes.

## Reasoning Output

The servers are launched with their family-specific reasoning parsers:

- Qwen3.5: `--reasoning-parser qwen3`
- Ministral 3 Reasoning: `--reasoning-parser mistral`

The benchmark parses only `message.content` as the actionable answer.
When vLLM returns separate `message.reasoning_content`, it is retained in the
raw model-call record with its character count. This prevents thinking text
from breaking the H1/H2/action parsers while preserving it for analysis.

Before final experiments, pin each registry `revision` to a Hugging Face commit
SHA and record the VM image, GPU model, CUDA version, vLLM version, dtype,
context length, and tensor-parallel size.
