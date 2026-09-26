#!/usr/bin/env python3
"""Parallel episode renderer.

Two GPUs, two jobs, because the models have different footprints:

  RTX 4070  12 GB (:8189) -- keyframes. Qwen-Image is 6.8 GB and fits.
  RTX 3090 Ti 24 GB (:8188) -- clips. H3's DiT is 19.5 GiB and fits nothing smaller.

They are genuinely independent: a keyframe pipeline finishes a shot's still while
the big card is still animating an earlier one. So keyframes run ahead in a
producer thread and the clip renderer consumes them as they appear.

Usage:
    python3 render_episode.py <scene.json> [--limit N] [--clips-only] [--keys-only]
"""

import argparse
import json
import pathlib
import queue
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from pipeline import comfy, scene  # noqa: E402

KEYFRAME_HOST = "http://127.0.0.1:8189"   # 4070
CLIP_HOST = "http://127.0.0.1:8188"       # 3090 Ti

_log_lock = threading.Lock()


def log(msg):
    with _log_lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def guard(fn, name):
    """Run a worker, reporting anything that kills its thread."""
    def wrapped(*a, **k):
        try:
            fn(*a, **k)
        except BaseException as e:
            import traceback
            log(f"!! {name} THREAD DIED: {type(e).__name__}: {e}")
            log(traceback.format_exc()[-800:])
    return wrapped



def publish(scene_dir, clip_path):
    """Mirror a finished clip into the layout the dashboard serves.

    The renderer writes into clips/h3/ (per-model). The dashboard's media route
    accepts that path, so nothing else is needed -- but the file must also be
    reachable when the render ran against a scratch directory.
    """
    try:
        clip_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def keyframe_worker(s, d, shots, results, errors, stop):
    """Produce keyframes on the 4070 as fast as it can."""
    try:
        c = comfy.Comfy(host=KEYFRAME_HOST)
        if not c.up():
            log("4070 keyframe worker: ComfyUI :8189 not reachable — skipping keyframes")
            return
    except Exception as e:
        log(f"keyframe worker cannot start: {e}")
        return

    for shot in shots:
        if stop.is_set():
            return
        out = d / "keyframes" / f"{shot['id']}.png"
        if out.exists():
            log(f"keyframe {shot['id']}: cached")
            continue
        # A close-up should carry ONE character's reference, not two -- splitting
        # the reference budget across faces is the documented way to lose a
        # likeness. Wide shots get both.
        who = shot.get("characters") or list(s.get("characters") or {})
        if shot.get("size") == "cu" and len(who) > 1:
            who = who[:1]
        sheets = scene.character_sheets(s, who)
        prompt = scene.build_keyframe_prompt(s, shot, sheets)
        t0 = time.time()
        try:
            info = c.render_image(str(out), prompt,
                                  width=s["width"], height=s["height"],
                                  seed=shot.get("seed", s["seed"]),
                                  ref_image_paths=sheets,
                                  resolution=s["width"],
                                  filename_prefix=f"endless/{s['slug']}/kf_{shot['id']}")
            log(f"keyframe {shot['id']}: {info['wall_seconds']}s -> {info['bytes']//1024} KB")
        except Exception as e:
            log(f"keyframe {shot['id']} FAILED: {str(e)[:200]}")
            errors.append((shot["id"], "keyframe", str(e)[:300]))


