#!/usr/bin/env python3
"""Endless dashboard.

Config, progress, clip review and episode assembly for the scene pipeline.

Follows the ac2 dashboard conventions: stdlib only, no database and no daemon
state (everything is read from files and the live process table per request),
bound to loopback, and token auth on EVERY route including reads.

It never starts or stops GPU work on its own. Running a pipeline step is an
explicit action from the UI, and each step reports clearly when ComfyUI is down
or the GPU is busy.

Routes (all require ?token=, Authorization: Bearer, or X-Token):
    GET  /                          HTML cockpit
    GET  /api/status                ComfyUI, GPU, disk, downloads
    GET  /api/scenes                scene list with per-step state
    GET  /api/scene/<slug>          scene detail: shots, keyframes, clips
    GET  /api/downloads             weight-download progress parsed from logs
    GET  /api/config                current defaults
    POST /api/config                update defaults (scenes/defaults.json)
    POST /api/run                   run a pipeline step for a scene
    GET  /media/<slug>/<kind>/<f>   keyframe / clip / sheet bytes (for playback)
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent      # the pipeline root
SCENES_DIR = ROOT / "scenes"
COMFY = os.environ.get("ENDLESS_COMFY_HOST", "http://127.0.0.1:8188")
IMAGE_COMFY = os.environ.get("ENDLESS_IMAGE_HOST", "http://127.0.0.1:8189")
MODELS_DIR = pathlib.Path(os.environ.get("ENDLESS_MODELS_DIR", str(ROOT / "models")))
HOST = os.environ.get("ENDLESS_DASH_HOST", "100.97.62.30")  # tailscale; use 127.0.0.1 for loopback-only
PORT = int(os.environ.get("ENDLESS_DASH_PORT", "8199"))
TOKEN_FILE = ROOT / "dashboard" / ".token"

# Steps the UI may run. keyframes/render/all are refused when the story
# check fails, so the dashboard cannot launch another cloned episode.
STEPS = ("plan", "sheets", "keyframes", "render", "assemble", "all")
GPU_STEPS = ("keyframes", "render", "all")
MAX_WRITE_SHOTS = 24
_RUN_LOCK = threading.Lock()
_RUNNING: dict[str, dict] = {}          # slug -> {step, started, proc, log}


# ------------------------------------------------------------------ helpers

def load_token() -> str:
    """Persistent token, created on first run with 0600 permissions."""
    if env := os.environ.get("ENDLESS_DASH_TOKEN"):
        return env
    if TOKEN_FILE.exists():
        tok = TOKEN_FILE.read_text().strip()
        if tok:
            return tok
    tok = secrets.token_urlsafe(24)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(tok + "\n")
    TOKEN_FILE.chmod(0o600)
    return tok


TOKEN = load_token()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "scene"


def scene_paths(slug: str) -> pathlib.Path:
    return SCENES_DIR / slug


def read_scene_json(path: pathlib.Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _import_story():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from pipeline.story import StoryError, validate
    return StoryError, validate


def story_verdict(raw: dict) -> dict:
    """Whether this scene is a story or a cloned episode."""
    try:
        StoryError, validate = _import_story()
        validate(raw)
        return {"ok": True, "error": ""}
    except Exception as e:
        name = type(e).__name__
        if name != "StoryError":
            return {"ok": False, "error": f"{name}: {e}"}
        return {"ok": False, "error": str(e)}


def list_scenes() -> list[dict]:
    """Every scene JSON, with the state of each pipeline step."""
    out = []
    for p in sorted(SCENES_DIR.glob("*.json")):
        if p.name == "defaults.json":
            continue
        raw = read_scene_json(p)
        if raw is None:
            out.append({"file": p.name, "slug": p.stem, "title": p.stem,
                        "error": "invalid JSON"})
            continue
        slug = raw.get("slug") or slugify(raw.get("title", p.stem))
        d = scene_paths(slug)
        shots = raw.get("shots") or []
        chars = raw.get("characters") or {}
        sheets_done = sum(1 for k in chars if (d / "sheets" / f"{k}.png").exists())
        kf_done = sum(1 for s in shots if (d / "keyframes" / f"{s['id']}.png").exists())
        # Clips may sit at clips/<shot>.mp4 (single model) or clips/<model>/<shot>.mp4
        # (several models rendered for comparison). Count both, or the library shows
        # 0/N for every episode the parallel renderer produces.
        clip_root = d / "clips"
        subdirs = [q for q in clip_root.iterdir() if q.is_dir()] if clip_root.is_dir() else []
        clips_done = 0
        for sh in shots:
            if (clip_root / f"{sh['id']}.mp4").exists():
                clips_done += 1
            elif any((q / f"{sh['id']}.mp4").exists() for q in subdirs):
                clips_done += 1
        final = d / "final.mp4"
        out.append({
            "file": p.name,
            "slug": slug,
            "title": raw.get("title", p.stem),
            "premise": (raw.get("premise") or "")[:280],
            "backend": raw.get("backend", "local"),
            "width": raw.get("width"), "height": raw.get("height"),
            "shots": len(shots),
            "seconds": sum(s.get("seconds", 5) for s in shots),
            "characters": len(chars),
            "sheets": {"done": sheets_done, "total": len(chars)},
            "keyframes": {"done": kf_done, "total": len(shots)},
            "clips": {"done": clips_done, "total": len(shots)},
            "final": {
                "exists": final.exists(),
                "bytes": final.stat().st_size if final.exists() else 0,
                "mtime": final.stat().st_mtime if final.exists() else 0,
            },
            "story": story_verdict(raw),
            "running": _RUNNING.get(slug, {}).get("step"),
        })
    out.sort(key=lambda s: (
        0 if (s.get("story") or {}).get("ok") and (s.get("final") or {}).get("exists") else
        1 if (s.get("story") or {}).get("ok") else 2,
        -((s.get("final") or {}).get("mtime") or 0),
        s.get("title") or "",
    ))
    return out


def scene_detail(slug: str) -> dict | None:
    d = scene_paths(slug)
    for p in SCENES_DIR.glob("*.json"):
        raw = read_scene_json(p)
        if raw and (raw.get("slug") or slugify(raw.get("title", p.stem))) == slug:
            # A shot may have a clip per MODEL, so a scene can be rendered by
            # more than one video model and compared side by side. Both layouts
            # are supported: clips/<shot>.mp4, and clips/<model>/<shot>.mp4.
            clip_root = d / "clips"
            models = sorted(p.name for p in clip_root.iterdir()
                            if p.is_dir()) if clip_root.is_dir() else []
            shots = []
            for s in (raw.get("shots") or []):
                kf = d / "keyframes" / f"{s['id']}.png"
                variants = []
                flat = clip_root / f"{s['id']}.mp4"
                if flat.exists():
                    variants.append({"model": "default", "bytes": flat.stat().st_size})
                for m in models:
                    v = clip_root / m / f"{s['id']}.mp4"
                    if v.exists():
                        variants.append({"model": m, "bytes": v.stat().st_size})
                shots.append({
                    "id": s["id"],
                    "seconds": s.get("seconds", 5),
                    "location": s.get("location") or "",
                    "characters": s.get("characters") or [],
                    "action": (s.get("action") or s.get("keyframe_prompt") or "")[:280],
                    "dialogue": [
                        {"speaker": ln.get("speaker") or "", "line": ln.get("line") or ""}
                        for ln in (s.get("dialogue") or [])
                        if isinstance(ln, dict)
                    ],
                    "keyframe": {"exists": kf.exists(), "bytes": kf.stat().st_size if kf.exists() else 0},
                    "clips": variants,
                    "clip": {"exists": bool(variants),
                             "bytes": max((v["bytes"] for v in variants), default=0)},
                })
            chars = []
            for k, ch in (raw.get("characters") or {}).items():
                sheet = d / "sheets" / f"{k}.png"
                chars.append({
                    "key": k,
                    "lock": ch.get("lock") or "",
                    "voice": ch.get("voice") or "",
                    "sheet": {"exists": sheet.exists(),
                              "bytes": sheet.stat().st_size if sheet.exists() else 0},
                })
            final = d / "final.mp4"
            return {
                "slug": slug, "file": p.name,
                "title": raw.get("title") or slug,
                "premise": raw.get("premise") or "",
                "width": raw.get("width"), "height": raw.get("height"),
                "story": story_verdict(raw),
                "shots": shots, "characters": chars,
                "out_dir": str(d),
                "final": {"exists": final.exists(),
                          "bytes": final.stat().st_size if final.exists() else 0},
                "run": _RUNNING.get(slug),
            }
    return None


def comfy_status(host: str = COMFY) -> dict:
    try:
        with urllib.request.urlopen(host + "/system_stats", timeout=5) as r:
            stats = json.loads(r.read())
        devs = stats.get("devices") or []
        queue = {}
        try:
            with urllib.request.urlopen(host + "/queue", timeout=5) as r:
                q = json.loads(r.read())
            queue = {"running": len(q.get("queue_running") or []),
                     "pending": len(q.get("queue_pending") or [])}
        except Exception:
            pass
        return {"up": True, "host": host,
                "version": stats.get("system", {}).get("comfyui_version"),
                "devices": [{"name": d.get("name"), "vram_total": d.get("vram_total"),
                             "vram_free": d.get("vram_free")} for d in devs],
                "queue": queue}
    except Exception as e:
        return {"up": False, "error": str(e)}


def gpu_status() -> list[dict]:
    """Read nvidia-smi. Read-only: never changes GPU state."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout
        gpus = []
        for line in out.strip().splitlines():
            idx, name, used, total, util = [x.strip() for x in line.split(",")]
            gpus.append({"index": int(idx), "name": name, "used_mb": int(used),
                         "total_mb": int(total), "util": int(util)})
        return gpus
    except Exception:
        return []


