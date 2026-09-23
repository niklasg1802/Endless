# Endless – Proof of Concept Report (2026-09-23)

**Authors:** Niklas + Claude (Opus 5.5) · **Issues:** #1, #3, #5 · **PRs:** #2, #4 · **Clips:** [release `poc-2026-09-23`](https://github.com/niklasg1802/Endless/releases/tag/poc-2026-09-23)

## TL;DR

- **Goal:** fully AI-generated Rick and Morty episodes at the quality of the real show, produced offline (not a live stream), for personal use.
- **Result: it can be done.** MiniMax H3 produces 8-second shots whose style, voices and consistency across shots come very close to the show. **Humans rated the H3 voices and video "far better"** than the alternative (Veo 3.1 Lite).
- **Blocker in the cloud:** H3's API moderation rejects show and character names in text, and it **recognises the characters in images**. An accurate Morty therefore only works with **H3 running locally** on the 3090 Ti rig, where there is no moderation.
- **Method confirmed:** generate a correct keyframe with an image model first, then animate it with the video model. This fixes wrong character designs.
- **Total spend:** $2.62 of a $5 OpenRouter budget.
- **Next step:** get local H3 running on the rig (#6 → #7).

---

## 1. Project setup

- The repo `niklasg1802/Endless` is **public**. `raketenkater` has been invited as a collaborator with write access. Admin rights aren't possible on a personal repo; that would need a GitHub organization.
- **Rules for collaboration between agents** (Claude, ChatGPT/Codex, local models), see [`AGENTS.md`](../../AGENTS.md):
  - GitHub is the only shared state.
  - One task = one issue = one branch = one PR.
  - Agents claim an issue before starting and leave a state comment when they stop.
  - `status:*` and `agent:*` labels track who is doing what.
  - Only humans merge.
- `CLAUDE.md` just imports `AGENTS.md`. There's also a task issue form, a PR template, and a `.gitignore` for secrets and generated media.
- **The `protect-main` ruleset** requires a PR and resolved review threads, and blocks force-pushes and deleting `main`. No one can bypass it.
- **Decision records** live in [`docs/decisions/`](../decisions/): 0001 (agent collaboration) and 0002 (H3 as the primary video model).

## 2. Research

### 2.1 Do projects like this already exist?

| Project | Approach | Relevance |
|---|---|---|
| Nothing, Forever (AI Seinfeld, 2023) | LLM script + TTS + fixed 3D puppets, 24/7 stream | Coherent episodes, but stiff and flat |
| AI Sponge, Family Guy / South Park streams | Same recipe in Unity | Same trade-offs |
| "Infinite interdimensional cable" (Rehan Sheikh, Aug 2026) | MiniMax H3 Max driven by Twitch chat, Rick and Morty-like surreal clips | Looks great, but no episodes, no plot, about $4,300 per day |
| Infinite Slop (Pieter Levels + fal), Infinite TV (LTX) | Endless generated video steered by chat | Same: disconnected clips |
| Fable Showrunner | Closed commercial platform for generated episodes | Not usable |

**Gap:** we found no open project that produces *coherent* Rick and Morty episodes at show quality.

### 2.2 How the real show is made

- **Animation:** Toon Boom Harmony cutout rigs with modular parts and curved deformers. Backgrounds are painted in Photoshop, and After Effects is used for glows and portals.
- **Studios:** Burbank does the boards, designs, color keys and backgrounds; Bardel in Vancouver animates.
- **Writing:** Dan Harmon's **Story Circle** (8 beats), usually as two parallel circles (an A-plot adventure and a B-plot at home), plus a cold open, a ~22-minute runtime and a post-credits stinger.
- **Dialogue:** heavily **improvised**. The stammering, rambling and burps are the show's signature; clean LLM dialogue sounds wrong.
- **Voices:** Justin Roiland through season 6, then **Ian Cardoni** (Rick) and **Harry Belden** (Morty) from season 7.

### 2.3 Frameworks

| Framework | License / size | What it does | Fit |
|---|---|---|---|
| [HKUDS/ViMax](https://github.com/HKUDS/ViMax) | MIT, ~670k lines of Python | Idea/script → storyboard → reference images → keyframes → shots → assembly, with a consistency check | Best reference design, but built for short clips and cloud-only (H3 is only on its roadmap) |
| [OpenMontage](https://github.com/calesthio/OpenMontage) | AGPL-3.0 | Agent-driven general video production | Too generic, AGPL |
| [Toonflow](https://github.com/HBAI-Ltd/Toonflow-app) | Apache-2.0, TypeScript desktop app | Script → animated short drama | An app, not a library |

### 2.4 Cloud video models (OpenRouter, prices as of 2026-09-23)

| Model | $/s | Notes |
|---|---|---|
| **MiniMax H3** (`minimax/hailuo-3`) | 0.13 (2K, audio) + $0.04 per reference image | **Chosen.** Best voices and video in our test; strict moderation |
| MiniMax H3 Max | 0.05–0.08 | 480p/768p, no audio |
| Seedance 2.0 Fast / Mini / 2.0 | from 0.040 / 0.034 / 0.067 (480p) | Up to 9 reference images plus audio input |
| Kling 3.0 Std / Pro | 0.084–0.126 / 0.112–0.168 | Strong at multi-shot consistency |
| Veo 3.1 Lite / Fast / full | 0.03–0.08 / 0.08–0.10 / 0.20–0.60 | Lite tested: cheap and fast, but voices clearly worse than H3 |
| Wan 3.0 / 2.7 | from 0.043 / 0.10 | API only; no open weights for these versions |
| Sora 2 Pro | 0.30–0.50 | Expensive, strict about copyrighted characters |

### 2.5 Local video models (open weights, checked on Hugging Face)

| Model | Fits the 3090 Ti (24 GB)? | Notes |
|---|---|---|
| **MiniMax H3** (open since Aug 2026) | Yes, with int8 or GGUF (~21 GB video model; the 32B text encoder goes in RAM) | Same model as the cloud version. Ref2VA takes ≤9 images and ≤3 audio clips as references; 4-step turbo LoRA; ControlNet; **no moderation**. Community license allows personal use |
| Wan 2.2 (I2V-A14B, S2V-14B, Animate-2) | Yes | Largest LoRA ecosystem; S2V does lip sync from audio |
| LTX-2.5 (22B) | Yes (distilled GGUF) | Fastest; generates audio too |
| HunyuanVideo 1.5 (8.3B) | Yes, also on the 4070 | Lightweight |

The 3090 Ti is Ampere and has **no native FP8/FP4**, so we use the int8 or GGUF files, not fp8/nvfp4.

## 3. Experiments

All clips are generated media, kept out of the repo, and available in the [release](https://github.com/niklasg1802/Endless/releases/tag/poc-2026-09-23). The scripts are `poc/h3_cloud.py` and `poc/keyframe.py`; the prompts are in `poc/prompts/`.

### 3.1 H3 in the cloud: text-to-video (#1)

| Run | Input | Result | Cost | Time |
|---|---|---|---|---|
| shot1 | Prompt **naming** "Rick and Morty" | ❌ `input text sensitive (1026)` | $0 | 17 s |
| **shot1b** | Same scene described by appearance only | ✅ 8 s, 2560×1440, 24 fps, stereo | $1.04 | 290 s |

![shot1b start](https://github.com/niklasg1802/Endless/releases/download/poc-2026-09-23/shot1b_0.jpg)
![shot1b end](https://github.com/niklasg1802/Endless/releases/download/poc-2026-09-23/shot1b_5.jpg)

▶️ [shot1b_garage.mp4](https://github.com/niklasg1802/Endless/releases/download/poc-2026-09-23/shot1b_garage.mp4)

- **Style:** very close to the show: outlines, round eyes, drool, garage lab, lighting.
- **Rick** is recognisable. **Morty's design is off** (hair and head shape).
- **Dialogue** came out exactly as written (checked with Whisper), and the voices fit.
- **Misses:** the written burp didn't come out as a real burp; the ray gun fires a beam instead of opening a portal.

### 3.2 H3 in the cloud: consistency across shots (#1)

| Run | Input | Result | Cost | Time |
|---|---|---|---|---|
| **shot2** | New camera angle, a frame of shot1b as reference image | ✅ 8 s, 2K | $1.04 | 357 s |

![shot2](https://github.com/niklasg1802/Endless/releases/download/poc-2026-09-23/shot2_0.jpg)
![shot2 later](https://github.com/niklasg1802/Endless/releases/download/poc-2026-09-23/shot2_2.jpg)

▶️ [shot2_portal.mp4](https://github.com/niklasg1802/Endless/releases/download/poc-2026-09-23/shot2_portal.mp4)

- **Characters, garage and lighting stay consistent** after the camera change.
- The portal looks like the one in the show.
- Dialogue came out exactly as written, and both characters jump through the portal as scripted.

### 3.3 Keyframe first: fixing the design with an image model (#3)

| Run | Input | Result | Cost |
|---|---|---|---|
| kf_named | shot1b frame + "redraw as Morty from Rick and Morty" (Gemini 3.1 Flash Image) | ✅ Show-accurate Morty; the name was **not** blocked | $0.07 |
| kf_described | Same frame + a detailed description of the design | ✅ Show-accurate Morty with a nervous mouth | $0.07 |

| Source frame (H3) | Edited keyframe |
|---|---|
| ![src](https://github.com/niklasg1802/Endless/releases/download/poc-2026-09-23/kf_src.jpg) | ![kf](https://github.com/niklasg1802/Endless/releases/download/poc-2026-09-23/kf_described.png) |

### 3.4 Animating the keyframe (#3)

| Run | Model | Result | Cost | Time |
|---|---|---|---|---|
| shot3 | H3 (cloud), keyframe as first frame | ❌ `input image sensitive (1026)`: H3 recognises the character in the image | $0 | 20 s |
| **shot3_veo_lite** | Veo 3.1 Lite, keyframe as first frame, 720p | ✅ Morty stays correct for the whole clip | $0.40 | 65 s |

![shot3](https://github.com/niklasg1802/Endless/releases/download/poc-2026-09-23/shot3_0.jpg)
![shot3 later](https://github.com/niklasg1802/Endless/releases/download/poc-2026-09-23/shot3_2.jpg)

▶️ [shot3_veo_lite.mp4](https://github.com/niklasg1802/Endless/releases/download/poc-2026-09-23/shot3_veo_lite.mp4)

- **Design:** both characters stay stable. **Keyframe first works.**
- **Dialogue:** correct words, but no audible stutter or burp. The drool turns green, and it's only 720p.
- **Human verdict (Niklas):** *"H3 voices are far better in terms of audio and video."*

### 3.5 Costs

| Item | Cost |
|---|---|
| H3 shot1b + shot2 | $2.08 |
| 2 keyframes | $0.14 |
| Veo 3.1 Lite shot3 | $0.40 |
| Blocked jobs (3) | $0 |
| **Total** | **$2.62** |

## 4. What we learned

1. **The quality is achievable.** H3 already gets close to the show's style and voices without any fine-tuning.
2. **Cloud H3 can't produce accurate designs.** It blocks names in text and recognises the characters in images. Only local H3 can.
3. **Keyframe first works.** Image models fix designs cheaply ($0.07) and precisely; the video model then only has to animate.
4. **Reference images keep shots consistent**, even across camera changes.
5. **Voices matter more than we expected.** They're H3's biggest advantage over the alternatives.
6. **Still open:** real burps and stutters, the gag actually landing (the ray gun), and speed and quality on the rig.

## 5. Architecture (recommendation, decision pending in #11)

**Build our own thin orchestrator** (a few thousand lines of Python) on top of existing engines, rather than building on a framework:

- **Local generation:** ComfyUI, driven through its API (H3, ControlNet, LoRAs).
- **Cloud:** OpenRouter, for LLMs, image models and fallback video models.
- **Tools:** ffmpeg for assembly, faster-whisper and a vision LLM for quality checks.
- **Borrowed from ViMax** (MIT, with attribution): keyframe first, storyboard prompts, consistency checks.

Every step reads and writes **files**, which keeps each step testable, repeatable and open to approval:

```
Idea → ① writers' room (LLM) → script.json
     → ② show bible + reference images per character/location
     → ③ shot list (LLM)
     → ④ keyframes (image model)                ← confirmed in #3
     → ⑤ video per shot (H3 local / cloud)      ← confirmed in #1
     → ⑥ QC (vision LLM + Whisper), retry
     → ⑦ assembly (ffmpeg): music, SFX, credits
```

**Why not a framework:**
- Our core needs aren't covered: 22-minute episodes, Rick and Morty writing, local and cloud routing, approval steps.
- A small codebase is easier for several AI agents to work on than 670k lines of someone else's code.

**Cost reasoning:** a 22-minute episode is about 1,320 s, or about 4,000 s of generated video with retakes.
- H3 in the cloud: about **$520 per episode**. That's another reason local H3 on the rig is the main path.
- The cloud stays a fallback.

## 6. Plan

| Milestone | Content | Issues |
|---|---|---|
| **M-Rig** | Rig access, ComfyUI, local H3 | #6 → #7 → #8 |
| **M0** | Show bible: characters, structure, style, dialogue | #9 |
| **M1** | Writers' room → script JSON | #10 |
| **M2** | Architecture decision + pipeline skeleton, end-to-end 30–60 s scene | #11 → #12 |
| **M3** | H3 style LoRA on show frames | #13 |
| M4 | Full episode: 22 min, editing, music, credits | later |
| M5 | Extras: topic suggestions, ratings | later |

**Can start now:** #9 (show bible) and #11 (architecture decision, humans).
**Blocked on rig access:** #6, then #7, #8 and #13.

### Open decisions for the humans

1. **Rig access (blocks #6):** SSH host and user from the dev PC, driver status, ~100 GB free for the models.
2. **Architecture (#11):** own orchestrator (recommended) or building on ViMax.
3. **Continuity:** standalone episodes, or arcs that remember each other?
4. **Your role:** approve pitches, outlines and shots (recommended at the start), or fully automatic?
5. **Budget** per episode for the cloud fallback.
6. **Security:** rotate the OpenRouter key; it was pasted into a chat. The new key goes only into `.env`.

## 7. Legal and hygiene

- Personal, non-commercial use only. The repo is public, so it contains **no show assets, voice samples, model weights or training data**; those stay local and gitignored.
- The generated clips are published only as release assets. They can be removed by deleting the release, with nothing left in git history.
- The H3 community license allows personal use. Its restrictions target commercial offerings and third-party services.

## Sources

- [Rick and Morty – Wikipedia](https://en.wikipedia.org/wiki/Rick_and_Morty) · [Season 8](https://en.wikipedia.org/wiki/Rick_and_Morty_season_8) · [Mortynight Run](https://en.wikipedia.org/wiki/Mortynight_Run)
- [Toon Boom: Rick and Morty Emmy / 2D pipeline](https://www.toonboom.com/rick-and-morty-wins-its-first-emmy-and-the-case-for-2d-animation-series) · [Animation Magazine](https://www.animationmagazine.net/2013/12/intergalactic-travels-grandpa/) · [Bardel – Wikipedia](https://en.wikipedia.org/wiki/Bardel_Entertainment)
- [Story Circle – Looper](https://www.looper.com/209262/the-truth-about-the-rick-and-morty-story-circle/) · [Nerdist](https://nerdist.com/article/rick-and-morty-story-circle-dan-harmon/)
- [Improvised moments – Screen Rant](https://screenrant.com/rick-and-morty-improvised-moments-hilarious/) · [Hollywood Reporter: new voice actors](https://www.hollywoodreporter.com/tv/tv-news/rick-and-morty-new-voice-actors-revealed-casting-process-1235618102/)
- [Endless AI TV: $4,320/day](https://explainx.ai/blog/endless-ai-tv-stream-h3-max-interdimensional-cable-2026) · [Infinite TV – WaveSpeed](https://wavespeed.ai/blog/ai-workflows/infinite-tv-real-time-ai-video/) · [Nothing, Forever – Oxford Academic](https://academic.oup.com/adaptation/article/19/1/apag006/8524249) · [Showrunner – Gizmodo](https://gizmodo.com/showrunner-ai-generated-tv-show-streaming-service-1851510379)
- [OpenRouter video generation docs](https://openrouter.ai/docs/guides/overview/multimodal/video-generation.md) · [OpenRouter video models](https://openrouter.ai/api/v1/videos/models)
- [MiniMax-H3 model card](https://huggingface.co/MiniMaxAI/MiniMax-H3) · [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) · [unsloth GGUF](https://huggingface.co/unsloth/MiniMax-H3-GGUF)
- [Wan-AI](https://huggingface.co/Wan-AI) · [LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) · [HunyuanVideo 1.5](https://huggingface.co/Comfy-Org/HunyuanVideo_1.5_repackaged)
- [ViMax](https://github.com/HKUDS/ViMax) · [OpenMontage](https://github.com/calesthio/OpenMontage) · [Toonflow](https://github.com/HBAI-Ltd/Toonflow-app)
