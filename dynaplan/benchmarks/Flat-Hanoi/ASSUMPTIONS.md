# Assumptions and reconstruction decisions

The paper leaves several implementation choices unspecified. This file records
the choices made here so that none are mistaken for reported facts.

## Primary pair sampling

The paper's Flat-Hanoi figure explicitly describes both the initial and goal
configurations as having disks spread across pegs. The baseline and extension
profiles therefore sample uniformly without replacement from distinct ordered
pairs `(start, goal)` for which each endpoint occupies at least two pegs. They
apply no minimum shortest-path distance.

The exact pair list and sampling distribution are still unpublished. The
separate `unrestricted-pairs-sensitivity-v1` profile samples from every distinct
ordered pair and may include tower endpoints; it must not be reported as the
primary paper-derived condition.

## Randomness

The authors' random seed is unknown. This project uses `260807077`, derived from
the paper's arXiv identifier. SHA-256 counter-mode rejection sampling maps
deterministic digests uniformly into the finite pair index range and rejects
duplicates. Frozen manifests remain authoritative even if an implementation is
later revised.

## Prompt reconstruction

The prompt retains the reported numeric action convention, legal-move rules,
three-disk demonstration, endpoint stacks, and predecessor instruction to show
a complete move list for each candidate explored. Its language is deliberately
paraphrased. The exact demonstration wording, role text, reasoning instructions,
and Flat-Hanoi adaptation used by the authors are not available.

The cited predecessor prompt asks for “the sequence” rather than explicitly
requesting a shortest sequence. The Flat-Hanoi paper reports optimal accuracy
but does not publish its exact adapted prompt. Asking for a shortest legal plan
is therefore our reconstruction choice, motivated by the headline metric; it is
not presented as verbatim or explicitly reported prompt language.

Stack displays are bottom-to-top. Pegs are zero-indexed and disks are one-indexed
from smallest to largest. These conventions are repeated in every prompt.

## Output budget

The paper reports a 32k answer-token budget, with provider-side reasoning beyond
that answer allowance. This implementation records an operational ceiling of
32,000 answer/output tokens and does not treat hidden reasoning tokens as part
of that ceiling. If a provider interprets “32k” as 32,768, combines answer and
reasoning budgets, or enforces a smaller limit, record the actual semantics in
the run ledger and do not merge it silently with the reference protocol.

## Sampling temperature

The Flat-Hanoi paper says it follows the cited Shojaee baseline protocol while
varying the generation budget. That predecessor protocol specifies temperature
1.0. We therefore record `temperature=1.0` as inherited protocol metadata, not
as a setting explicitly restated by the Flat-Hanoi paper. No other unspecified
provider sampling settings are inferred.

## Parsing

Only the final `moves = [...]` block is scored. An incomplete or malformed final
block is illegal even if an earlier draft block was valid. Strict lists and
integer triples prevent evaluator-side correction of model mistakes. Inline
Python `#` comments are tolerated to retain compatibility with the predecessor
prompt protocol, but their contents have no semantic effect.

This is intentionally stricter than the flexible extractor documented by the
cited Shojaee predecessor protocol, which also recognizes alternative explicit
move patterns and bracket-only answers, normalizes some formatting, and can
consider multiple candidates. The Flat-Hanoi paper does not publish its exact
adapted extractor. Accordingly, parser-sensitive score comparisons are not
exact replications; this benchmark favors an auditable, single final-answer
contract over permissive evaluator repair.

## Four-disk transformer split

The all-pairs profile contains every `81 * 80 = 6,480` distinct ordered pair.
The reported 80/20 split is reconstructed by stable SHA-256 ranking into exactly
5,184 training and 1,296 validation examples. The paper's original membership is
unknown. This artifact is a task-pair set with exact distances, not a
reimplementation of the six-layer transformer, trace-generation curriculum, or
training pipeline. Exact solution traces can be generated through the BFS oracle.

## Metrics

“Success” means optimal accuracy when matching the paper: number classified
`optimal` divided by all scheduled instances. Legal goal-reaching but longer
plans are `suboptimal`, not successes. Legal unfinished plans are `incorrect`.
Rule violations and unparseable/truncated answers are `illegal`.
