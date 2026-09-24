# Endless pipeline

Turns a scene description into one assembled video. Implements the architecture
recommended in the POC report (section 5) and tracked as issue #12.

```sh
python -m pipeline.scene plan      scenes/garage-portal.json   # what will happen, no spend
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
Solved by reference images. H3's Ref2VA accepts up to 9 reference images and 3
audio clips, so feeding the same character sheets into every keyframe keeps the
design identical across the scene.

So the video model never has to remember what a character looks like. It only has
to animate a frame that is already correct.

## Flow

```
character sheets (image model, once per character)
      |
      v
keyframe per shot (image model, sees the sheets)  ->  keyframes/<id>.png
      |
      v
animate the keyframe (H3, keyframe-first)         ->  clips/<id>.mp4
      |
      v
concat (ffmpeg, stream copy)                      ->  final.mp4
```

## Backends

`"backend": "local"` renders on the 3090 Ti through ComfyUI (no moderation, no
per-clip cost). `"backend": "cloud"` uses OpenRouter instead — useful for a quick
look, but cloud H3 rejects prompts that name the show and recognises the
characters in images, so it cannot render an accurate design (POC #1/#3).

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

## Requirements

- ComfyUI running locally: `/home/mik/2tb-disk/start-comfy.sh`
- Weights in ComfyUI's models tree (see `H3-SETUP.md`)
- `OPENROUTER_API_KEY` in `.env` (gitignored) for the image steps
- `ffmpeg` on PATH for assembly

**Do not render while a large download is running.** The 2 TB disk is NTFS over
FUSE on a spinning HDD and serialises badly.

## Limits

- Local H3 caps at **768 px on the short edge**; 2K is not possible with the open
  weights because the 2K module is not open-sourced. The default here is 864x480
  (0.4 MP), which is what the official guidance says to start at.
- One clip per shot. Longer continuous takes need `MiniMaxH3AddGuide` to anchor
  extra frames mid-video; not wired up yet.
- The writers' room (issue #10) does not exist, so scene JSON is written by hand
  for now. This orchestrator starts from the shot list.

## Not here yet

- **Shot-list generation from a script** — the LLM step from script.json.
- **QC** — a vision model plus Whisper checking design, dialogue and lip sync.
- **Audio references** — feeding H3 an audio clip for voice consistency (issue #8).
- **Retries** — a failed shot currently just stops the run.
