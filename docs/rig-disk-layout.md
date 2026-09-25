# Local render rig: disk layout

**Read this before installing anything on a rig.** Getting this wrong cost a full
session with zero clips rendered.

## The rule

**Put the python environment on a fast local filesystem. Put only the models on
the big storage disk.**

```
ext4 / NVMe (fast, small)          big disk (slow, large)
  ├── comfy-venv/                    ├── h3-models/          <- models only
  ├── ComfyUI/                       │     diffusion_models/
  └── dashboard/                     │     text_encoders/
                                     │     vae/ loras/
                                     └── hf_cache/
```

Symlink the models in so ComfyUI finds them:

```sh
mkdir -p /big/h3-models
rm -rf ComfyUI/models && ln -s /big/h3-models ComfyUI/models
```

## Why

Booting ComfyUI imports torch and walks the whole environment: **thousands of
small file reads**. If the venv sits on a network filesystem, a FUSE mount, or
anything with high per-file latency, each read costs a full round-trip to a
userspace daemon. The process parks in `D` state (`request_wait_answer`) and
crawls.

Models are the opposite: a 20 GiB safetensors is one long sequential read, which
even a slow disk handles at full speed. That is why they belong on the big disk
and the environment does not.

## What it looked like when we got it wrong

The reference rig had a 2 TB disk mounted as **NTFS over FUSE** (`fuseblk`,
`mount.ntfs-3g`) on a **spinning HDD**, with the venv *and* ComfyUI checked out
onto it:

- ComfyUI boot stalled twice in `D` state, blocked on the FUSE daemon.
- RSS crept from 69 MB to 591 MB over **more than 20 minutes** and never bound
  a port, so **no render was possible**.
- `du -sh` on the venv could not complete within **60 seconds**.
- Copying the venv to ext4 with `cp -a` moved only 15 of 206 packages in
  10 minutes.
- Creating a **fresh** venv on ext4 with `uv venv` and installing from the
  existing wheel cache did the same job in a couple of minutes.

The last point is the practical lesson: when a directory tree is on a slow
filesystem, **rebuild it rather than copy it**.

## Three more traps on the same rig

**1. Never download while starting or generating.** The measurements that came
with the machine already showed a concurrent large copy pushing `import torch`
from ~2.3 s to 94-463 s. It reproduced exactly. Finish downloads first.

**2. A stray download script keeps respawning workers.** Killing the `pget`
child processes alone does not work — the parent `download-*.sh` relaunches
them. Kill the script first, then the children. Check with:

```sh
ps -eo pid,ppid,stat,cmd | grep -E "pget\.py|download-.*\.sh" | grep -v grep
```

**3. A killed download leaves a plausible-looking partial file.** `[ -s file ]`
tests only that a file is non-empty, so a half-written 19.5 GiB weight looks
"done" and gets skipped forever. `scripts/pget.py` now verifies the byte size
against the server and re-fetches the remainder, and stitches via a temporary
file renamed only after the size checks out. Do not reintroduce an
existence-only check.

## Quick check for a new rig

```sh
findmnt -no FSTYPE,SOURCE /path/to/models     # fuseblk/ntfs/nfs/cifs => slow small-file I/O
lsblk -d -o NAME,ROTA /dev/sdX                # ROTA=1 => spinning disk
time python -c "import torch"                 # from the venv; should be ~2 s, not minutes
```
