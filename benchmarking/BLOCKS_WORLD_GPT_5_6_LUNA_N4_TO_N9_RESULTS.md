# Blocks World: GPT-5.6 Luna, N=4 to N=9

## Run Configuration

| Setting | Value |
|---|---|
| Model | `gpt-5.6-luna` |
| Provider | OpenAI |
| Reasoning effort | Medium |
| Complexity range | 4 to 9 blocks |
| Samples | One run per condition and complexity |
| Maximum replans | 2 |
| Maximum output tokens per call | 4,096 |
| Success criterion | Legal execution and exact final goal state |

## Results

The number in parentheses is the number of legal moves executed. A failed run
with zero moves did not produce a valid executable plan.

| Blocks (N) | Base model | Base + Inner/Outer | Inner/Outer + H1/H2 | Complete N-level hierarchy |
|---:|---:|---:|---:|---:|
| 4 | Failed (4) | Solved (7) | Solved (9) | Solved (10) |
| 5 | Failed (0) | Failed (0) | Solved (12) | Solved (17) |
| 6 | Failed (0) | Solved (12) | Solved (15) | Solved (14) |
| 7 | Failed (0) | Solved (15) | Failed (5) | Solved (15) |
| 8 | Failed (0) | Failed (0) | Solved (24) | Solved (24) |
| 9 | Failed (9) | Solved (19) | Solved (33) | Solved (40) |

## Aggregate Success

| Condition | Tasks solved | Success rate |
|---|---:|---:|
| Base model | 0/6 | 0.0% |
| Base + Inner/Outer | 4/6 | 66.7% |
| Inner/Outer + H1/H2 | 5/6 | 83.3% |
| Complete N-level hierarchy | 6/6 | 100.0% |

## Complete Framework Details

| Blocks (N) | Solved | Moves | Model calls | Replans | Maximum hierarchy level |
|---:|---:|---:|---:|---:|---:|
| 4 | Yes | 10 | 12 | 0 | H3 |
| 5 | Yes | 17 | 21 | 1 | H2 |
| 6 | Yes | 14 | 19 | 0 | H2 |
| 7 | Yes | 15 | 20 | 0 | H2 |
| 8 | Yes | 24 | 29 | 0 | H2 |
| 9 | Yes | 40 | 17 | 2 | H3 |

At N=5, the first hierarchy attempted to move `D` while `E` was the top block.
The deterministic executor attributed the error to HierarchyPlanner, retained
the valid DecisionBot plan, and solved on the hierarchy retry.

At N=9, the first DecisionBot response contained no JSON object. The second
attempt's hierarchy included a one-call wrapper used once, which the compiler
rejected as depth without reuse or compression. The third attempt solved the
task.

## Cost

| Measurement | Total |
|---|---:|
| Runtime | 1,632.45 seconds (about 27 minutes) |
| Model calls | 229 |
| Tokens | 280,845 |

## Artifacts

- [Summary JSON](results/gpt-5.6-luna/sweeps/blocks_world_4_to_9_20260822_120957/summary.json)
- [Summary CSV](results/gpt-5.6-luna/sweeps/blocks_world_4_to_9_20260822_120957/summary.csv)
- [Result figure](figures/blocks_world_gpt_5_6_luna_medium_n4_to_n9_four_conditions.png)

These are single-sample results. Repeated trials are required to estimate a
stable success probability for each condition and complexity.
