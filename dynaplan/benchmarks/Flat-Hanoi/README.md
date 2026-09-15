# Flat Hanoi: paper-derived benchmark

This repository is a self-contained reimplementation of the Flat-to-Flat Tower
of Hanoi benchmark described in [*Transformers Struggle to Use Their Emergent
World Models: Revisiting the Tower of Hanoi, and the Illusion of
Thinking*](https://arxiv.org/abs/2608.07077). It is **not an official code release
and not an exact reconstruction**. The paper did not publish its task instances,
sampling seed, parser, evaluator, or exact flat-state prompt adaptation.

The implementation has no runtime dependencies outside Python 3.8 or newer. It
provides deterministic data generation, an exact breadth-first-search oracle,
strict answer parsing, rule-by-rule simulation, paper-compatible outcome
categories, batch scoring, and aggregate reporting.

## What is reproduced

- Three pegs, numbered 0 through 2.
- Disks numbered from 1 (smallest) through `n` (largest).
- Initial and goal configurations with disks spread across multiple pegs in the
  main evaluation profiles.
- Numeric actions `[disk_id, source_peg, destination_peg]`.
- Exact shortest paths computed by breadth-first search.
- Four mutually exclusive outcomes: `optimal`, `suboptimal`, `incorrect`, and
  `illegal`.
- Unparseable answers count as `illegal` and remain in every reported
  denominator.
- The reported baseline sizes: 34 tasks at `n=3`, 33 at `n=4`, and 33 at `n=5`.
- The reported extension sizes: 33 tasks each at `n=6` and `n=7`.
- The four-disk transformer all-pairs task set of 6,480 ordered distinct state
  pairs, with an exact deterministic 5,184/1,296 split. This is not the paper's
  transformer architecture or training pipeline.
- A plain-model protocol with no tools, a 32,000 answer-token ceiling, and
  temperature 1.0 inherited from the prior baseline protocol cited by the
  Flat-Hanoi paper. Provider-side reasoning may be additional to that answer
  budget.

See [PROVENANCE.md](PROVENANCE.md) and [ASSUMPTIONS.md](ASSUMPTIONS.md) before
comparing results with the paper.

## Canonical representation

A state is a tuple containing one peg number per disk, smallest disk first:

```python
# disk 1 is on peg 1, disk 2 is on peg 2, disks 3 and 4 are on peg 0
(1, 2, 0, 0)
```

Disk order on each peg is implicit. Therefore all `3**n` assignments are legal
Hanoi configurations. Human-facing stack listings are rendered bottom-to-top.

## Frozen datasets

| Dataset | Contents | Sampling policy |
|---|---:|---|
| `flat_hanoi/data/paper_baseline_v1.jsonl` | 100 | Uniform without replacement, conditioned on both endpoints occupying at least two pegs; `n=3/4/5` counts are 34/33/33 |
| `flat_hanoi/data/paper_extension_n6_n7_v1.jsonl` | 66 | Same endpoint policy; 33 each at `n=6/7` |
| `flat_hanoi/data/unrestricted_pairs_sensitivity_v1.jsonl` | 100 | Same baseline counts sampled from all distinct ordered pairs, including tower endpoints |
| `flat_hanoi/data/transformer_n4_all_pairs_v1.jsonl` | 6,480 | Exhaustive distinct ordered pairs, with `split=train` or `split=validation` |

The primary and extension profiles follow the paper's figure, which specifies
that disks are spread across pegs in both the initial and goal configurations.
The unrestricted interpretation is retained only as a named sensitivity
analysis. No sampled profile applies a minimum-distance filter.

Every JSONL has a neighboring `.manifest.json` recording its byte-level SHA-256
digest, profile, seed, counts, optimal-distance histogram, evaluation protocol,
and hashes of the exact prompt, parser, simulator, oracle, and evaluator source.
The checked-in files, not regeneration, are the benchmark source of truth.

## Quick start

From this directory:

```bash
python -m unittest discover -s tests -v
python -m flat_hanoi validate flat_hanoi/data/paper_baseline_v1.jsonl
python -m flat_hanoi prompt \
  --dataset flat_hanoi/data/paper_baseline_v1.jsonl \
  --instance paper-baseline-v1-n3-0000
python -m flat_hanoi oracle \
  --dataset flat_hanoi/data/paper_baseline_v1.jsonl \
  --instance paper-baseline-v1-n3-0000
```

Regenerate a profile into an explicit output path:

```bash
python -m flat_hanoi generate \
  --profile paper-baseline-v1 \
  --seed 260807077 \
  --output /tmp/paper_baseline_v1.jsonl
```

Score one response:

```bash
python -m flat_hanoi score \
  --dataset flat_hanoi/data/paper_baseline_v1.jsonl \
  --instance paper-baseline-v1-n3-0000 \
  --response response.txt
```

Score a batch and summarize it:

```bash
python -m flat_hanoi score-batch \
  --dataset flat_hanoi/data/paper_baseline_v1.jsonl \
  --responses responses.jsonl \
  --output results.jsonl \
  --summary summary.json
python -m flat_hanoi summarize results.jsonl
```

Each response line must contain `instance_id` and either `response` or
`output_text`. Optional model, reasoning, token, cost, finish-reason, and timing
fields pass through to the result. A missing response becomes an unparseable
`illegal` attempt rather than being dropped.

## Parsing and evaluation

The parser selects the **last** `moves =` assignment, extracts its outer list by
balanced brackets, and safely parses it. It requires an outer list of
three-integer inner lists. It does not coerce strings, floats, booleans, tuples,
one-indexed pegs, missing disk IDs, or malformed text. Python-style `#` comments
inside a candidate list are tolerated for compatibility with the predecessor
protocol.

The simulator then verifies that each asserted disk:

1. exists and is on the asserted source peg;
2. is that peg's top disk;
3. moves to a different in-range peg; and
4. is not placed on a smaller disk.

The `prompt`, `oracle`, `score`, and `score-batch` commands verify the required
adjacent manifest and all stored BFS distances before consuming a dataset. A
modified or unverified task file is rejected rather than scored silently.

Every result exposes four independent booleans:

- `parseable`: a strict final moves list was recovered;
- `legal`: every submitted action passed simulation;
- `goal_reached`: the final state equals the goal;
- `optimal`: the goal was reached in exactly the BFS distance.

`valid` is retained as a documented alias for `legal`, not as the paper's
headline success metric. Headline success is `optimal / total`.

| Classification | Definition |
|---|---|
| `optimal` | Parseable, legal, goal-reaching, and exactly shortest |
| `suboptimal` | Parseable, legal, goal-reaching, but longer than shortest |
| `incorrect` | Parseable and legal, but final state is not the goal |
| `illegal` | Unparseable or contains at least one illegal move |

## Integrating model runners

Keep inference outside this neutral package. Render prompts with
`flat_hanoi.prompt.render_messages`, preserving the returned system and user
roles; `render_prompt` is only a labeled text preview. Save raw responses and
usage metadata as JSONL, and score only through this package. For the closest
reported baseline protocol, use a plain model, no tools, no simulator feedback during generation,
`max_output_tokens=32000`, and temperature 1.0. The temperature is inherited
from the cited Shojaee baseline protocol rather than explicitly restated in the
Flat-Hanoi paper. The 32k setting applies to the answer; provider-side reasoning
may use an additional budget. Record actual provider semantics. Preserve every
attempted instance—including API errors and truncated/unparseable answers—in
the response ledger.

## Out of scope

This repository does not reproduce the paper's six-layer transformer training,
linear probes, activation patching or steering, or the 81-state fixed-goal
mechanistic experiment. It implements the planning task generator, frozen task
sets, prompt renderer, exact oracle, parser, simulator, and scorer. The
four-disk all-pairs artifact supplies task pairs and distances; oracle traces can
be generated on demand.
