"""Scene orchestrator: a scene JSON -> keyframes -> clips -> one assembled video.

Every step reads and writes files, so any step can be re-run on its own and a
failure does not lose the work before it. This is the skeleton from issue #12,
restricted to what the POC actually proved works:

    keyframe (image model, sees the character sheets)  <- POC #3: design fixed for $0.07
      -> animate the keyframe (local H3, keyframe-first)  <- POC #1/#3: design holds
      -> assemble with ffmpeg

Character consistency comes from feeding the same character sheets into every
keyframe generation, not from hoping the video model remembers. The video model
then only has to animate a frame that is already correct.

Usage:
    python -m pipeline.scene plan      <scene.json>
    python -m pipeline.scene keyframes <scene.json> [--shot ID ...] [--force]
    python -m pipeline.scene render    <scene.json> [--shot ID ...] [--force]
    python -m pipeline.scene assemble  <scene.json>
    python -m pipeline.scene all       <scene.json>

Outputs land under <scene_dir>/<slug>/{keyframes,clips,final.mp4}.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pipeline import comfy, llm  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "scenes"


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "scene"


def load_scene(path):
    path = pathlib.Path(path)
    scene = json.loads(path.read_text())
    scene["_path"] = path
    scene.setdefault("title", path.stem)
    scene.setdefault("slug", slugify(scene["title"]))
    scene.setdefault("out_dir", str(DEFAULT_OUT))
    scene.setdefault("width", 864)
    scene.setdefault("height", 480)
    scene.setdefault("seed", 1)
    scene.setdefault("backend", "local")          # local | cloud
    scene.setdefault("characters", {})
    scene.setdefault("style_block", "")
    return scene


def scene_dir(scene):
    d = pathlib.Path(scene["out_dir"]) / scene["slug"]
    (d / "keyframes").mkdir(parents=True, exist_ok=True)
    (d / "clips").mkdir(parents=True, exist_ok=True)
    return d


def character_sheets(scene, names):
    """Local paths of the sheets for the given character keys.

    Relative sheet paths are resolved against the scene's output directory, so
    `sheets/scientist.png` means <scene_dir>/sheets/scientist.png.
    """
    d = scene_dir(scene)
    out = []
    for n in names or []:
        ch = scene["characters"].get(n)
        if not ch:
            print(f"  ! unknown character '{n}' -- skipping its sheet")
            continue
        p = pathlib.Path(ch["sheet"])
        if not p.is_absolute():
            p = d / p
        if not p.exists():
            print(f"  ! sheet missing for '{n}': {p}")
            continue
        out.append(p)
    return out


def build_keyframe_prompt(scene, shot, sheets):
    """Prompt for the local image model (Qwen-Image-2.1, generate + edit).

    IMPORTANT: when reference images are attached, do NOT describe the
    character's appearance in the prompt. An instruction-editing model treats
    those tokens as instructions and overrides the reference image, which is
    exactly the design drift we are trying to avoid. Describe only scene,
    background, lighting and action; let the sheets carry the design.
    """
    parts = []
    if scene["style_block"]:
        parts.append(scene["style_block"])
    parts.append(shot["keyframe_prompt"])
    if sheets:
        who = [n for n in (shot.get("characters") or []) if scene["characters"].get(n)]
        refs = ", ".join(f"<Picture {i}> is {n}" for i, n in enumerate(who, start=1))
        parts.append(
            f"Use the character designs from the reference images exactly as shown "
            f"({refs}). Preserve each character's head shape, hair, face, proportions "
            f"and clothing from the reference without altering them."
        )
    parts.append("Single still frame, no text, no watermark, no letterboxing.")
    return "\n\n".join(parts)


# ---------------------------------------------------------------- commands

def _image_client(scene):
    """Local ComfyUI image generation. Cloud image models are not used."""
    if scene.get("image_backend", "local") != "local":
        raise SystemExit("only the local image backend is supported; set \"image_backend\": \"local\"")
    client = comfy.Comfy()
    if not client.up():
        raise SystemExit(
            "ComfyUI is not running, so images cannot be generated.\n"
            "Start it with the rig launch script, then re-run this step."
        )
    return client


def cmd_sheets(scene, force=False):
    """Generate a character model sheet per character.

    These are the reference images fed into every keyframe generation, so the
    design is identical in every shot. This is the step that makes "correct
    character models" hold across a scene (issue #8).
    """
    d = scene_dir(scene)
    sheets_dir = d / "sheets"
    sheets_dir.mkdir(exist_ok=True)
    made = 0
    for key, ch in scene["characters"].items():
        out = sheets_dir / f"{key}.png"
        ch["sheet"] = f"sheets/{key}.png"
        if out.exists() and not force:
            print(f"  skip {key} (exists)")
            continue
        if not ch.get("sheet_prompt"):
            print(f"  ! {key} has no sheet_prompt")
            continue
        prompt = "\n\n".join(filter(None, [
            scene["style_block"],
            ch["sheet_prompt"],
            "Character model sheet: the same character shown full-body in three "
            "poses (front, three-quarter, side) on a plain flat background. "
            "Consistent proportions, colours and features across all three poses. "
            "No text, no labels, no watermark.",
        ]))
        print(f"  sheet {key} ...", flush=True)
        client = _image_client(scene)
        info = client.render_image(out, prompt, width=scene.get("image_size", 1024),
                                   height=scene.get("image_size", 1024),
                                   seed=scene["seed"],
                                   filename_prefix=f"endless/{scene['slug']}/sheet_{key}")
        print(f"    -> sheets/{key}.png in {info['wall_seconds']}s")
        made += 1
    print(f"sheets: {made} generated")
    return 0


def cmd_plan(scene):
    d = scene_dir(scene)
    print(f"scene: {scene['title']}  ->  {d}")
    print(f"backend: {scene['backend']}  canvas: {scene['width']}x{scene['height']}")
    total = 0
    for s in scene["shots"]:
        secs = s.get("seconds", 5)
        total += secs
        sheets = character_sheets(scene, s.get("characters"))
        print(f"  {s['id']:>6}  {secs:>4}s  chars={','.join(s.get('characters') or []) or '-':<18} "
              f"sheets={len(sheets)}  {s['keyframe_prompt'][:52]}")
    print(f"  total {total}s across {len(scene['shots'])} shots")
    print(f"\n  sheets:    {len(scene['characters'])} local image generation(s)")
    print(f"  keyframes: {len(scene['shots'])} local image generation(s), conditioned on the sheets")
    print(f"  render:    {len(scene['shots'])} local H3 clip(s) on the GPU")
    print(f"  text:      {llm.describe()}")
    return 0


def cmd_keyframes(scene, only=None, force=False):
    d = scene_dir(scene)
    done = 0
    for shot in scene["shots"]:
        if only and shot["id"] not in only:
            continue
        out = d / "keyframes" / f"{shot['id']}.png"
        if out.exists() and not force:
            print(f"  skip {shot['id']} (exists)")
            continue
        sheets = character_sheets(scene, shot.get("characters"))
        prompt = build_keyframe_prompt(scene, shot, sheets)
        print(f"  keyframe {shot['id']} (refs={len(sheets)}) ...", flush=True)
        client = _image_client(scene)
        info = client.render_image(out, prompt, width=scene["width"], height=scene["height"],
                                   seed=shot.get("seed", scene["seed"]),
                                   ref_image_paths=sheets,
                                   filename_prefix=f"endless/{scene['slug']}/kf_{shot['id']}")
        print(f"    -> keyframes/{shot['id']}.png in {info['wall_seconds']}s")
        done += 1
    print(f"keyframes: {done} generated")
    return 0


def cmd_render(scene, only=None, force=False):
    d = scene_dir(scene)
    if scene["backend"] == "local":
        client = comfy.Comfy()
        if not client.up():
            print("  ! ComfyUI is not running. Start it with /home/mik/2tb-disk/start-comfy.sh")
            return 2
        print(f"  ComfyUI up at {client.host}")
    done = 0
    for i, shot in enumerate(scene["shots"]):
        if only and shot["id"] not in only:
            continue
        kf = d / "keyframes" / f"{shot['id']}.png"
        out = d / "clips" / f"{shot['id']}.mp4"
        if out.exists() and not force:
            print(f"  skip {shot['id']} (exists)")
            continue
        if not kf.exists():
            print(f"  ! no keyframe for {shot['id']} -- run 'keyframes' first")
            continue

        secs = shot.get("seconds", 5)
        prompt = shot.get("motion_prompt") or shot["keyframe_prompt"]
        seed = shot.get("seed", scene["seed"] + i)
        print(f"  render {shot['id']} ({secs}s, seed={seed}) ...", flush=True)

        if scene["backend"] == "cloud":
            info = openrouter.generate_video(
                prompt, out, first_frame=kf, duration=int(secs),
                on_progress=lambda t, st: print(f"    ... {t}s {st}", flush=True))
            print(f"    -> {out.name} in {info['_wall_seconds']}s cost={info['_cost']}")
        else:
            info = client.render_i2v(
                out, prompt, kf,
                width=scene["width"], height=scene["height"], seconds=secs, seed=seed,
                steps=shot.get("steps", 8),
                lora=shot.get("lora", comfy.TURBO_FL2V_8STEP),
                filename_prefix=f"endless/{scene['slug']}/{shot['id']}")
            print(f"    -> {out.name} in {info['wall_seconds']}s ({info['bytes']//1024} KB)")
        done += 1
    print(f"render: {done} clip(s)")
    return 0


def cmd_assemble(scene):
    d = scene_dir(scene)
    clips = []
    for shot in scene["shots"]:
        p = d / "clips" / f"{shot['id']}.mp4"
        if p.exists():
            clips.append(p)
        else:
            print(f"  ! missing clip for {shot['id']}, skipping")
    if not clips:
        print("  ! nothing to assemble")
        return 2

    final = d / "final.mp4"
    if len(clips) == 1:
        subprocess.run(["ffmpeg", "-y", "-i", str(clips[0]), "-c", "copy", str(final)],
                       check=True, capture_output=True)
    else:
        # Concat demuxer keeps this a stream copy, so no re-encode and no quality loss.
        listing = d / "clips" / "concat.txt"
        listing.write_text("".join(f"file '{c.name}'\n" for c in clips))
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", str(final)],
            check=True, capture_output=True)
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(final)],
        capture_output=True, text=True).stdout.strip()
    print(f"  -> {final}  ({len(clips)} clips, {dur}s, {final.stat().st_size//1024} KB)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Endless scene orchestrator")
    p.add_argument("command",
                   choices=["plan", "sheets", "keyframes", "render", "assemble", "all"])
    p.add_argument("scene")
    p.add_argument("--shot", action="append", help="limit to this shot id (repeatable)")
    p.add_argument("--force", action="store_true", help="redo work that already exists")
    a = p.parse_args(argv)

    scene = load_scene(a.scene)
    print(f"=== {scene['title']} ===")
    if a.command == "plan":
        return cmd_plan(scene)
    if a.command == "sheets":
        return cmd_sheets(scene, a.force)
    if a.command == "keyframes":
        return cmd_keyframes(scene, a.shot, a.force)
    if a.command == "render":
        return cmd_render(scene, a.shot, a.force)
    if a.command == "assemble":
        return cmd_assemble(scene)
    # all
    for step in (lambda: cmd_sheets(scene, a.force),
                 lambda: cmd_keyframes(scene, a.shot, a.force),
                 lambda: cmd_render(scene, a.shot, a.force),
                 lambda: cmd_assemble(scene)):
        rc = step()
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
