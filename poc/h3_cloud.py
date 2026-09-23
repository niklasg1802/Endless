"""Generate one clip with MiniMax H3 via OpenRouter's async video API.

Usage:
    python3 poc/h3_cloud.py <name> <prompt_file> [--duration 8] [--ref image.png ...] [--first-frame image.png]

Reads OPENROUTER_API_KEY from .env. Writes poc/out/<name>.mp4 and <name>.json (job metadata).
"""

import argparse
import base64
import json
import mimetypes
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "poc" / "out"
API = "https://openrouter.ai/api/v1/videos"
MODEL = "minimax/hailuo-3"


def api_key():
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("OPENROUTER_API_KEY missing in .env")


def request(url, key, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
            return body if r.headers.get_content_type().startswith("video/") else json.loads(body)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode(errors='replace')}")


def image_part(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    b64 = base64.b64encode(pathlib.Path(path).read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("prompt_file")
    p.add_argument("--duration", type=int, default=8)
    p.add_argument("--ref", action="append", default=[], help="reference image (reference-to-video)")
    p.add_argument("--first-frame", help="exact first frame (image-to-video)")
    args = p.parse_args()

    key = api_key()
    payload = {
        "model": MODEL,
        "prompt": pathlib.Path(args.prompt_file).read_text().strip(),
        "duration": args.duration,
        "aspect_ratio": "16:9",
        "generate_audio": True,
    }
    if args.ref:
        payload["input_references"] = [image_part(r) for r in args.ref]
    if args.first_frame:
        payload["frame_images"] = [{**image_part(args.first_frame), "frame_type": "first_frame"}]

    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    job = request(API, key, payload)
    print(f"submitted {job.get('id')} status={job.get('status')}", flush=True)

    while job.get("status") not in ("completed", "failed", "cancelled", "expired"):
        time.sleep(15)
        job = request(job["polling_url"], key)
        print(f"  {int(time.time() - started)}s status={job.get('status')}", flush=True)

    job["_wall_seconds"] = round(time.time() - started)
    (OUT / f"{args.name}.json").write_text(json.dumps(job, indent=2))
    if job["status"] != "completed":
        sys.exit(f"job {job['status']}: {job.get('error')}")

    video = request(job["unsigned_urls"][0], key)
    (OUT / f"{args.name}.mp4").write_bytes(video)
    print(f"saved poc/out/{args.name}.mp4 ({len(video) // 1024} KB) in {job['_wall_seconds']}s, usage={job.get('usage')}")


if __name__ == "__main__":
    main()