def clip_worker(s, d, shots, results, errors, stop, kf_done):
    """Animate on the 3090 Ti, waiting for each keyframe as the 4070 produces it."""
    c = comfy.Comfy(host=CLIP_HOST)
    if not c.up():
        log("3090 Ti clip worker: ComfyUI :8188 not reachable — aborting")
        return

    for shot in shots:
        if stop.is_set():
            return
        kf = d / "keyframes" / f"{shot['id']}.png"
        out = d / "clips" / "h3" / f"{shot['id']}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            log(f"clip {shot['id']}: cached")
            continue

        # Wait for the producer, but not forever.
        waited = 0
        while not kf.exists():
            if waited > 900:
                log(f"clip {shot['id']}: gave up waiting for its keyframe")
                errors.append((shot["id"], "clip", "keyframe never arrived"))
                kf = None
                break
            time.sleep(5)
            waited += 5
        if kf is None:
            continue

        # If the NEXT keyframe already exists, this shot can be bracketed with it
        # to force a trajectory instead of a static hold. Two frames of the same
        # characters in a different action state is what produces real movement.
        idx = shots.index(shot)
        nxt = shots[idx + 1]["id"] if idx + 1 < len(shots) else None
        nxt_kf = d / "keyframes" / f"{nxt}.png" if nxt else None
        use_last = bool(nxt_kf and nxt_kf.exists())

        # Release anything the previous shot left resident. Without this the 15 GB
        # text encoder can still be loaded when the 20 GB DiT is staged, which does
        # not fit and fails with an int8_linear allocation error.
        try:
            c._request("/free", {"unload_models": True, "free_memory": True}, timeout=60)
        except Exception:
            pass
        time.sleep(2)

        t0 = time.time()
        try:
            info = c.render_i2v(
                str(out), shot["motion_prompt"], str(kf),
                width=s["width"], height=s["height"],
                seconds=shot.get("seconds", 5),
                seed=shot.get("seed", s["seed"]),
                last_frame_path=str(nxt_kf) if use_last else None,
                steps=shot.get("steps", 8),
                lora=shot.get("lora", comfy.TURBO_FL2V_8STEP),
                filename_prefix=f"endless/{s['slug']}/{shot['id']}")
            tag = "bracketed" if use_last else "single-frame"
            log(f"clip {shot['id']}: {info['wall_seconds']}s ({tag}) -> {info['bytes']//1024} KB")
            publish(d, out)
            results.append({"id": shot["id"], "wall": info["wall_seconds"],
                            "bracketed": use_last, "bytes": info["bytes"]})
        except Exception as e:
            log(f"clip {shot['id']} FAILED: {str(e)[:200]}")
            errors.append((shot["id"], "clip", str(e)[:300]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keys-only", action="store_true")
    ap.add_argument("--clips-only", action="store_true")
    a = ap.parse_args()

    s = scene.load_scene(a.scene)
    d = scene.scene_dir(s)
    (d / "clips" / "h3").mkdir(parents=True, exist_ok=True)
    shots = s["shots"][: a.limit] if a.limit else s["shots"]

    log(f"episode: {s['title']}")
    log(f"canvas:  {s['width']}x{s['height']}   shots: {len(shots)}   out: {d}")
    log(f"keyframes on 4070 ({KEYFRAME_HOST}), clips on 3090 Ti ({CLIP_HOST})")

    results, errors = [], []
    stop = threading.Event()
    kf_done = threading.Event()

    kt = threading.Thread(target=guard(keyframe_worker, "keyframe"),
                          args=(s, d, shots, results, errors, stop), daemon=True)
    ct = threading.Thread(target=guard(clip_worker, "clip"),
                          args=(s, d, shots, results, errors, stop, kf_done), daemon=True)

    t0 = time.time()
    if a.clips_only:
        ct.start(); ct.join()
    elif a.keys_only:
        kt.start(); kt.join()
    else:
        kt.start()
        ct.start()
        kt.join()
        ct.join()
    elapsed = round(time.time() - t0)

    log(f"done in {elapsed}s — {len(results)} clips, {len(errors)} errors")
    for sid, kind, err in errors:
        log(f"  ERROR {kind} {sid}: {err[:160]}")
    total = sum(r["wall"] for r in results)
    if results:
        log(f"clip seconds: {total}s | avg {total // len(results)}s | "
            f"bracketed {sum(1 for r in results if r['bracketed'])}/{len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
