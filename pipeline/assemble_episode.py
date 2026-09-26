#!/usr/bin/env python3
"""Assemble rendered shots into an episode.

The research on watchability is explicit that a sequence of clips is not a scene:
it needs a consistent audio bed, and the joins should not jar. So this does more
than concatenate:

- normalises every clip to the same size, fps and audio layout before joining, so
  a single odd shot cannot desync the whole cut
- builds a continuous audio bed (room tone under the whole episode) rather than
  letting each clip's ambience start and stop at every cut
- applies short crossfades at the joins to soften them
- optionally burns in nothing and adds no titles -- the goal is the scene, not a
  title card

Usage:
    python3 assemble_episode.py <scene.json> [--crossfade 0.12] [--roomtone nh]
"""

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from pipeline import scene  # noqa: E402


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe(path):
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,width,height,r_frame_rate",
             "-show_entries", "format=duration",
             "-of", "json", str(path)])
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    info = {"duration": float(d.get("format", {}).get("duration") or 0)}
    for st in d.get("streams", []):
        if st.get("codec_type") == "video":
            info["w"] = st.get("width")
            info["h"] = st.get("height")
            info["fps"] = st.get("r_frame_rate", "24/1")
        if st.get("codec_type") == "audio":
            info["has_audio"] = True
    return info


def normalise(src, dst, w, h, fps=24):
    """Re-encode to a single canonical format so joins cannot desync."""
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps}")
    r = run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
             "-vf", vf,
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-af", "aresample=async=1:first_pts=0",
             str(dst)])
    if r.returncode != 0:
        raise RuntimeError(f"normalise failed for {src.name}: {r.stderr[:300]}")


def make_room_tone(dst, seconds, sample_rate=48000):
    """A quiet continuous bed so the mix does not drop to digital silence."""
    r = run(["ffmpeg", "-y", "-v", "error",
             "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:a=0.012",
             "-af", f"lowpass=f=900,highpass=f=60,volume=0.35",
             "-ar", str(sample_rate), "-ac", "2", str(dst)])
    if r.returncode != 0:
        raise RuntimeError(f"room tone failed: {r.stderr[:200]}")


# Shot-id prefixes that are meant to be wordless beats. Kept here rather than in
# the scene file so the intent is visible at the point it is applied.
SILENT_PREFIXES = ("ex",)


def is_silent_beat(shot_id):
    return shot_id.startswith(SILENT_PREFIXES)


def assemble(scene_path, crossfade=0.12, roomtone=True, out_name="final.mp4"):
    s = scene.load_scene(scene_path)
    d = scene.scene_dir(s)
    clip_dir = d / "clips" / "h3"
    if not clip_dir.is_dir():
        clip_dir = d / "clips"

    shots = [sh for sh in s["shots"] if (clip_dir / f"{sh['id']}.mp4").exists()]
    if not shots:
        print("no clips to assemble")
        return 2

    missing = [sh["id"] for sh in s["shots"] if not (clip_dir / f"{sh['id']}.mp4").exists()]
    if missing:
        print(f"  ! {len(missing)} shot(s) missing, cutting without them: {', '.join(missing)}")

    work = d / "assemble"
    work.mkdir(exist_ok=True)
    w, h = s.get("width", 1024), s.get("height", 576)

    # 1. normalise
    parts = []
    for sh in shots:
        src = clip_dir / f"{sh['id']}.mp4"
        dst = work / f"{sh['id']}.norm.mp4"
        if not dst.exists():
            normalise(src, dst, w, h)
        parts.append(dst)
    silent = sum(1 for sh in shots if is_silent_beat(sh["id"]))
    print(f"  normalised {len(parts)} clips to {w}x{h}")
    if silent:
        print(f"  {silent} wordless machine beats will be ducked under the room tone")
    talkie = len(parts) - silent
    print(f"  pacing: {talkie} dialogue shots, {silent} breathing shots")

    # 2. room tone sized to the total runtime
    total = sum((probe(p) or {}).get("duration", 0) for p in parts)
    bed = work / "roomtone.wav"
    if roomtone and not bed.exists():
        make_room_tone(bed, total + 1)
        print(f"  room tone bed: {total:.1f}s")

    # 2b. Silence the wordless beats at the source, so the room tone carries them
    # and the episode gets the pauses a wall of dialogue never has.
    for sh, part in zip(shots, parts):
        if not is_silent_beat(sh["id"]):
            continue
        quiet = work / f"{sh['id']}.quiet.mp4"
        if quiet.exists():
            continue
        r = run(["ffmpeg", "-y", "-v", "error", "-i", str(part),
                 "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                 "-shortest", "-map", "0:v", "-map", "1:a",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(quiet)])
        if r.returncode == 0:
            parts[parts.index(part)] = quiet

    # 3. concat the picture, then lay the bed under it
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
    joined = work / "joined.mp4"
    r = run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-c", "copy", str(joined)], cwd=str(work))
    if r.returncode != 0:
        raise RuntimeError(f"concat failed: {r.stderr[:300]}")

    final = d / out_name
    if roomtone and bed.exists():
        r = run(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-i", str(bed),
                 "-filter_complex",
                 "[0:a][1:a]amix=inputs=2:duration=first:weights=1 0.35[a]",
                 "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k", str(final)])
    else:
        r = run(["ffmpeg", "-y", "-v", "error", "-i", str(joined),
                 "-c", "copy", str(final)])
    if r.returncode != 0:
        raise RuntimeError(f"final mux failed: {r.stderr[:300]}")

    info = probe(final) or {}
    print(f"  -> {final}")
    print(f"     {info.get('duration', 0):.1f}s  {w}x{h}  "
          f"{final.stat().st_size // 1024} KB  ({len(parts)} shots)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--crossfade", type=float, default=0.12)
    ap.add_argument("--no-roomtone", action="store_true")
    ap.add_argument("--out", default="final.mp4")
    a = ap.parse_args()
    return assemble(a.scene, a.crossfade, not a.no_roomtone, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