def disk_dir() -> pathlib.Path:
    if MODELS_DIR.exists():
        return MODELS_DIR
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from pipeline.comfy import _comfy_install
        cand = _comfy_install() / "models"
        if cand.exists():
            return cand
    except Exception:
        pass
    return ROOT


def disk_status() -> dict:
    try:
        path = disk_dir()
        u = shutil.disk_usage(path)
        return {"path": str(path), "total_gb": round(u.total / 2**30, 1),
                "free_gb": round(u.free / 2**30, 1),
                "used_pct": round(100 * u.used / u.total, 1)}
    except Exception as e:
        return {"error": str(e)}


DOWNLOAD_LOGS = ("download-h3.log", "download-ltx.log", "download-image.log")


def downloads_status() -> list[dict]:
    """Parse the weight-download logs for the last progress line per file."""
    out = []
    for name in DOWNLOAD_LOGS:
        p = ROOT / name
        if not p.exists():
            continue
        try:
            lines = p.read_text(errors="replace").splitlines()
        except OSError:
            continue
        current = None
        entries = []
        for line in lines:
            if m := re.search(r"\] GET\s+(\S+)", line):
                current = {"file": m.group(1), "pct": 0.0, "rate": "", "eta": ""}
                entries.append(current)
            elif (m := re.match(r"\s*([\d.]+)%\s+([\d.]+)/([\d.]+) GiB\s+([\d.]+) MiB/s\s+eta\s+([\d.]+) min", line)) and current:
                current.update({"pct": float(m.group(1)), "done_gib": float(m.group(2)),
                                "total_gib": float(m.group(3)), "rate": float(m.group(4)),
                                "eta": float(m.group(5))})
            elif "SKIP" in line and current is None:
                pass
        # Only the newest few matter for a progress view.
        for e in entries[-3:]:
            e["log"] = name
        out.extend(entries[-3:])
    return out


