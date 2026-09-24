"""Shared OpenRouter client for the Endless pipeline.

Stdlib only, same approach as poc/h3_cloud.py so there is one way to talk to
OpenRouter in this repo. The API key is read from .env, which is gitignored --
never hard-code a key here, the repo is public.
"""

import base64
import json
import mimetypes
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHAT_API = "https://openrouter.ai/api/v1/chat/completions"
VIDEO_API = "https://openrouter.ai/api/v1/videos"

# Cloud video model. Decision 0002: H3 is primary, but its cloud moderation
# rejects show and character names in text AND recognises the characters in
# images, so cloud H3 can only be used for name-free prompts. Local H3 has no
# moderation -- that is why the rig exists.
DEFAULT_VIDEO_MODEL = "minimax/hailuo-3"
# Image model used for keyframes (POC #3: produced a show-accurate design, $0.07).
DEFAULT_IMAGE_MODEL = "google/gemini-3.1-flash-image"


def api_key():
    """Read OPENROUTER_API_KEY from .env. Never log or return this elsewhere."""
    env = ROOT / ".env"
    if not env.exists():
        sys.exit(f"{env} not found -- create it with OPENROUTER_API_KEY=...")
    for line in env.read_text().splitlines():
        line = line.strip()
        if line.startswith("OPENROUTER_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if key:
                return key
    sys.exit("OPENROUTER_API_KEY missing from .env")


def request(url, key, payload=None, timeout=120):
    """POST payload, or GET when payload is None. Returns parsed JSON or bytes."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            ctype = r.headers.get_content_type()
            if ctype.startswith("video/") or ctype == "application/octet-stream":
                return body
            return json.loads(body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {detail[:600]}") from None


def image_part(path):
    """Encode a local image as an OpenRouter image_url content part."""
    path = pathlib.Path(path)
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def chat(prompt, images=(), model=None, key=None, json_mode=False):
    """One-shot text completion. Returns (text, usage)."""
    key = key or api_key()
    content = [{"type": "text", "text": prompt}]
    content += [image_part(i) for i in images]
    payload = {"model": model or "anthropic/claude-sonnet-5",
               "messages": [{"role": "user", "content": content}]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    resp = request(CHAT_API, key, payload)
    msg = resp["choices"][0]["message"]
    return msg.get("content") or "", resp.get("usage", {})


def generate_image(prompt, images=(), model=None, key=None, aspect_ratio="16:9"):
    """Generate or edit an image. Returns a list of raw PNG bytes."""
    key = key or api_key()
    content = [{"type": "text", "text": prompt}]
    content += [image_part(i) for i in images]
    payload = {
        "model": model or DEFAULT_IMAGE_MODEL,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": aspect_ratio},
    }
    resp = request(CHAT_API, key, payload)
    msg = resp["choices"][0]["message"]
    out = []
    for img in (msg.get("images") or []):
        out.append(base64.b64decode(img["image_url"]["url"].split(",", 1)[1]))
    if not out:
        raise RuntimeError(
            f"no image returned (finish={resp['choices'][0].get('finish_reason')}); "
            f"text={msg.get('content')!r}"
        )
    return out, resp.get("usage", {})


def generate_video(prompt, out_path, first_frame=None, refs=(),
                   duration=8, model=None, key=None, resolution=None,
                   aspect_ratio="16:9", poll=15, on_progress=None):
    """Submit a video job and poll until done, then write the mp4 to out_path.

    `first_frame` pins the opening frame (the keyframe-first method from POC #3).
    `refs` are reference images for consistency across shots (POC #1 shot2).
    Returns the job dict (with _wall_seconds and _cost).
    """
    key = key or api_key()
    payload = {
        "model": model or DEFAULT_VIDEO_MODEL,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "generate_audio": True,
    }
    if resolution:
        payload["resolution"] = resolution
    if refs:
        payload["input_references"] = [image_part(r) for r in refs]
    if first_frame:
        payload["frame_images"] = [
            {**image_part(first_frame), "frame_type": "first_frame"}
        ]

    started = time.time()
    job = request(VIDEO_API, key, payload)
    while job.get("status") not in ("completed", "failed", "cancelled", "expired"):
        time.sleep(poll)
        job = request(job["polling_url"], key)
        if on_progress:
            on_progress(int(time.time() - started), job.get("status"))

    job["_wall_seconds"] = round(time.time() - started)
    job["_cost"] = (job.get("usage") or {}).get("cost")
    if job["status"] != "completed":
        raise RuntimeError(f"video job {job['status']}: {job.get('error')}")

    video = request(job["unsigned_urls"][0], key)
    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out_path).write_bytes(video)
    return job
