# Local H3 rig notes

Findings from setting up local MiniMax H3 on the reference rig, kept here so the
next agent does not have to rediscover them. Machine-specific paths are
deliberately absent — see `setup-rig.sh` and `download-h3-weights.sh` for the
portable version.

## The cu130 requirement

ComfyUI's H3 checkpoints are stored as `int8_tensorwise` + `convrot`. The
accelerated kernels for that format live in comfy-kitchen's CUDA backend, and
`comfy/quant_ops.py` disables that backend below CUDA 13:

```python
cuda_version = tuple(map(int, str(torch.version.cuda).split('.')))
if cuda_version < (13,):
    ck.registry.disable("cuda")
    logging.warning("WARNING: You need pytorch with cu130 or higher to use optimized CUDA operations.")
```

Nothing raises. The run is just silently slow. Install the cu130 torch stack
**last**, because `requirements.txt` lists `torch` unpinned and will otherwise
resolve a default-index wheel over the top.

## Ampere (sm_86) constraints

- No native FP8 or FP4 compute. Use `int8_convrot` weights. The `fp8_scaled`
  variants load but dequantize, so they are strictly worse here.
- NVFP4 **storage** is still fine: the NVFP4 text encoder's safetensors header
  carries 351 `comfy_quant` descriptors and **zero `input_scale` tensors**, so it
  dequantizes rather than requiring an FP4 matmul. Verified by reading the header.
- Do **not** install flash-attn (sdist only on PyPI, long source build) or
  xformers (not needed). ComfyUI's built-in attention is fine.

## Which text encoder

Use `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` (14.61 GiB), not the int8
variant (25.28 GiB). int8 plus ComfyUI's inference reserve exceeds 24 GB, so it
streams on every run. Both official H3 workflow templates use the NVFP4 file.

## GGUF is not an option for H3 on ComfyUI

`city96/ComfyUI-GGUF`'s allowlist is:

```python
IMG_ARCH_LIST = {"flux", "sd1", "sdxl", "sd3", "aura", "hidream", "cosmos", "ltxv", "hyvid", "wan", "lumina2", "qwen_image"}
```

MiniMax H3 is absent, and an unlisted architecture raises `ValueError`. ComfyUI
core ships no GGUF loader at all. unsloth's H3 GGUF targets
`stablediffusion.cpp`, not ComfyUI. This is why the download is ~67 GiB rather
than ~30 GiB — there is no quantised shortcut through ComfyUI.

## 2K is impossible locally

MiniMax's model card states the 2K module (H3-Regenerate-2K) "is not yet
open-sourced". Local open weights cap at **768 px on the short edge**, and
ComfyUI's `MAX_PIXELS` for H3 is `768*1344`. Start at 0.4 MP (864x480); the 1.0 MP
preset yields 1376x768 which is over the cap, so use 0.98 MP (1344x768) instead.

## Node input names

Read from the installed source, not guessed — a wrong name is a validation error:

| node | inputs |
|---|---|
| `MiniMaxH3ImageToVideo` | `clip, vae, prompt, width, height, length, first_frame?, last_frame?` → `positive, LATENT` |
| `MiniMaxH3ReferenceToVideo` | `clip, vae, prompt, width, height, length, ref_image_size, ref_image_1..9` |
| `MiniMaxH3AddGuide` | `positive, latent, frame_idx, vae?, audio_vae?, image?, audio?` |
| `MiniMaxH3SigmaShift` | `model, shift_video, shift_audio` |
| `SamplerCustomAdvanced` | `noise, guider, sampler, sigmas, latent_image` |
| `BasicGuider` | `model, conditioning` |
| `BasicScheduler` | `model, scheduler, steps, denoise` |
| `KSamplerSelect` | `sampler_name` |
| `RandomNoise` | `noise_seed` |
| `CreateVideo` | `images, fps, audio?` |
| `SaveVideo` | `video, filename_prefix` |

`length` is a frame count at 24 fps snapped to the model's 17k+5 grid
(5, 22, 39 … 362). 124 frames ≈ 5 s. Trained range is roughly 124–362.

## Disk behaviour

If the models disk is NTFS over FUSE on a spinning HDD (as on the reference
rig), it works — symlinks, hardlinks, `mmap`, `flock` and sqlite all verified —
but **FUSE serialises badly**. A large download running concurrently with
ComfyUI startup pushed `import torch` from ~2.3 s to 94–463 s. Never download
while starting or generating. `rm -rf` can also fail intermittently with
"Directory not empty"; retry.

## Download throughput

HuggingFace throttles **per connection** (~0.9 MB/s observed) while the link
does ~8 MB/s. The `hf` CLI's `--max-workers` only parallelises across files, so a
single 20 GiB safetensors still takes hours. `pget.py` splits one file into
ranged chunks and reached ~7 MiB/s — about 7x. Use it.

## Licence

The MiniMax H3 Community License excludes the **EU, UK, Republic of Korea and
the USA** from its "Applicable Territory", and clause V.4 extends the restriction
to the **outputs**. This is a real constraint on the project's goal and it
contradicts the "no moderation" rationale for running locally. Unresolved —
see the discussion on the tracking issue.
