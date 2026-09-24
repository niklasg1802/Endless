"""ComfyUI backend for local MiniMax H3 rendering.

Drives the ComfyUI HTTP API on 127.0.0.1:8188. Builds an API-format prompt graph
from the same node set the official workflow templates use, so the parameters
match what ComfyUI itself ships.

The node input names below were read out of this install's source
(comfy_extras/nodes_minimax_h3.py, nodes_custom_sampler.py, nodes_video.py,
nodes_audio.py) rather than guessed -- a wrong name is a validation error.

Stdlib only.
"""

import json
import mimetypes
import pathlib
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_HOST = "http://127.0.0.1:8188"

# Model filenames as they sit in ComfyUI/models (see H3-SETUP.md).
FL2VA = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
REF2VA = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_int8_convrot.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
TURBO_FL2V_8STEP = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
TURBO_FL2V_4STEP = "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"
TURBO_REF2V_4STEP = "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"

# Frame count at 24 fps, snapped to the model's 17k+5 grid (see the node tooltip).
FPS = 24
VALID_LENGTHS = tuple(17 * k + 5 for k in range(1, 22))  # 22, 39, ... 362


def length_for_seconds(seconds, minimum=5):
    """Smallest valid frame count that covers `seconds` at 24 fps."""
    want = max(minimum, round(seconds * FPS))
    for n in VALID_LENGTHS:
        if n >= want:
            return n
    return VALID_LENGTHS[-1]


class ComfyError(RuntimeError):
    pass


