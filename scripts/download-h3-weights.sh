#!/usr/bin/env bash
# Fetch the MiniMax H3 weights needed to render locally (issue #6).
#
# ComfyUI-only install. H3 is NOT supported by ComfyUI's GGUF loaders -- see
# the note at the bottom -- so these are the int8_convrot files, which is the
# format the cu130 comfy-kitchen kernels accelerate.
#
# Usage:
#   MODELS_DIR=/path/to/ComfyUI/models ./scripts/download-h3-weights.sh
#
# Set HF_TOKEN in the environment for gated repos (only the LTX script needs it).
#
# Do NOT run this while ComfyUI is starting or generating. On the reference rig
# the models disk is NTFS over FUSE on a spinning HDD, and FUSE serialises: a
# concurrent large copy pushed `import torch` from ~2.3 s to 94-463 s.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="${MODELS_DIR:?set MODELS_DIR to your ComfyUI models directory}"
LOG="${LOG:-$MODELS_DIR/../download-h3.log}"
BASE=https://huggingface.co

say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

dl() { # dl <repo> <file-in-repo> <models-subdir>
  local repo=$1 file=$2 sub=$3
  local dest="$MODELS_DIR/$sub/$(basename "$file")"
  if [ -s "$dest" ]; then say "SKIP $sub/$(basename "$file")"; return 0; fi
  say "GET  $(basename "$file")"
  if python3 "$HERE/pget.py" "$BASE/$repo/resolve/main/$file" "$dest" -c 8 >>"$LOG" 2>&1; then
    say "OK   $sub/$(basename "$file") $(du -h "$dest" | cut -f1)"
  else
    say "FAIL $repo :: $file"; return 1
  fi
}

say "=== H3 weights -> $MODELS_DIR ==="

# ---- Tier 1: the keyframe-first path (smallest set that renders a shot) ----
# Both VAEs are mandatory: H3 denoises picture and stereo audio jointly in one
# pass, so there is no video-only mode and the audio VAE cannot be dropped.
dl Comfy-Org/MiniMax-H3 vae/minimax_h3_audio_vae_fp32.safetensors vae
dl Comfy-Org/MiniMax-H3 vae/minimax_h3_video_vae_int8_convrot.safetensors vae
# NVFP4 text encoder, NOT int8: int8 is 25.28 GiB and would exceed a 24 GB card
# and stream on every run. Safe on Ampere despite sm_86 having no FP4 compute --
# the safetensors header carries 351 comfy_quant descriptors and zero
# input_scale tensors, so it dequantizes rather than needing an FP4 matmul.
dl Comfy-Org/MiniMax-H3 text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors text_encoders
# The DiT for image-to-video / text-to-video (first-frame keyframe animation).
dl Comfy-Org/MiniMax-H3 diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors diffusion_models
# Turbo LoRA: the official i2v template ships the 8-step variant.
dl Comfy-Org/MiniMax-H3 loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors loras

# ---- Tier 2: reference-to-video, for character consistency (issue #8) ----
# Up to 9 reference images (character model sheets) + 3 audio clips. This is the
# path that keeps a character's design identical across shots.
dl Comfy-Org/MiniMax-H3 diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors diffusion_models
dl lightx2v/Minimax-h3-Turbo minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors loras
# Second video VAE variant: the official r2v template loads int8, the Singularity
# workflow loads fp16. Keeping both avoids a mid-scene re-fetch.
dl Comfy-Org/MiniMax-H3 vae/minimax_h3_video_vae_fp16.safetensors vae
# 4-step fl2v turbo: the other step-count variant, for A/B on motion vs speed.
dl Comfy-Org/MiniMax-H3 loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors loras
# Latent upscaler: refines latents directly, skipping the costly 5B VAE decode.
dl LBH-123-AI/Minimax_h3_latent_Upscaler \
   minimax_h3_latent_upscaler_3d_conv_v1/minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors \
   latent_upscale_models

say "=== done ==="
df -h "$MODELS_DIR" | tail -1 | tee -a "$LOG"

# NOT included on purpose:
#   WarmBloodAban/Minimax-h3_Singularity (19.53 GiB) -- a third DiT that does the
#   same job as ref2va. Optional; add it only if you want the HDR fusion variant.
#
# GGUF is NOT an option for H3 on ComfyUI:
#   city96/ComfyUI-GGUF's IMG_ARCH_LIST is
#   {flux, sd1, sdxl, sd3, aura, hidream, cosmos, ltxv, hyvid, wan, lumina2,
#    qwen_image} -- MiniMax H3 is absent and unknown architectures raise.
#   ComfyUI core ships no GGUF loader at all. unsloth's H3 GGUF targets
#   stablediffusion.cpp, not ComfyUI. Use the int8_convrot files above.