def run_active() -> bool:
    with _RUN_LOCK:
        return any(v.get("proc") and v["proc"].poll() is None for v in _RUNNING.values())


def start_step(slug: str, step: str) -> dict:
    """Launch one pipeline step as a subprocess. Never runs two at once."""
    if step not in STEPS:
        return {"ok": False, "error": f"unknown step {step!r}"}
    with _RUN_LOCK:
        if any(v.get("proc") and v["proc"].poll() is None for v in _RUNNING.values()):
            busy = [s for s, v in _RUNNING.items() if v.get("proc") and v["proc"].poll() is None]
            return {"ok": False, "error": f"a step is already running for {', '.join(busy)}"}
        scene_file = None
        for p in SCENES_DIR.glob("*.json"):
            raw = read_scene_json(p)
            if raw and (raw.get("slug") or slugify(raw.get("title", p.stem))) == slug:
                scene_file = p
                break
        if scene_file is None:
            return {"ok": False, "error": f"no scene file for slug {slug!r}"}
        raw = read_scene_json(scene_file) or {}
        if step in GPU_STEPS:
            verdict = story_verdict(raw)
            if not verdict["ok"]:
                return {"ok": False, "error": "story check failed: " + verdict["error"]}

        log = scene_paths(slug) / f"run-{step}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log, "w")
        proc = subprocess.Popen(
            [sys.executable, "-m", "pipeline.scene", step, str(scene_file)],
            cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"})
        _RUNNING[slug] = {"step": step, "started": time.time(), "proc": proc,
                          "log": str(log), "fh": fh}
    return {"ok": True, "step": step, "log": str(log)}


def run_log(slug: str, lines: int = 80) -> dict:
    entry = _RUNNING.get(slug)
    if not entry:
        return {"running": False, "log": ""}
    proc = entry["proc"]
    alive = proc.poll() is None
    try:
        text = pathlib.Path(entry["log"]).read_text(errors="replace")
    except OSError:
        text = ""
    tail = "\n".join(text.splitlines()[-lines:])
    if not alive and entry.get("fh"):
        try:
            entry["fh"].close()
        except Exception:
            pass
        entry["fh"] = None
    return {"running": alive, "step": entry["step"], "exit_code": proc.returncode,
            "log": tail, "out": entry.get("out")}


def start_write(premise: str, shots: int = 8) -> dict:
    """Ask the writers' room for a new scene file. Does not touch the GPU."""
    premise = (premise or "").strip()
    if not premise:
        return {"ok": False, "error": "a premise is required"}
    try:
        shots = max(4, min(int(shots or 8), MAX_WRITE_SHOTS))
    except (TypeError, ValueError):
        return {"ok": False, "error": "shots must be a number"}
    with _RUN_LOCK:
        if any(v.get("proc") and v["proc"].poll() is None for v in _RUNNING.values()):
            return {"ok": False, "error": "a step is already running"}
        out = SCENES_DIR / f"draft-{time.strftime('%Y%m%d-%H%M%S')}.json"
        log = SCENES_DIR / "write.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log, "w")
        proc = subprocess.Popen(
            [sys.executable, "-m", "pipeline.story", "write", premise,
             "--shots", str(shots), "--out", str(out)],
            cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"})
        _RUNNING["_write"] = {"step": "write", "started": time.time(), "proc": proc,
                              "log": str(log), "fh": fh, "out": out.name}
    return {"ok": True, "step": "write", "file": out.name}


# ---------------------------------------------------------------- HTTP layer

class Handler(BaseHTTPRequestHandler):
    server_version = "endless-dashboard"

    def log_message(self, fmt, *args):        # keep the console quiet
        pass

    # -- auth: every route, including reads --
    def _authed(self, query) -> bool:
        if self.headers.get("X-Token") == TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:].strip() == TOKEN:
            return True
        return query.get("token", [None])[0] == TOKEN

    def _send(self, code: int, body: bytes, ctype: str = "application/json",
              extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        if not (extra or {}).get("Content-Length"):
            self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, default=str).encode())

    def _deny(self):
        self._json({"error": "unauthorized"}, 401)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authed(q):
            return self._deny()
        path = unquote(u.path)

        if path in ("/", "/index.html"):
            html = (pathlib.Path(__file__).parent / "index.html")
            if not html.exists():
                return self._json({"error": "index.html missing"}, 500)
            return self._send(200, html.read_bytes(), "text/html; charset=utf-8")

        if path == "/api/status":
            return self._json({
                "comfy": comfy_status(COMFY),
                "comfy_image": comfy_status(IMAGE_COMFY),
                "gpus": gpu_status(),
                "disk": disk_status(),
                "running": {s: v.get("step") for s, v in _RUNNING.items()
                            if v.get("proc") and v["proc"].poll() is None},
                "models_dir": str(disk_dir()),
            })

        if path == "/api/scenes":
            return self._json({"scenes": list_scenes()})

        if path == "/api/downloads":
            return self._json({"downloads": downloads_status()})

        if path == "/api/config":
            return self._json({
                "defaults": read_scene_json(SCENES_DIR / "defaults.json") or {},
                "steps": list(STEPS),
                "comfy_host": COMFY,
                "image_host": IMAGE_COMFY,
                "models_dir": str(MODELS_DIR),
                "llm": _llm_describe(),
            })

        if path.startswith("/api/scene/"):
            slug = path[len("/api/scene/"):]
            detail = scene_detail(slug)
            if detail is None:
                return self._json({"error": f"unknown scene {slug}"}, 404)
            return self._json(detail)

        if path.startswith("/api/log/"):
            return self._json(run_log(path[len("/api/log/"):]))

        if path.startswith("/media/"):
            return self._media(path[len("/media/"):])

        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authed(q):
            return self._deny()
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "invalid JSON body"}, 400)

        if u.path == "/api/run":
            slug, step = body.get("slug"), body.get("step")
            if not slug or not step:
                return self._json({"error": "slug and step required"}, 400)
            res = start_step(slug, step)
            return self._json(res, 200 if res.get("ok") else 409)

        if u.path == "/api/write":
            res = start_write(body.get("premise") or "", body.get("shots") or 8)
            return self._json(res, 200 if res.get("ok") else 409)

        if u.path == "/api/config":
            SCENES_DIR.mkdir(parents=True, exist_ok=True)
            target = SCENES_DIR / "defaults.json"
            current = read_scene_json(target) or {}
            current.update(body.get("defaults") or {})
            target.write_text(json.dumps(current, indent=2) + "\n")
            return self._json({"ok": True, "defaults": current})

        return self._json({"error": "not found"}, 404)

    def _media(self, rest: str):
        """Serve a scene artefact for playback. Path-contained to SCENES_DIR."""
        parts = [p for p in rest.split("/") if p]
        # /media/<slug>/final.mp4 is the assembled cut, which lives in the
        # scene directory rather than in a kind subdirectory.
        if len(parts) == 2 and parts[1] == "final.mp4":
            slug, rel = parts[0], pathlib.Path("final.mp4")
        elif len(parts) >= 3:
            slug, rel = parts[0], pathlib.Path(parts[1], *parts[2:])
        else:
            return self._json({"error": "bad media path"}, 400)
        base = (SCENES_DIR / slug).resolve()
        target = (base / rel).resolve()
        # Containment: never serve anything outside the scene's own directory.
        if not str(target).startswith(str(base) + os.sep) or not target.is_file():
            return self._json({"error": "not found"}, 404)
        ctype = {".mp4": "video/mp4", ".webm": "video/webm",
                 ".png": "image/png", ".jpg": "image/jpeg",
                 ".jpeg": "image/jpeg", ".webp": "image/webp",
                 ".gif": "image/gif"}.get(target.suffix.lower(), "application/octet-stream")

        # Byte ranges matter for video: without them a browser cannot seek, and
        # some players will not start a large file at all. This serves 206
        # responses for a Range request and full content otherwise.
        size = target.stat().st_size
        rng = self.headers.get("Range", "")
        start, end = 0, size - 1
        partial = False
        if rng.startswith("bytes="):
            spec = rng[len("bytes="):].split(",")[0].strip()
            a, _, b = spec.partition("-")
            try:
                if a == "":                      # suffix: last N bytes
                    start = max(0, size - int(b)); end = size - 1
                else:
                    start = int(a)
                    end = int(b) if b else size - 1
                end = min(end, size - 1)
                partial = 0 <= start <= end < size
            except ValueError:
                partial = False
        if not partial:
            start, end = 0, size - 1

        length = end - start + 1
        with open(target, "rb") as f:
            f.seek(start)
            data = f.read(length)
        code = 206 if (partial and rng) else 200
        extra = {"Accept-Ranges": "bytes", "Content-Length": str(length)}
        if code == 206:
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        self._send(code, data, ctype, extra)


def _llm_describe() -> str:
    try:
        sys.path.insert(0, str(ROOT))
        from pipeline import llm
        return llm.describe()
    except Exception as e:
        return f"unavailable ({e})"


def main():
    SCENES_DIR.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Endless dashboard on http://{HOST}:{PORT}/?token={TOKEN}", flush=True)
    print(f"  pipeline root : {ROOT}", flush=True)
    print(f"  scenes        : {SCENES_DIR}", flush=True)
    print(f"  models        : {MODELS_DIR}", flush=True)
    print(f"  ComfyUI       : {COMFY}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
        srv.shutdown()


if __name__ == "__main__":
    main()
