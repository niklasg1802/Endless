# LoRA training recipe (for the character fix)

Reference conditioning cannot hold a character's design across independently
generated keyframes -- two keyframes from the SAME sheet produced different hair
silhouettes (bowl vs spiky) and different coat colours (brown vs grey). A LoRA is
the fix, and this records how to train one on this hardware.

## The memory problem, and why SGD solves it

Training needs weights + gradients + optimizer state:

| optimizer | weights | gradients | state | total | fits ~22 GB? |
|---|---|---|---|---|---|
| AdamW / Adam | 6.8 GB | 6.8 GB | 13.6 GB (2 moment buffers/param) | **27.2 GB** | no |
| **SGD** | 6.8 GB | 6.8 GB | **0** | **13.6 GB** | **yes** |

Five attempts with AdamW/Adam OOM'd identically. The failure was not a setting:
no parameter fixes an equation. SGD carries no moment buffers, which is the whole
difference.

Verified by running it: on the 12 GB card the trainer entered its loop
(`Training LoRA: 0%| | 0/1200`) and failed only on a memory-compile error from
that card's 11.5 GB -- not on allocation. The 24 GB card will have 23.3 GB free
once the episode render finishes.

## Settings

ComfyUI core ships `TrainLoraNode`; no external trainer is needed. Its input names
have been checked against the node schema -- all 21 match exactly.

- `optimizer: SGD`, `learning_rate: 0.02` (SGD has no adaptive scaling, so it
  needs a far higher rate than the ~1e-4 used with Prodigy/Adam)
- `rank: 16`, `steps: 1500`
- `training_dtype: none` + `quantized_backward: true` -- required together for a
  quantized checkpoint. Setting `training_dtype: bf16` dequantizes the whole model
  in memory and OOMs immediately.
- `gradient_checkpointing: true`, `offloading: true`
- A unique trigger token per character (`rickch`, `mortych`) so the LoRA carries
  the identity rather than the base model's prior for "generic scientist".

## Dataset

24-34 images per character, generated as variations from the corrected reference
sheet and varying pose, angle, expression and framing. The generation script is
the same one that produced the sheets, with the corrected design text -- describing
the design positively rather than by negation. Saying "NOT a bowl cut" produced a
bowl cut; saying "a close-fitting helmet mass hugging the skull, ears visible"
produced the right hair, because a negative gives the model nothing to aim at.

## Known unknowns

- SGD convergence on this subject is unproven here -- the loop starts, but no run
  has completed, so 2-4 iterations should be expected.
- Memory during a full 1500-step run is unmeasured. The 13.6 GB figure is
  arithmetic; the 3060 run proves the loop starts, not that it finishes.
