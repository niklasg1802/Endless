# Endless dashboard

Config, progress, clip review and episode assembly for the scene pipeline.

```sh
./dashboard/run.sh
# prints: http://127.0.0.1:8199/?token=<generated>
```

Stdlib only — no framework, no database, no daemon state. Everything is read
from files and the live process table on each request, following the same
conventions as the ac2 dashboard.

## Security

- Binds **loopback only** (`ENDLESS_DASH_HOST`, default `127.0.0.1`). Put it
  behind Tailscale or a reverse proxy if you need remote access.
- **Token auth on every route, including reads.** Generated on first run into
  `dashboard/.token` (mode 0600), or set `ENDLESS_DASH_TOKEN`. Accepts
  `?token=`, `Authorization: Bearer`, or `X-Token`.
- `/media/` is **path-contained**: a request resolving outside the scene's own
  directory returns 404, so `../` traversal cannot read arbitrary files.

## What it does

| Area | Detail |
|---|---|
| Runtime | ComfyUI up/down and version, queue depth, per-GPU VRAM and utilisation, disk free |
| Downloads | Weight-download progress parsed from the download logs |
| Scenes | Per-scene progress for sheets, keyframes, clips and the final cut |
| Review | Inline playback of each clip and the final cut, keyframe stills, character sheets |
| Run | Launch any pipeline step and watch its log live |
| Config | Edit `scenes/defaults.json` |

## Running a step

The dashboard runs steps as subprocesses of `pipeline.scene`, one at a time, and
streams the log. It never starts or stops GPU work by itself — a step is only
started by an explicit click.

`plan` is read-only and safe. `sheets`, `keyframes`, `render` and `all` use the
GPU, so ComfyUI must be running and the target card should be free.

The status bar shows ComfyUI and GPU state so it is obvious when a run will fail
before you start it.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `ENDLESS_DASH_HOST` | `127.0.0.1` | bind address |
| `ENDLESS_DASH_PORT` | `8199` | port |
| `ENDLESS_DASH_TOKEN` | generated | auth token |
| `ENDLESS_COMFY_HOST` | `http://127.0.0.1:8188` | ComfyUI API |
| `ENDLESS_MODELS_DIR` | `../models` | where weights live (for the disk readout) |

## API

All routes need the token.

```
GET  /                          HTML cockpit
GET  /api/status                ComfyUI, GPUs, disk, running steps
GET  /api/scenes                scene list with per-step state
GET  /api/scene/<slug>          scene detail: characters, shots, keyframes, clips
GET  /api/downloads             download progress
GET  /api/config                defaults and backend info
POST /api/config                {"defaults": {...}} -> merge into scenes/defaults.json
POST /api/run                   {"slug": "...", "step": "plan|sheets|keyframes|render|assemble|all"}
GET  /api/log/<slug>            current/last run log and exit code
GET  /media/<slug>/<kind>/<file>  keyframe / clip / sheet bytes
```
