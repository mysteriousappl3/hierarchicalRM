# Provenance

## Primary source

This implementation is derived from the task and evaluation description in:

- *Transformers Struggle to Use Their Emergent World Models: Revisiting the
  Tower of Hanoi, and the Illusion of Thinking*, arXiv:2608.07077,
  <https://arxiv.org/abs/2608.07077>.

The paper describes Flat-to-Flat Hanoi with endpoints spread across pegs,
numeric moves, model/task sizes, a four-way result taxonomy, and a four-disk
all-pairs transformer experiment. Its reported prompt and inference protocol
follow an optimized Tower-of-Hanoi baseline from prior work.

## Artifact status

No official Flat-Hanoi repository, task manifest, seed, parser, evaluator, or
exact prompt adaptation was publicly linked by the paper when this repository
was created. The arXiv source archive contained manuscript assets rather than an
executable benchmark. Consequently:

- no source code was copied from the paper authors;
- no claim of official implementation is made;
- no claim that these are the authors' exact evaluation pairs is made; and
- numerical comparisons must say **paper-derived reproduction**.

The legal transition system and BFS oracle are independently implemented from
the standard mathematical rules of Tower of Hanoi. The task prompt is
paraphrased and adapted for initial and goal states spread across pegs; it is
not a verbatim reproduction of copyrighted prompt text.

## Reproducibility identity

- Generator version: `flat-hanoi-paper-derived-v1`
- Schema version: `1`
- Default seed: `260807077`, formed from the digits in arXiv identifier
  `2608.07077`
- Runtime dependencies: none beyond Python 3.8+
- Dataset identity: the SHA-256 in each checked-in manifest

If an official artifact is later released, it should be stored and evaluated as
a separate profile rather than silently replacing these frozen manifests.
