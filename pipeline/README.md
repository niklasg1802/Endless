# Endless pipeline

Turns a scene description into one assembled video. Implements the architecture
recommended in the POC report (section 5) and tracked as issue #12.

```sh
python -m pipeline.scene plan      scenes/garage-portal.json   # what will happen, no GPU
python -m pipeline.scene sheets    scenes/garage-portal.json   # character model sheets
python -m pipeline.scene keyframes scenes/garage-portal.json   # one still per shot
python -m pipeline.scene render    scenes/garage-portal.json   # animate each keyframe
python -m pipeline.scene assemble  scenes/garage-portal.json   # ffmpeg concat -> final.mp4
python -m pipeline.scene all       scenes/garage-portal.json   # all of the above
```

`--shot s1_garage` limits a step to one shot. `--force` redoes work that already
exists. Every step writes files, so any step can be re-run alone and a failure
does not lose the work before it.

## Why it works this way

The POC established two separate problems that are easy to confuse:

**Design** — does the character look right. Solved by an image model making the
keyframe first (POC #3): the name was not blocked and a show-accurate design came
back for about $0.07.

**Consistency** — does the character look the *same* in shot 4 as in shot 1.
Solved by reference images. Feed the same character model sheet into every
keyframe generation and the design holds. H3's Ref2VA also accepts up to 9
reference images and 3 audio clips for the video step.

So the video model never has to remember what a character looks like. It only has
to animate a frame that is already correct.

## Flow

```
character sheets (local image model, once per character)
      |
      v
keyframe per shot (local image model, conditioned on the sheets)  ->  keyframes/<id>.png
      |
      v
animate the keyframe (H3, keyframe-first)                        ->  clips/<id>.mp4
      |
      v
concat (ffmpeg, stream copy)                                     ->  final.mp4
```

## Everything runs locally

No metered API is required. Two local models do the work:

- **Images** — Qwen-Image-2.1, a 7B unified generate+edit model. One checkpoint
  does text-to-image *and* instruction editing with reference images, so the same
  model makes a model sheet and then a keyframe that matches it. Fits a 24 GB
  card with no offload. **Licence: Qwen Research License, non-commercial only** —
  fine for this project, which is personal use; the Apache-2.0 alternative is
  Qwen-Image-Edit-2511 if that ever changes.
- **Video** — MiniMax H3 through ComfyUI, keyframe-first. See `docs/rig-local-h3.md`.

Text work (writers' room, shot lists, critique) can run on a subscription via
ultra-zen's local proxy instead of paid API credits:

```sh
ultra-zen --proxy-only grok-4.5          # prints the port it binds
export ENDLESS_LLM_BASE_URL=http://127.0.0.1:<port>/v1
export ENDLESS_LLM_MODEL=grok-4.5
```

`pipeline/llm.py` uses that endpoint when `ENDLESS_LLM_BASE_URL` is set, and
falls back to OpenRouter otherwise. Note the proxy is **chat-completions only**:
it has no image endpoint and replaces incoming images with the text
`[image omitted]`, so it is usable for text and never for keyframes.

## Scene file

```json
{
  "title": "Garage Portal Test",
  "backend": "local",
  "width": 864, "height": 480, "seed": 101,
  "style_block": "shared art-style text prepended to every prompt",
  "characters": {
    "boy": { "sheet_prompt": "appearance description", "sheet": "sheets/boy.png" }
  },
  "shots": [
    {
      "id": "s1_garage",
      "characters": ["boy"],
      "seconds": 5,
      "keyframe_prompt": "the still frame to generate",
      "motion_prompt": "how it should move and what is said"
    }
  ]
}
```

`motion_prompt` is what the video model gets, so it carries the dialogue and
delivery notes (the POC wrote `burp` inline and it came out as a real burp).
`seconds` is converted to the frame count H3 requires (24 fps, snapped to the
model's 17k+5 grid, so 5 s becomes 124 frames).

## Prompting rules that matter

**When reference images are attached, do not describe the character's appearance
in the prompt.** An instruction-editing model treats those tokens as
instructions and overrides the reference image — which is exactly the design
drift the sheets exist to prevent. Describe only scene, background, lighting and
action. `build_keyframe_prompt` enforces this; do not "helpfully" add a
description of the character back in.

Flat cel-shaded output needs the style stated as a render pipeline, not an
adjective:

```
flat cel shading, bold clean thick black outlines, hard-edged shadow shapes,
limited flat colour palette, no gradients, no texture, no volumetric lighting,
2D cutout animation cel
```

## Requirements

- ComfyUI running locally, with the H3 and Qwen-Image-2.1 weights
  (`scripts/setup-rig.sh`, `scripts/download-h3-weights.sh`)
- `ffmpeg` on PATH for assembly

**Do not render while a large download is running.** On the reference rig the
models disk is NTFS over FUSE on a spinning HDD and serialises badly.

## Limits

- Local H3 caps at **768 px on the short edge**; 2K is not possible with the open
  weights because the 2K module is not open-sourced. The default here is 864x480
  (0.4 MP), which is what the official guidance says to start at.
- One clip per shot. Longer continuous takes need `MiniMaxH3AddGuide` to anchor
  extra frames mid-video; not wired up yet.
- There is no ready-made American-sitcom flat-cel LoRA for Qwen-Image-2.1, so a
  style LoRA may need training (issue #13).

## Not here yet

- **Shot-list generation from a script** — the LLM step from script.json.
- **QC** — a vision model plus Whisper checking design, dialogue and lip sync.
- **Audio references** — feeding H3 an audio clip for voice consistency (issue #8).
- **Retries** — a failed shot currently just stops the run.
