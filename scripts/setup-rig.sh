#!/usr/bin/env bash
# Install ComfyUI + the H3 python stack on a CUDA 13 / Ampere rig (issue #6).
#
# Usage:
#   COMFY_DIR=/path/to/ComfyUI VENV_DIR=/path/to/venv ./scripts/setup-rig.sh
#
# Both default to a `ComfyUI`/`comfy-venv` pair next to each other; put them on
# a large disk, not on a small root filesystem -- the venv is ~8 GB and the H3
# weights are ~67 GB.
#
# Why cu130 is mandatory, not merely preferred: ComfyUI's H3 checkpoints are
# stored as int8_tensorwise + convrot. The accelerated kernels for that format
# live in comfy-kitchen's CUDA backend, and comfy/quant_ops.py calls
# ck.registry.disable("cuda") when torch.version.cuda is below 13. Nothing
# raises -- the run is just silently slow. So the cu130 stack must be installed
# LAST, because requirements.txt lists torch unpinned and would clobber it.
set -euo pipefail

COMFY_DIR="${COMFY_DIR:-$(pwd)/ComfyUI}"
VENV_DIR="${VENV_DIR:-$(pwd)/comfy-venv}"
REPO="${COMFY_REPO:-https://github.com/comfyanonymous/ComfyUI.git}"
PY="${PYTHON:-3.12}"

# Keep multi-GB caches off a possibly-small root filesystem.
export UV_CACHE_DIR="${UV_CACHE_DIR:-$(dirname "$COMFY_DIR")/uvcache}"
export TMPDIR="${TMPDIR:-$(dirname "$COMFY_DIR")/tmp}"
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-600}"   # the CUDA wheels time out at the 30s default
mkdir -p "$UV_CACHE_DIR" "$TMPDIR"

say() { echo "[$(date +%H:%M:%S)] $*"; }

if [ ! -d "$COMFY_DIR/.git" ]; then
  say "cloning ComfyUI -> $COMFY_DIR"
  git clone --depth 1 "$REPO" "$COMFY_DIR"
else
  say "ComfyUI already present at $COMFY_DIR"
fi

say "creating venv at $VENV_DIR"
uv venv --python "$PY" "$VENV_DIR"

say "installing requirements (pulls a default torch; overwritten next)"
VIRTUAL_ENV="$VENV_DIR" uv pip install -r "$COMFY_DIR/requirements.txt"

say "installing cu130 torch stack (must win)"
VIRTUAL_ENV="$VENV_DIR" uv pip install --index-url https://download.pytorch.org/whl/cu130 \
  torch torchvision torchaudio

say "verifying"
"$VENV_DIR/bin/python" - <<'PY'
import torch
print("torch", torch.__version__, "| cuda", torch.version.cuda,
      "| avail", torch.cuda.is_available(), "| devs", torch.cuda.device_count())
assert torch.version.cuda and int(torch.version.cuda.split(".")[0]) >= 13, \
    "cu130 or newer REQUIRED for H3 int8_convrot kernels"
print("CU130 GATE OK")
PY

say "done"
echo
echo "Models go in $COMFY_DIR/models. If you want them on a separate disk:"
echo "  mkdir -p /path/to/h3-models"
echo "  rm -rf $COMFY_DIR/models && ln -s /path/to/h3-models $COMFY_DIR/models"
echo
echo "Then fetch weights:"
echo "  MODELS_DIR=$COMFY_DIR/models ./scripts/download-h3-weights.sh"
echo
echo "Launch (pins the GPU via CUDA_VISIBLE_DEVICES under PCI_BUS_ID ordering):"
echo "  CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 $VENV_DIR/bin/python $COMFY_DIR/main.py --listen 127.0.0.1 --port 8188"