class Comfy:
    def __init__(self, host=DEFAULT_HOST, client_id=None):
        self.host = host.rstrip("/")
        self.client_id = client_id or uuid.uuid4().hex

    # ---- HTTP ----

    def _request(self, path, payload=None, method=None, timeout=120):
        url = self.host + path
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            raise ComfyError(f"HTTP {e.code} {path}: {e.read().decode(errors='replace')[:800]}") from None
        except urllib.error.URLError as e:
            raise ComfyError(
                f"cannot reach ComfyUI at {self.host} ({e.reason}). "
                f"Start it with /home/mik/2tb-disk/start-comfy.sh"
            ) from None

    def up(self):
        try:
            self._request("/system_stats", timeout=10)
            return True
        except ComfyError:
            return False

    def object_info(self, node=None):
        return self._request(f"/object_info/{node}" if node else "/object_info", timeout=120)

    def stats(self):
        return self._request("/system_stats", timeout=30)

    def upload_image(self, path, subfolder=""):
        """Upload a local image into ComfyUI's input dir. Returns the stored name."""
        path = pathlib.Path(path)
        if not path.exists():
            raise ComfyError(f"image not found: {path}")
        boundary = "----endless" + uuid.uuid4().hex
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        body = b""
        for name, value in (("subfolder", subfolder), ("type", "input"), ("overwrite", "true")):
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode()
        body += (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
        body += path.read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()

        req = urllib.request.Request(self.host + "/upload/image", data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ComfyError(f"upload failed HTTP {e.code}: {e.read().decode(errors='replace')[:400]}") from None
        # ComfyUI may place it in a subfolder; LoadImage wants that prefix.
        sub = out.get("subfolder") or ""
        return f"{sub}/{out['name']}" if sub else out["name"]

    # ---- execution ----

    def queue(self, graph):
        resp = self._request("/prompt", {"prompt": graph, "client_id": self.client_id})
        if "prompt_id" not in resp:
            raise ComfyError(f"queue rejected: {json.dumps(resp)[:800]}")
        return resp["prompt_id"]

    def wait(self, prompt_id, timeout=7200, poll=3, on_progress=None):
        """Block until the prompt finishes. Returns the history entry."""
        started = time.time()
        while True:
            hist = self._request(f"/history/{prompt_id}", timeout=60)
            if prompt_id in hist:
                entry = hist[prompt_id]
                status = (entry.get("status") or {})
                if status.get("status_str") == "error" or not status.get("completed", True):
                    msgs = status.get("messages") or []
                    raise ComfyError(f"execution failed: {json.dumps(msgs)[:1200]}")
                return entry
            if time.time() - started > timeout:
                raise ComfyError(f"timed out after {timeout}s waiting for {prompt_id}")
            if on_progress:
                on_progress(int(time.time() - started))
            time.sleep(poll)

    def interrupt(self):
        try:
            self._request("/interrupt", {}, timeout=15)
        except ComfyError:
            pass

    # ---- graph building ----

    @staticmethod
    def _i2v_graph(prompt, width, height, length, seed, first_frame,
                   steps=8, shift_video=12.0, shift_audio=3.0,
                   unet=FL2VA, encoder=ENCODER, video_vae=VIDEO_VAE,
                   audio_vae=AUDIO_VAE, lora=TURBO_FL2V_8STEP,
                   lora_strength=1.0, filename_prefix="endless/shot"):
        """Keyframe-first: one image pinned as the opening frame (POC #3 method)."""
        g = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": unet, "weight_dtype": "default"}},
            "4": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": encoder, "type": "minimax", "device": "default"}},
            "5": {"class_type": "VAELoader", "inputs": {"vae_name": video_vae}},
            "6": {"class_type": "VAELoader", "inputs": {"vae_name": audio_vae}},
            "7": {"class_type": "LoadImage", "inputs": {"image": first_frame}},
            "8": {"class_type": "MiniMaxH3ImageToVideo",
                  "inputs": {"clip": ["4", 0], "vae": ["5", 0], "prompt": prompt,
                             "width": width, "height": height, "length": length,
                             "first_frame": ["7", 0]}},
            "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
            "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
            "12": {"class_type": "BasicGuider",
                   "inputs": {"model": ["3", 0], "conditioning": ["8", 0]}},
            "13": {"class_type": "SamplerCustomAdvanced",
                   "inputs": {"noise": ["11", 0], "guider": ["12", 0], "sampler": ["9", 0],
                              "sigmas": ["10", 0], "latent_image": ["8", 1]}},
            "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["5", 0]}},
            "15": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["13", 0], "vae": ["6", 0]}},
            "16": {"class_type": "CreateVideo",
                   "inputs": {"images": ["14", 0], "fps": FPS, "audio": ["15", 0]}},
            "17": {"class_type": "SaveVideo",
                   "inputs": {"video": ["16", 0], "filename_prefix": filename_prefix}},
        }
        if lora:
            g["2"] = {"class_type": "LoraLoaderModelOnly",
                      "inputs": {"model": ["1", 0], "lora_name": lora,
                                 "strength_model": lora_strength}}
            model_src = ["2", 0]
        else:
            model_src = ["1", 0]
        g["3"] = {"class_type": "MiniMaxH3SigmaShift",
                  "inputs": {"model": model_src, "shift_video": shift_video,
                             "shift_audio": shift_audio}}
        g["10"] = {"class_type": "BasicScheduler",
                   "inputs": {"model": ["3", 0], "scheduler": "simple",
                              "steps": steps, "denoise": 1.0}}
        return g

    @staticmethod
    def _r2v_graph(prompt, width, height, length, seed, ref_images,
                   steps=4, shift_video=12.0, shift_audio=3.0,
                   unet=REF2VA, encoder=ENCODER, video_vae=VIDEO_VAE,
                   audio_vae=AUDIO_VAE, lora=TURBO_REF2V_4STEP,
                   lora_strength=1.0, ref_image_size="match",
                   filename_prefix="endless/shot"):
        """Reference-to-video: character sheets (and optionally audio) as refs.

        Up to 9 reference images. This is the path that keeps a character's
        design consistent across shots (issue #8).
        """
        if len(ref_images) > 9:
            raise ComfyError(f"at most 9 reference images, got {len(ref_images)}")
        g = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": unet, "weight_dtype": "default"}},
            "4": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": encoder, "type": "minimax", "device": "default"}},
            "5": {"class_type": "VAELoader", "inputs": {"vae_name": video_vae}},
            "6": {"class_type": "VAELoader", "inputs": {"vae_name": audio_vae}},
            "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
            "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
            "12": {"class_type": "BasicGuider",
                   "inputs": {"model": ["3", 0], "conditioning": ["8", 0]}},
            "13": {"class_type": "SamplerCustomAdvanced",
                   "inputs": {"noise": ["11", 0], "guider": ["12", 0], "sampler": ["9", 0],
                              "sigmas": ["10", 0], "latent_image": ["8", 1]}},
            "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["5", 0]}},
            "15": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["13", 0], "vae": ["6", 0]}},
            "16": {"class_type": "CreateVideo",
                   "inputs": {"images": ["14", 0], "fps": FPS, "audio": ["15", 0]}},
            "17": {"class_type": "SaveVideo",
                   "inputs": {"video": ["16", 0], "filename_prefix": filename_prefix}},
        }
        # ref_image_N are autogrow inputs, numbered from 1.
        ref_inputs = {}
        for n, name in enumerate(ref_images, start=1):
            node_id = str(100 + n)
            g[node_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
            ref_inputs[f"ref_image_{n}"] = [node_id, 0]
        g["8"] = {"class_type": "MiniMaxH3ReferenceToVideo",
                  "inputs": {"clip": ["4", 0], "vae": ["5", 0], "prompt": prompt,
                             "width": width, "height": height, "length": length,
                             "ref_image_size": ref_image_size, **ref_inputs}}
        if lora:
            g["2"] = {"class_type": "LoraLoaderModelOnly",
                      "inputs": {"model": ["1", 0], "lora_name": lora,
                                 "strength_model": lora_strength}}
            model_src = ["2", 0]
        else:
            model_src = ["1", 0]
        g["3"] = {"class_type": "MiniMaxH3SigmaShift",
                  "inputs": {"model": model_src, "shift_video": shift_video,
                             "shift_audio": shift_audio}}
        g["10"] = {"class_type": "BasicScheduler",
                   "inputs": {"model": ["3", 0], "scheduler": "simple",
                              "steps": steps, "denoise": 1.0}}
        return g

    def render_i2v(self, out_path, prompt, first_frame_path, width=864, height=480,
                   seconds=5, seed=1, **kw):
        """Animate a keyframe. Uploads the image, queues the graph, waits, returns info."""
        name = self.upload_image(first_frame_path)
        length = kw.pop("length", None) or length_for_seconds(seconds)
        graph = self._i2v_graph(prompt, width, height, length, seed, name, **kw)
        return self._run(graph, out_path, prompt)

    def render_r2v(self, out_path, prompt, ref_image_paths, width=864, height=480,
                   seconds=5, seed=1, **kw):
        """Reference-to-video render (character sheets for consistency)."""
        names = [self.upload_image(p) for p in ref_image_paths]
        length = kw.pop("length", None) or length_for_seconds(seconds)
        graph = self._r2v_graph(prompt, width, height, length, seed, names, **kw)
        return self._run(graph, out_path, prompt)

    # ---- local image generation (Qwen-Image-2.1) ----

    @staticmethod
    def _image_graph(prompt, width, height, seed, steps=25, cfg=1.0,
                     unet="qwen_image_2.1_int8_convrot.safetensors",
                     encoder="qwen3vl_8b_int8_convrot.safetensors",
                     vae="qwen_image_2.1_vae_bf16.safetensors",
                     ref_images=(), loras=(), filename_prefix="endless/img"):
        """Qwen-Image-2.1 generate, or edit when ref_images are supplied.

        Mirrors the node set in the official templates shipped with ComfyUI
        (image_qwen_image_2_1_t2i.json / ..._image_edit.json): UNETLoader ->
        optional LoRAs -> KSampler, with TextEncodeQwenImage21 for conditioning.

        ref_image_N are autogrow inputs on TextEncodeQwenImage21 and are what
        keep a character's design consistent between the model sheet and every
        keyframe.
        """
        g = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": unet, "weight_dtype": "default"}},
            "4": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": encoder, "type": "qwen_image", "device": "default"}},
            "5": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
            "6": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": width, "height": height, "batch_size": 1}},
            "9": {"class_type": "KSampler",
                  "inputs": {"model": ["3", 0], "positive": ["8", 0], "negative": ["8", 1],
                             "latent_image": ["6", 0], "seed": seed, "steps": steps,
                             "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                             "denoise": 1.0}},
            "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["5", 0]}},
            "11": {"class_type": "SaveImage",
                   "inputs": {"images": ["10", 0], "filename_prefix": filename_prefix}},
        }
        cond_inputs = {"clip": ["4", 0], "vae": ["5", 0], "prompt": prompt, "resolution": 1024}
        for n, name in enumerate(ref_images, start=1):
            node_id = str(200 + n)
            g[node_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
            cond_inputs[f"image_{n}"] = [node_id, 0]
        g["8"] = {"class_type": "TextEncodeQwenImage21", "inputs": cond_inputs}

        model_src = ["1", 0]
        for i, (lora_name, strength) in enumerate(loras, start=1):
            node_id = str(300 + i)
            g[node_id] = {"class_type": "LoraLoaderModelOnly",
                          "inputs": {"model": model_src, "lora_name": lora_name,
                                     "strength_model": strength}}
            model_src = [node_id, 0]
        g["3"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": model_src, "shift": 3.1}}
        return g

    def render_image(self, out_path, prompt, width=1024, height=1024, seed=1,
                     ref_image_paths=(), **kw):
        """Generate one image locally, optionally conditioned on reference images."""
        if not self.up():
            raise ComfyError(
                "ComfyUI is not running. Start it with the rig launch script."
            )
        names = [self.upload_image(p) for p in ref_image_paths]
        graph = self._image_graph(prompt, width, height, seed, ref_images=names, **kw)
        started = time.time()
        pid = self.queue(graph)
        entry = self.wait(pid, on_progress=lambda s: print(f"    ... {s}s", flush=True))
        produced = [p for p in self._outputs_of(entry)
                    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
        if not produced:
            raise ComfyError("image run produced no output")
        src = max(produced, key=lambda p: p.stat().st_size)
        out_path = pathlib.Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(src.read_bytes())
        return {"prompt_id": pid, "wall_seconds": round(time.time() - started),
                "out": str(out_path), "bytes": out_path.stat().st_size}

    def _run(self, graph, out_path, prompt):
        if not self.up():
            raise ComfyError(
                "ComfyUI is not running. Start it with /home/mik/2tb-disk/start-comfy.sh "
                "(and make sure no large download is in flight -- the 2 TB disk is "
                "NTFS over FUSE and serialises)."
            )
        started = time.time()
        pid = self.queue(graph)
        entry = self.wait(pid, on_progress=lambda s: print(f"    ... {s}s", flush=True))
        elapsed = round(time.time() - started)

        produced = self._outputs_of(entry)
        if not produced:
            raise ComfyError("execution finished but produced no video output")
        src = max(produced, key=lambda p: p.stat().st_size)
        out_path = pathlib.Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(src.read_bytes())
        return {"prompt_id": pid, "wall_seconds": elapsed, "source": str(src),
                "out": str(out_path), "bytes": out_path.stat().st_size}

    def _outputs_of(self, entry):
        """Absolute paths of video files this run produced."""
        out = []
        root = pathlib.Path(self._output_root())
        for node_out in (entry.get("outputs") or {}).values():
            for key in ("images", "videos", "gifs"):
                for item in (node_out.get(key) or []):
                    p = root / item.get("subfolder", "") / item["filename"]
                    if p.exists() and p.suffix.lower() in (".mp4", ".webm", ".mkv", ".gif"):
                        out.append(p)
        return out

    def _output_root(self):
        # ComfyUI's --output-directory default is <install>/output
        return pathlib.Path(__file__).resolve().parent.parent.parent / "ComfyUI" / "output"
